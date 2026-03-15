"""勾稽校验引擎（本地规则为主）。

基于 Table_Structure_Analyzer 输出的结构化信息执行确定性数值校验：
- 科目名称模糊匹配构建对照映射
- 金额一致性校验（报表 vs 附注合计值）
- 附注表格内部勾稽（横纵加总）
- 余额变动公式校验（期初+增加-减少=期末）
- 其中项校验（子项之和 ≤ 父项）
"""
import json
import logging
import uuid
from typing import Dict, List, Optional, Tuple

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    MatchingEntry,
    MatchingMap,
    NoteSection,
    NoteTable,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    RiskLevel,
    StatementItem,
    StatementType,
    TableStructure,
)

logger = logging.getLogger(__name__)

# 浮点容差
TOLERANCE = 0.5


def _safe_float(val) -> Optional[float]:
    """安全转换为浮点数，支持千分位逗号格式（如 38,444,572.98）。"""
    if val is None:
        return None
    try:
        v = float(val)
        return v
    except (ValueError, TypeError):
        pass
    # 尝试去除千分位逗号后再转换
    try:
        s = str(val).replace(",", "").strip()
        if s:
            return float(s)
    except (ValueError, TypeError):
        pass
    return None


def _amounts_equal(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < TOLERANCE


class ReconciliationEngine:
    """勾稽校验引擎，所有数值校验为纯函数。"""

    # ─── 科目匹配 ───

    def build_matching_map(
        self,
        items: List[StatementItem],
        notes: List[NoteTable],
    ) -> MatchingMap:
        """基于标准科目映射模板构建对照映射，模板未命中时回退到模糊匹配。"""
        from .account_mapping_template import account_mapping_template

        entries: List[MatchingEntry] = []
        matched_note_ids: set = set()
        unmatched_items: List[str] = []

        for item in items:
            # 1) 优先使用模板映射
            template_notes: List[Tuple[str, float]] = []
            for note in notes:
                if account_mapping_template.match_note(
                    item.account_name, note.account_name, note.section_title
                ):
                    template_notes.append((note.id, 1.0))

            if template_notes:
                note_ids = [n[0] for n in template_notes[:3]]
                entries.append(MatchingEntry(
                    statement_item_id=item.id,
                    note_table_ids=note_ids,
                    match_confidence=1.0,
                ))
                matched_note_ids.update(note_ids)
                continue

            # 2) 回退到模糊匹配
            best_notes: List[Tuple[str, float]] = []
            for note in notes:
                score = self._match_score(item.account_name, note.account_name)
                if score >= 0.5:
                    best_notes.append((note.id, score))

            best_notes.sort(key=lambda x: x[1], reverse=True)

            if best_notes:
                note_ids = [n[0] for n in best_notes[:3]]
                confidence = best_notes[0][1]
                entries.append(MatchingEntry(
                    statement_item_id=item.id,
                    note_table_ids=note_ids,
                    match_confidence=confidence,
                ))
                matched_note_ids.update(note_ids)
            else:
                unmatched_items.append(item.id)

        unmatched_notes = [n.id for n in notes if n.id not in matched_note_ids]

        return MatchingMap(
            entries=entries,
            unmatched_items=unmatched_items,
            unmatched_notes=unmatched_notes,
        )

    # ─── 金额一致性校验 ───

    # 报表中的汇总行关键词 — 这些行是多个科目的合计，不对应具体附注披露，跳过金额核对
    STATEMENT_SUBTOTAL_KEYWORDS = [
        "合计", "总计", "总额", "小计", "净额",
    ]

    # 不应做金额核对的特殊科目名称关键词（包含即跳过）
    SKIP_AMOUNT_CHECK_KEYWORDS = [
        "相抵后净额", "抵销后净额",  # 递延所得税资产和负债相抵后净额
    ]

    # 现金流量表中有附注披露的科目关键词（仅"其他与XX活动有关的现金"等有明细表）
    # 其余现金流量表科目（如"处置固定资产收回的现金净额"、"投资支付的现金"等）无附注披露
    CASH_FLOW_NOTE_KEYWORDS = [
        "其他与经营活动有关",
        "其他与投资活动有关",
        "其他与筹资活动有关",
        "重要的投资活动有关",
        "重要的筹资活动有关",
    ]

    # 现金流量表科目名称特征（用于 statement_type 未正确标记时的兜底识别）
    CASH_FLOW_NAME_INDICATORS = [
        "收到的现金", "支付的现金", "收回的现金", "现金净额",
        "经营活动", "投资活动", "筹资活动",
        "现金及现金等价物",
    ]

    def _should_skip_amount_check(self, item: StatementItem) -> bool:
        """判断报表科目是否应跳过金额一致性核对。"""
        import re
        name = item.account_name
        # 所有者权益变动表：结构行/过程行，不对应具体附注披露表格
        if item.statement_type == StatementType.EQUITY_CHANGE:
            return True
        # 汇总行（如"非流动负债合计"）
        if any(name.endswith(kw) for kw in self.STATEMENT_SUBTOTAL_KEYWORDS):
            return True
        # 特殊科目（如"递延所得税资产和递延所得税负债相抵后净额"）
        if any(kw in name for kw in self.SKIP_AMOUNT_CHECK_KEYWORDS):
            return True
        # 报表中的"其中"子项（如"应付职工薪酬-短期薪酬"、"当期所得税费用"等）：
        # 子项没有独立的附注披露表格，其金额包含在父科目的附注表格中，
        # 不应单独与附注合计值比对（否则会用父科目的合计值来比对子项金额，必然不一致）。
        if item.is_sub_item:
            return True
        # 附注编号格式的科目名（如"(1) 固定资产情况"、"4.递延所得税"等）：
        # 这些是附注章节标题被误解析为报表科目，不是真正的报表行
        if re.match(r'^[（(]\d+[）)]', name) or re.match(r'^\d+[.、．]', name):
            return True
        # 现金流量表科目：仅白名单内的科目有附注披露
        is_cash_flow = (
            item.statement_type == StatementType.CASH_FLOW
            or any(kw in name for kw in self.CASH_FLOW_NAME_INDICATORS)
        )
        if is_cash_flow:
            if not any(kw in name for kw in self.CASH_FLOW_NOTE_KEYWORDS):
                return True
        # 现金流量表补充资料项目：这些项目的名称来自补充资料表格，
        # 不是独立的报表科目，不应与附注表格核对
        if any(kw in name for kw in self.CASHFLOW_SUPPLEMENT_ITEM_KEYWORDS):
            return True
        return False

    # 现金流量表补充资料中的项目名称关键词
    # 这些项目出现在补充资料中，不是独立的报表科目，不应与附注表格做金额核对
    CASHFLOW_SUPPLEMENT_ITEM_KEYWORDS = [
        "固定资产折旧", "油气资产折耗", "生产性生物资产折旧",
        "无形资产摊销", "长期待摊费用摊销",
        "处置固定资产", "固定资产报废",
        "公允价值变动损失", "财务费用",
        "投资损失", "递延所得税资产减少", "递延所得税负债增加",
        "存货的减少", "经营性应收项目", "经营性应付项目",
        "商誉减值损失", "资产减值准备",
        "现金的期末余额", "现金的期初余额",
        "现金等价物的期末余额", "现金等价物的期初余额",
        "现金及现金等价物净增加额",
    ]

    # 附注表格标题中含这些关键词时，表示仅披露重要/主要项目，
    # 报表金额应 ≥ 附注合计（附注是部分明细，不是全部）
    PARTIAL_DISCLOSURE_KEYWORDS = [
        "重要", "主要", "重大",
    ]

    def _is_partial_disclosure(self, note: NoteTable) -> bool:
        """判断附注表格是否仅披露部分项目（如"重要在建工程项目变动情况"）。"""
        combined = (note.section_title or "") + (note.account_name or "")
        return any(kw in combined for kw in self.PARTIAL_DISCLOSURE_KEYWORDS)

    # 资产组成部分子表关键词（国企报表中固定资产/无形资产等科目的附注
    # 常拆分为多张独立表格：原价表、累计折旧表、减值准备表、账面价值表。
    # 原价/累计折旧/减值准备表的合计值仅代表资产的某一组成部分，
    # 不应直接与报表余额（账面价值）比对。）
    _COMPONENT_SUBTABLE_KW = [
        "原价", "原值", "账面原值",
        "累计折旧", "累计摊销",
        "减值准备",
    ]

    @staticmethod
    def _is_component_subtable(note: NoteTable) -> bool:
        """判断附注表格是否为资产组成部分子表（原价/累计折旧/减值准备）。

        国企报表中，固定资产等科目的附注常拆分为多张独立表格，
        其中原价表、累计折旧表、减值准备表的合计值仅代表资产的某一组成部分，
        不应直接与报表余额（账面价值）比对。
        """
        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")
        return any(kw in title for kw in ReconciliationEngine._COMPONENT_SUBTABLE_KW)

    # 资产组成部分子表关键词（国企报表中固定资产/无形资产等科目的附注
    # 常拆分为多张独立表格：原价表、累计折旧表、减值准备表、账面价值表。
    # 原价/累计折旧/减值准备表的合计值仅代表资产的某一组成部分，
    # 不应直接与报表余额（账面价值）比对。）
    _COMPONENT_SUBTABLE_KW = [
        "原价", "原值", "账面原值",
        "累计折旧", "累计摊销",
        "减值准备",
    ]

    # 国企版资产负债表中，固定资产/无形资产等科目拆分为子行项目：
    # "固定资产原价"、"累计折旧"、"固定资产减值准备"、"固定资产净值"等。
    # 这些子行项目需要从合并附注表格的对应段落中提取值。
    _COMPONENT_ITEM_TO_SECTION = {
        "原价": "cost", "原值": "cost", "账面原值": "cost",
        "累计折旧": "amort", "累计摊销": "amort",
        "减值准备": "impair",
    }
    # 需要做子行段落提取的资产科目
    _SECTION_EXTRACT_ACCOUNTS = [
        "固定资产", "无形资产", "投资性房地产",
        "使用权资产", "油气资产", "生产性生物资产",
    ]

    # ─── 合并小计表格（同一张表包含两个科目各自的"小计"行） ───
    # 国企版"未经抵销的递延所得税资产和递延所得税负债"表格中，
    # 递延所得税资产和递延所得税负债各有一个"小计"行。
    # key = 报表科目关键词, value = 该科目在合并表中的段落标识关键词列表
    _COMBINED_SUBTOTAL_MAP: Dict[str, List[str]] = {
        "递延所得税资产": ["递延所得税资产"],
        "递延所得税负债": ["递延所得税负债"],
    }
    # 合并小计表格的标题特征：同时包含以下所有关键词才视为合并表
    _COMBINED_SUBTOTAL_TABLE_MARKERS = ["递延所得税资产", "递延所得税负债"]

    @staticmethod
    def _is_combined_subtotal_table(note: NoteTable) -> bool:
        """判断附注表格是否为合并小计表格（如递延所得税资产和负债合并表）。"""
        title = (note.account_name or "") + (note.section_title or "")
        title = title.replace(" ", "").replace("\u3000", "")
        return all(kw in title for kw in ReconciliationEngine._COMBINED_SUBTOTAL_TABLE_MARKERS)

    @staticmethod
    def _extract_combined_subtotal(
        note: NoteTable,
        section_keywords: List[str],
    ) -> Tuple[Optional[float], Optional[float]]:
        """从合并小计表格中提取指定段落的小计行期末/期初值。

        表格结构示例（递延所得税）：
          项目 | 期末余额-暂时性差异 | 期末余额-递延所得税 | 期初余额-暂时性差异 | 期初余额-递延所得税
          递延所得税资产:
            ...明细行...
            小计 | 6,645,328.04 | 1,861,632.01 | 9,670,760.85 | 2,419,049.17
          递延所得税负债:
            ...明细行...
            小计 | 163,431,416.60 | 40,120,854.15 | 8,265,217.92 | 2,066,304.48

        本方法找到 section_keywords 匹配的段落，然后提取该段落内"小计"行的值。
        对于有多个同期列的表格（如暂时性差异+递延所得税），取最后一个匹配列
        （即"递延所得税"列，而非"暂时性差异"列）。
        """
        closing_kw = ReconciliationEngine._CLOSING_COL_KW
        opening_kw = ReconciliationEngine._OPENING_COL_KW
        is_move = ReconciliationEngine._is_movement_col
        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]

        # 找所有期末/期初列索引，取最后一个（递延所得税列在暂时性差异列之后）
        hdr_closing_idx = -1
        hdr_opening_idx = -1
        for ci, h in enumerate(norm_h):
            if is_move(h):
                continue
            has_open = any(kw in h for kw in opening_kw)
            if any(kw in h for kw in closing_kw) and not has_open:
                hdr_closing_idx = ci  # 取最后一个期末列
            if has_open:
                hdr_opening_idx = ci  # 取最后一个期初列

        if hdr_closing_idx <= 0 and hdr_opening_idx <= 0:
            # 尝试从 header_rows 中查找
            for hr in (getattr(note, "header_rows", None) or []):
                for ci, cell in enumerate(hr):
                    h = str(cell or "").replace(" ", "").replace("\u3000", "")
                    has_open = any(kw in h for kw in opening_kw)
                    if any(kw in h for kw in closing_kw) and not has_open:
                        hdr_closing_idx = ci
                    if has_open:
                        hdr_opening_idx = ci

        in_target = False
        closing_val: Optional[float] = None
        opening_val: Optional[float] = None

        for row in note.rows:
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()

            # 检测段落标题行（包含段落关键词的行，如"递延所得税负债："）
            is_section_header = False
            for kw in ReconciliationEngine._COMBINED_SUBTOTAL_TABLE_MARKERS:
                if kw in first:
                    is_section_header = True
                    in_target = any(skw in first for skw in section_keywords)
                    break

            if is_section_header:
                continue

            if not in_target:
                continue

            # 在目标段落内找"小计"行
            if first in ("小计", "合计"):
                if hdr_closing_idx > 0 and hdr_closing_idx < len(row):
                    v = _safe_float(row[hdr_closing_idx])
                    if v is not None:
                        closing_val = v
                if hdr_opening_idx > 0 and hdr_opening_idx < len(row):
                    v = _safe_float(row[hdr_opening_idx])
                    if v is not None:
                        opening_val = v

                # 如果表头列索引没找到，尝试从小计行中取最后几个数值列
                if closing_val is None and opening_val is None:
                    numeric_indices = []
                    for ci in range(1, len(row)):
                        v = _safe_float(row[ci])
                        if v is not None:
                            numeric_indices.append(ci)
                    if len(numeric_indices) >= 2:
                        closing_val = _safe_float(row[numeric_indices[-2]])
                        opening_val = _safe_float(row[numeric_indices[-1]])
                    elif len(numeric_indices) == 1:
                        closing_val = _safe_float(row[numeric_indices[0]])

                break  # 找到小计行就停止

        return (closing_val, opening_val)


    @staticmethod
    def _is_component_subtable(note: NoteTable) -> bool:
        """判断附注表格是否为资产组成部分子表（原价/累计折旧/减值准备）。

        国企报表中，固定资产等科目的附注常拆分为多张独立表格，
        其中原价表、累计折旧表、减值准备表的合计值仅代表资产的某一组成部分，
        不应直接与报表余额（账面价值）比对。
        """
        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")
        return any(kw in title for kw in ReconciliationEngine._COMPONENT_SUBTABLE_KW)

    @staticmethod
    def _get_component_section_type(item_name: str) -> Optional[str]:
        """判断报表科目名是否为资产子行项目，返回对应的段落类型。

        例如："固定资产原价" → "cost"，"累计折旧" → "amort"
        返回 None 表示不是子行项目（是净值/账面价值行或主科目行）。
        """
        for kw, section in ReconciliationEngine._COMPONENT_ITEM_TO_SECTION.items():
            if kw in item_name:
                return section
        return None

    @staticmethod
    def _extract_component_section_totals(
        note: NoteTable,
        section_type: str,
    ) -> Tuple[Optional[float], Optional[float]]:
        """从合并附注表格中提取指定段落（cost/amort/impair）的期末/期初值。

        国企版固定资产等科目的附注表格包含多个段落（原值、累计折旧、减值准备、账面价值），
        每个段落有自己的合计行。本方法提取指定段落的合计值。
        """
        import re as _re
        section_pattern = _re.compile(r"^[一二三四五六七八九十]+[、.]")
        kw_map = {
            "cost": ReconciliationEngine._COST_SECTION_KW,
            "amort": ReconciliationEngine._AMORT_SECTION_KW,
            "impair": ReconciliationEngine._IMPAIR_SECTION_KW,
        }
        target_kw = kw_map.get(section_type)
        if not target_kw:
            return (None, None)

        closing_kw = ReconciliationEngine._CLOSING_COL_KW
        opening_kw = ReconciliationEngine._OPENING_COL_KW
        is_move = ReconciliationEngine._is_movement_col
        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]

        hdr_closing_idx = -1
        hdr_opening_idx = -1
        for ci, h in enumerate(norm_h):
            if is_move(h):
                continue
            has_open = any(kw in h for kw in opening_kw)
            if hdr_closing_idx < 0 and any(kw in h for kw in closing_kw) and not has_open:
                hdr_closing_idx = ci
            if hdr_opening_idx < 0 and has_open:
                hdr_opening_idx = ci

        if hdr_closing_idx <= 0 and hdr_opening_idx <= 0:
            return (None, None)

        total_col = -1
        for ci in range(len(note.headers) - 1, 0, -1):
            h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")
            if h in ("合计", "总计"):
                total_col = ci
                break

        closing_val: Optional[float] = None
        opening_val: Optional[float] = None
        in_target = False

        for row in note.rows:
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
            if section_pattern.match(first):
                in_target = any(kw in first for kw in target_kw)
                if in_target:
                    if hdr_closing_idx > 0 and hdr_closing_idx < len(row):
                        v = _safe_float(row[hdr_closing_idx])
                        if v is not None:
                            closing_val = v
                    if hdr_opening_idx > 0 and hdr_opening_idx < len(row):
                        v = _safe_float(row[hdr_opening_idx])
                        if v is not None:
                            opening_val = v
                continue
            if not in_target:
                continue
            if "期末" in first or "年末" in first:
                pick = total_col if total_col > 0 else hdr_closing_idx
                if 0 < pick < len(row):
                    v = _safe_float(row[pick])
                    if v is not None:
                        closing_val = v
            if "期初" in first or "年初" in first:
                pick = total_col if total_col > 0 else hdr_opening_idx
                if 0 < pick < len(row):
                    v = _safe_float(row[pick])
                    if v is not None:
                        opening_val = v

        return (closing_val, opening_val)

    # 明细/分类子表关键词（国企报表中，多个科目的附注包含多张表格：
    # 只有1级汇总表直接与报表余额核对，
    # 其余明细表仅参与 check_cross_table_consistency 的表间核对。）
    # 适用科目：应收票据、应收账款、其他应收款、合同资产、应收款项融资、
    # 长期应收款、预付款项、存货、应付职工薪酬、固定资产等。
    _DETAIL_SUBTABLE_KW = [
        # 应收类：账龄、组合、坏账准备
        "按账龄", "账龄组合", "账龄披露", "账龄列示",
        "组合方法", "组合计提", "按组合",
        "分类披露", "计提方法分类",
        "单项计提", "按单项",
        "坏账准备计提", "坏账准备变动",
        "前五名", "前5名",
        "实际核销", "核销情况",
        "收回或转回", "转回或收回",
        "逾期",
        "款项性质",
        # 应收票据专用
        "已质押", "已背书", "已贴现",
        "出票人未履约", "转为应收账款",
        "金融资产转移", "终止确认",
        # 预付款项
        "账龄超过",
        # 存货：跌价准备
        "跌价准备", "合同履约成本减值",
        # 合同资产
        "减值准备",
        # 应付职工薪酬：明细子表
        "短期薪酬列示", "设定提存计划列示", "设定受益计划",
        # 固定资产/在建工程/无形资产：明细子表
        "暂时闲置", "未办妥产权",
        # 在建工程：国企报表明细子表
        "重要在建工程", "本期变动情况", "本期计提",
        # 固定资产清理
        "固定资产清理",
        # 长期股权投资：明细子表
        "长期股权投资明细", "主要财务信息",
        # 受限制的货币资金
        "受限制",
    ]

    # 适用明细子表过滤的科目关键词
    _DETAIL_SUBTABLE_ACCOUNTS = [
        "应收票据", "应收账款", "其他应收款", "合同资产",
        "应收款项融资", "长期应收款",
        "预付款项", "预付账款",
        "存货",
        "应付职工薪酬",
        "固定资产", "在建工程", "无形资产",
        "投资性房地产", "使用权资产",
        "长期股权投资", "货币资金",
        "债权投资", "其他债权投资",
    ]

    def _is_detail_subtable(self, note: NoteTable) -> bool:
        """判断附注表格是否为明细/分类子表（非1级汇总表）。

        国企报表中，多个科目下有多张表格，只有1级汇总表应与报表余额
        直接核对，其余明细表（按账龄披露、按组合计提、坏账准备计提、
        跌价准备变动、短期薪酬列示等）仅参与表间核对。
        """
        acct = note.account_name or ""
        if not any(kw in acct for kw in self._DETAIL_SUBTABLE_ACCOUNTS):
            return False
        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")
        return any(kw in title for kw in self._DETAIL_SUBTABLE_KW)

    @staticmethod
    def _is_revenue_cost_detail_table(note: NoteTable) -> bool:
        """判断营业收入/营业成本合并表格是否为明细子表（按行业/地区/商品转让时间划分）。

        国企和上市报表中，营业收入、营业成本科目下通常有多张合并表格：
        - 汇总表（主营业务/其他业务/合计）→ 与报表余额直接核对
        - 按行业（或产品类型）划分 → 明细子表，仅参与表间核对
        - 按地区划分 → 明细子表
        - 按商品转让时间划分 → 明细子表

        只有汇总表应与报表余额直接比对。
        """
        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")
        return any(kw in title for kw in ReconciliationEngine._REVENUE_COST_DETAIL_KW)

    # 母公司附注表格识别关键词（section_title 中包含这些关键词时，视为母公司口径）
    PARENT_COMPANY_NOTE_KEYWORDS = [
        "母公司财务报表", "母公司报表", "公司财务报表主要项目",
        "公司报表主要项目", "母公司主要项目",
    ]

    @staticmethod
    def _is_parent_company_note(note: NoteTable) -> bool:
        """判断附注表格是否属于母公司报表附注（而非合并报表附注）。

        母公司附注表格的 section_title 通常包含"母公司财务报表主要项目注释"等关键词。
        """
        title = (note.section_title or "")
        return any(kw in title for kw in ReconciliationEngine.PARENT_COMPANY_NOTE_KEYWORDS)

    @staticmethod
    def _is_parent_company_note(
        note: NoteTable,
        ancestor_titles: Optional[List[str]] = None,
    ) -> bool:
        """判断附注表格是否属于母公司报表附注（而非合并报表附注）。

        优先检查 NoteSection 层级树中的祖先节点标题（ancestor_titles），
        兜底检查 note.section_title。
        """
        kws = ReconciliationEngine.PARENT_COMPANY_NOTE_KEYWORDS
        # 优先：检查祖先节点标题（从 NoteSection 层级树获取）
        if ancestor_titles:
            for t in ancestor_titles:
                if any(kw in t for kw in kws):
                    return True
        # 兜底：检查 section_title 本身
        title = (note.section_title or "")
        return any(kw in title for kw in kws)

    @staticmethod
    def _build_note_parent_section_map(
        note_sections: List[NoteSection],
    ) -> Dict[str, List[str]]:
        """遍历 NoteSection 层级树，构建 note_table_id → 祖先节点标题列表 的映射。

        返回值示例: {"note-uuid-1": ["五、合并财务报表项目注释", "1、货币资金"]}
        """
        result: Dict[str, List[str]] = {}

        def _walk(nodes: List['NoteSection'], ancestors: List[str]):
            for node in nodes:
                current_ancestors = ancestors + [node.title]
                for nid in node.note_table_ids:
                    result[nid] = current_ancestors
                if node.children:
                    _walk(node.children, current_ancestors)

        _walk(note_sections, [])
        return result

    # 标记"未找到附注合计值"的 finding，用于 report_review_engine 中触发 LLM 重新分析
    NOTE_VALUE_NOT_FOUND_TAG = "[未提取到附注合计值]"

    def check_amount_consistency(
        self,
        matching_map: MatchingMap,
        items: List[StatementItem],
        notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
        note_sections: Optional[List[NoteSection]] = None,
    ) -> List[ReportReviewFinding]:
        """基于 TableStructure 定位附注合计值，与报表余额比对。

        当一个报表科目匹配了多个附注表格时，只要有任一表格的金额与报表一致，
        就视为该科目校验通过（跳过变动表等辅助表格的误报）。

        对于"重要项目"类附注表格（仅披露部分明细），采用宽松比对：
        报表金额 ≥ 附注合计即视为通过。

        当报表科目有余额但所有匹配附注表格均未提取到对应合计值时，
        生成"未找到附注合计值"的警告 finding，提示结构识别可能不完整。

        note_sections: 附注层级结构树，用于判断附注表格所属的母公司/合并口径。
        """
        findings: List[ReportReviewFinding] = []
        item_map = {i.id: i for i in items}
        note_map = {n.id: n for n in notes}

        # 构建 note_table_id → 祖先标题 映射，用于判断母公司/合并口径
        ancestor_map: Dict[str, List[str]] = {}
        if note_sections:
            ancestor_map = self._build_note_parent_section_map(note_sections)

        for entry in matching_map.entries:
            item = item_map.get(entry.statement_item_id)
            if not item:
                continue

            # 跳过不需要金额核对的科目（汇总行、无附注披露的现金流量表科目等）
            if self._should_skip_amount_check(item):
                continue

            # 收集所有匹配表格的校验结果
            closing_matched = False
            opening_matched = False
            closing_findings: List[ReportReviewFinding] = []
            opening_findings: List[ReportReviewFinding] = []
            # 跟踪是否有任何表格提取到了对应值
            any_closing_value_found = False
            any_opening_value_found = False
            # 收集所有有效匹配的附注表格 ID（用于"未找到值"时的 finding）
            valid_note_ids: List[str] = []

            for note_id in entry.note_table_ids:
                note = note_map.get(note_id)
                ts = table_structures.get(note_id)
                if not note or not ts:
                    continue

                valid_note_ids.append(note_id)
                is_partial = self._is_partial_disclosure(note)

                # 跳过资产组成部分子表（原价/累计折旧/减值准备），
                # 它们的合计值不代表报表余额（账面价值）
                if self._is_component_subtable(note):
                    valid_note_ids.pop()
                    continue

                # 跳过应收类科目的明细/分类子表（按账龄、按组合、坏账准备计提等），
                # 这些表仅参与表间核对，不与报表余额直接比对
                if self._is_detail_subtable(note):
                    valid_note_ids.pop()
                    continue

                # 跳过营业收入/营业成本的明细子表（按行业、按地区、按商品转让时间划分），
                # 仅汇总表（主营业务/其他业务/合计）与报表余额直接比对
                if (self._is_revenue_cost_combined_table(note)
                        and self._is_revenue_cost_detail_table(note)):
                    valid_note_ids.pop()
                    continue

                ancestors = ancestor_map.get(note_id)
                is_parent_note = self._is_parent_company_note(note, ancestors)

                # 根据附注口径选择对应的报表余额：
                # 母公司附注 → 用公司数；合并附注 → 用合并数
                if is_parent_note and item.is_consolidated:
                    stmt_closing = item.company_closing_balance
                    stmt_opening = item.company_opening_balance
                    scope_label = "母公司"
                else:
                    stmt_closing = item.closing_balance
                    stmt_opening = item.opening_balance
                    scope_label = "合并" if is_parent_note is False and item.is_consolidated else ""

                # 获取附注合计值（优先用 LLM 识别的 cell，兜底用规则引擎）
                note_closing = self._get_cell_value(note, ts.closing_balance_cell)
                note_opening = self._get_cell_value(note, ts.opening_balance_cell)

                # 特殊处理：营业收入/营业成本合并表格
                # 这类表格一张表包含收入和成本两组列，需按科目名称定位正确的列
                if self._is_revenue_cost_combined_table(note):
                    rc_closing, rc_opening = self._extract_revenue_cost_from_combined_table(
                        note, item.account_name,
                    )
                    if rc_closing is not None:
                        note_closing = rc_closing
                    if rc_opening is not None:
                        note_opening = rc_opening

                # 规则引擎：始终运行，用于兜底和交叉验证
                rule_closing, rule_opening = self._extract_note_totals_by_rules(note)

                # 国企版资产子行项目（如"固定资产原价"、"累计折旧"）：
                # 从合并附注表格的对应段落提取值，而非使用账面价值合计
                comp_section = self._get_component_section_type(item.account_name)
                if comp_section and any(kw in (note.account_name or "") for kw in self._SECTION_EXTRACT_ACCOUNTS):
                    sec_closing, sec_opening = self._extract_component_section_totals(note, comp_section)
                    if sec_closing is not None or sec_opening is not None:
                        note_closing = sec_closing
                        note_opening = sec_opening
                        rule_closing = sec_closing
                        rule_opening = sec_opening

                # 合并小计表格（如"递延所得税资产和递延所得税负债"）：
                # 从合并表中提取对应段落的"小计"行值
                if self._is_combined_subtotal_table(note):
                    norm_item = item.account_name.replace(" ", "").replace("\u3000", "")
                    for item_kw, sec_kws in self._COMBINED_SUBTOTAL_MAP.items():
                        if item_kw in norm_item:
                            sub_closing, sub_opening = self._extract_combined_subtotal(note, sec_kws)
                            if sub_closing is not None or sub_opening is not None:
                                note_closing = sub_closing
                                note_opening = sub_opening
                                rule_closing = sub_closing
                                rule_opening = sub_opening
                            break

                # 兜底：LLM 未识别出 cell 时，用规则引擎结果
                if note_closing is None and rule_closing is not None:
                    note_closing = rule_closing
                if note_opening is None and rule_opening is not None:
                    note_opening = rule_opening

                # 交叉验证：检测 LLM 是否把期末/期初搞反
                # 当 LLM 和规则引擎都提取到了值，且 LLM 的 closing 等于规则的 opening
                # 且 LLM 的 opening 等于规则的 closing，说明 LLM 搞反了，用规则引擎纠正
                if (note_closing is not None and note_opening is not None
                        and rule_closing is not None and rule_opening is not None
                        and not _amounts_equal(note_closing, rule_closing)
                        and _amounts_equal(note_closing, rule_opening)
                        and _amounts_equal(note_opening, rule_closing)):
                    note_closing, note_opening = rule_closing, rule_opening

                if note_closing is not None:
                    any_closing_value_found = True
                if note_opening is not None:
                    any_opening_value_found = True

                # 期末余额比对
                if stmt_closing is not None and note_closing is not None:
                    if _amounts_equal(stmt_closing, note_closing):
                        closing_matched = True
                    elif is_partial and stmt_closing >= note_closing - TOLERANCE:
                        closing_matched = True
                    elif (rule_closing is not None
                          and not _amounts_equal(note_closing, rule_closing)
                          and _amounts_equal(stmt_closing, rule_closing)):
                        # LLM 指向了错误行（如原价合计而非账面价值合计），
                        # 规则引擎的值与报表一致 → 采信规则引擎，视为通过
                        closing_matched = True
                    else:
                        # 如果规则引擎值与报表更接近，用规则引擎值报告差异
                        effective_closing = note_closing
                        if (rule_closing is not None
                                and not _amounts_equal(note_closing, rule_closing)
                                and abs((rule_closing or 0) - stmt_closing) < abs(note_closing - stmt_closing)):
                            effective_closing = rule_closing
                        diff = round(stmt_closing - effective_closing, 2)
                        scope_desc = f"（{scope_label}）" if scope_label else ""
                        closing_findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                            account_name=item.account_name,
                            statement_amount=stmt_closing,
                            note_amount=effective_closing,
                            difference=diff,
                            location=f"附注-{item.account_name}-{note.section_title}-期末余额",
                            description=f"报表期末余额{scope_desc}{stmt_closing}与附注合计{effective_closing}不一致，差异{diff}",
                            risk_level=self._assess_risk(abs(diff), stmt_closing),
                            reasoning=f"校验公式: 报表期末余额{scope_desc}({stmt_closing}) - 附注合计({effective_closing}) = {diff}",
                            note_table_ids=[note_id],
                        ))

                # 期初余额比对
                if stmt_opening is not None and note_opening is not None:
                    if _amounts_equal(stmt_opening, note_opening):
                        opening_matched = True
                    elif is_partial and stmt_opening >= note_opening - TOLERANCE:
                        opening_matched = True
                    elif (rule_opening is not None
                          and not _amounts_equal(note_opening, rule_opening)
                          and _amounts_equal(stmt_opening, rule_opening)):
                        # LLM 指向了错误行，规则引擎的值与报表一致 → 采信规则引擎
                        opening_matched = True
                    else:
                        effective_opening = note_opening
                        if (rule_opening is not None
                                and not _amounts_equal(note_opening, rule_opening)
                                and abs((rule_opening or 0) - stmt_opening) < abs(note_opening - stmt_opening)):
                            effective_opening = rule_opening
                        diff = round(stmt_opening - effective_opening, 2)
                        scope_desc = f"（{scope_label}）" if scope_label else ""
                        opening_findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                            account_name=item.account_name,
                            statement_amount=stmt_opening,
                            note_amount=effective_opening,
                            difference=diff,
                            location=f"附注-{item.account_name}-{note.section_title}-期初余额",
                            description=f"报表期初余额{scope_desc}{stmt_opening}与附注合计{effective_opening}不一致，差异{diff}",
                            risk_level=self._assess_risk(abs(diff), stmt_opening),
                            reasoning=f"校验公式: 报表期初余额{scope_desc}({stmt_opening}) - 附注合计({effective_opening}) = {diff}",
                            note_table_ids=[note_id],
                        ))

            # 只有当所有匹配表格都不一致时，才报告差异最小的那个 finding
            if not closing_matched and closing_findings:
                best = min(closing_findings, key=lambda f: abs(f.difference or 0))
                findings.append(best)
            if not opening_matched and opening_findings:
                best = min(opening_findings, key=lambda f: abs(f.difference or 0))
                findings.append(best)

            # 报表科目有余额但所有附注表格都没提取到对应值 → 生成警告
            # 但如果所有匹配表格的表头中都没有对应的期初/期末列，说明该表格本身
            # 就不披露该期间数据（如国企版"会计利润与所得税费用调整过程"只有本期数），
            # 此时不应报警告。
            if valid_note_ids:
                has_closing = item.closing_balance is not None and item.closing_balance != 0
                has_opening = item.opening_balance is not None and item.opening_balance != 0

                # 检查匹配表格的表头中是否存在期末/期初列
                # 仅当表头中能识别出至少一种期间列时，才根据缺失情况抑制警告；
                # 如果表头完全无法识别（如"数据A"），仍然保留警告。
                any_table_has_closing_col = False
                any_table_has_opening_col = False
                any_table_has_period_col = False  # 是否有任何可识别的期间列
                for nid in valid_note_ids:
                    n = note_map.get(nid)
                    if not n:
                        continue
                    hdrs = " ".join(str(h or "") for h in (n.headers or []))
                    if any(kw in hdrs for kw in self._CLOSING_COL_KW):
                        any_table_has_closing_col = True
                        any_table_has_period_col = True
                    if any(kw in hdrs for kw in self._OPENING_COL_KW):
                        any_table_has_opening_col = True
                        any_table_has_period_col = True

                # 抑制条件：表头能识别出期间列，但明确缺少对应的期末/期初列
                suppress_closing_warn = any_table_has_period_col and not any_table_has_closing_col
                suppress_opening_warn = any_table_has_period_col and not any_table_has_opening_col

                if has_closing and not any_closing_value_found and not closing_matched and not suppress_closing_warn:
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                        account_name=item.account_name,
                        statement_amount=item.closing_balance,
                        note_amount=None,
                        difference=None,
                        location=f"附注-{item.account_name}-期末余额",
                        description=f"{self.NOTE_VALUE_NOT_FOUND_TAG} 报表期末余额{item.closing_balance}，但匹配的{len(valid_note_ids)}个附注表格均未识别出期末合计值，可能是表格结构识别不完整",
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=f"报表期末余额={item.closing_balance}，匹配附注表格{len(valid_note_ids)}个，均未提取到closing_balance_cell",
                        note_table_ids=valid_note_ids,
                    ))

                if has_opening and not any_opening_value_found and not opening_matched and not suppress_opening_warn:
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                        account_name=item.account_name,
                        statement_amount=item.opening_balance,
                        note_amount=None,
                        difference=None,
                        location=f"附注-{item.account_name}-期初余额",
                        description=f"{self.NOTE_VALUE_NOT_FOUND_TAG} 报表期初余额{item.opening_balance}，但匹配的{len(valid_note_ids)}个附注表格均未识别出期初合计值，可能是表格结构识别不完整",
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=f"报表期初余额={item.opening_balance}，匹配附注表格{len(valid_note_ids)}个，均未提取到opening_balance_cell",
                        note_table_ids=valid_note_ids,
                    ))

        return findings

    # ─── 附注表格内部勾稽 ───

    # 这些表格是汇总性质的财务信息摘要，行之间相互独立，不适用纵向加总/其中项/余额变动校验
    SKIP_INTEGRITY_KEYWORDS = [
        "主要财务信息",
        "重要合营企业",
        "重要联营企业",
        "重要合资企业",
        "不重要的合营企业",
        "不重要的联营企业",
    ]

    def _should_skip_integrity(self, note_table: NoteTable) -> bool:
        """判断表格是否应跳过完整性校验（汇总性质的财务信息表格）。"""
        combined = (note_table.section_title or "") + (note_table.account_name or "")
        if any(kw in combined for kw in self.SKIP_INTEGRITY_KEYWORDS):
            return True
        # 未分配利润表有专用校验，跳过通用纵向加总
        if self._is_undistributed_profit_table(note_table):
            return True
        return False

    # ─── 未分配利润专用校验 ───

    UNDISTRIBUTED_PROFIT_KEYWORDS = ["未分配利润"]

    @staticmethod
    def _is_undistributed_profit_table(note_table: NoteTable) -> bool:
        """判断是否为未分配利润表格。"""
        combined = (note_table.section_title or "") + (note_table.account_name or "")
        return "未分配利润" in combined

    def check_undistributed_profit(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """未分配利润表专用校验。

        表格结构（典型）：
            行标签                          本期数/期末数    上期数/期初数
            调整后 期初未分配利润             A1              B1
            加：本期归属于母公司净利润        A2              B2
                其他（可能多行）              ...             ...
            减：提取法定盈余公积              A3              B3
                其他（可能多行）              ...             ...
            期末未分配利润                    A4              B4

        校验规则：
        1. 纵向公式：A1 + sum(加项) - sum(减项) = A4（每列独立校验）
        2. 跨期衔接：本期列的"调整后期初未分配利润" = 上期列的"期末未分配利润"
        """
        findings: List[ReportReviewFinding] = []
        if not note_table.rows:
            return findings

        rows = note_table.rows
        headers = note_table.headers or []

        # ── 定位关键行 ──
        opening_row_idx = None   # "调整后 期初未分配利润" 行 / 国企"本期期初余额"行
        closing_row_idx = None   # "期末未分配利润" 行 / 国企"本期期末余额"行
        add_start = None         # "加：" 区域起始行 / 国企"本期增加额"行
        sub_start = None         # "减：" 区域起始行 / 国企"本期减少额"行

        for ri, row in enumerate(rows):
            label = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
            # 上市格式
            if ("期初未分配利润" in label or "期初未分配" in label) and opening_row_idx is None:
                opening_row_idx = ri
            if ("期末未分配利润" in label or "期末未分配" in label) and closing_row_idx is None:
                closing_row_idx = ri
            # 国企格式
            if "本期期初余额" in label and opening_row_idx is None:
                opening_row_idx = ri
            if "本期期末余额" in label and closing_row_idx is None:
                closing_row_idx = ri
            # 上市格式：加/减
            if label.startswith("加") or label.startswith("加：") or label.startswith("加:"):
                if add_start is None:
                    add_start = ri
            if label.startswith("减") or label.startswith("减：") or label.startswith("减:"):
                if sub_start is None:
                    sub_start = ri
            # 国企格式：本期增加额/本期减少额
            if "本期增加额" in label and add_start is None:
                add_start = ri
            if "本期减少额" in label and sub_start is None:
                sub_start = ri

        if opening_row_idx is None or closing_row_idx is None:
            return findings

        # 检测是否为国企格式（"本期增加额"/"本期减少额"行本身包含合计值）
        is_soe_format = False
        for ri in (add_start, sub_start):
            if ri is not None:
                lbl = str(rows[ri][0] if rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()
                if "本期增加额" in lbl or "本期减少额" in lbl:
                    is_soe_format = True
                    break

        # 如果没有明确的"加："/"减："标记，尝试推断：
        # 期初行之后到"减"之前为加项，"减"之后到期末行之前为减项
        if add_start is None:
            add_start = opening_row_idx + 1
        if sub_start is None:
            # 没有减项区域，所有中间行都是加项
            sub_start = closing_row_idx

        # ── 识别数值列（跳过第一列标签列）──
        num_cols = []
        for ci in range(1, len(headers)):
            num_cols.append(ci)
        if not num_cols:
            return findings

        # ── 逐列校验纵向公式 ──
        for ci in num_cols:
            opening_val = self._get_row_col_value(note_table, opening_row_idx, ci)
            closing_val = self._get_row_col_value(note_table, closing_row_idx, ci)
            if opening_val is None or closing_val is None:
                continue

            if is_soe_format:
                # 国企格式：直接取"本期增加额"和"本期减少额"行的值
                add_sum = self._get_row_col_value(note_table, add_start, ci) or 0.0
                sub_sum = self._get_row_col_value(note_table, sub_start, ci) or 0.0
            else:
                # 上市格式：汇总加项（add_start 到 sub_start 之间，排除小计行和空行）
                add_sum = 0.0
                for ri in range(add_start, sub_start):
                    if ri == opening_row_idx:
                        continue
                    label = str(rows[ri][0] if rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()
                    # 跳过"小计"行和纯标记行（如"加："本身）
                    if "小计" in label or label in ("加：", "加:", "加", "减：", "减:", "减"):
                        continue
                    v = self._get_row_col_value(note_table, ri, ci)
                    if v is not None:
                        add_sum += v

                # 汇总减项（sub_start 到 closing_row_idx 之间）
                sub_sum = 0.0
                for ri in range(sub_start, closing_row_idx):
                    label = str(rows[ri][0] if rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()
                    if "小计" in label or label in ("加：", "加:", "加", "减：", "减:", "减"):
                        continue
                    v = self._get_row_col_value(note_table, ri, ci)
                    if v is not None:
                        sub_sum += v

            expected = opening_val + add_sum - sub_sum
            if not _amounts_equal(expected, closing_val):
                diff = round(expected - closing_val, 2)
                col_label = headers[ci] if ci < len(headers) else f"列{ci + 1}"
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=note_table.account_name,
                    location=f"附注-{note_table.account_name}-{note_table.section_title}-{col_label}",
                    description=(
                        f"未分配利润纵向公式不平：期初({opening_val})"
                        f"+加项({add_sum})-减项({sub_sum})={expected}，"
                        f"期末({closing_val})，差异{diff}"
                    ),
                    difference=diff,
                    statement_amount=expected,
                    note_amount=closing_val,
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=(
                        f"公式: {opening_val}+{add_sum}-{sub_sum}={expected}, "
                        f"实际期末={closing_val}"
                    ),
                    note_table_ids=[note_table.id],
                ))

        # ── 跨期衔接校验 ──
        # 本期列的"调整后期初未分配利润" 应等于 上期列的"期末未分配利润"
        # 表头通常为 [项目, 本期数/期末数, 上期数/期初数]
        if len(num_cols) >= 2:
            closing_col = None  # 本期/期末列
            opening_col = None  # 上期/期初列
            closing_kw = self._CLOSING_COL_KW
            opening_kw = self._OPENING_COL_KW
            for ci in num_cols:
                h = str(headers[ci] if ci < len(headers) else "").replace(" ", "").replace("\u3000", "")
                if opening_col is None and any(kw in h for kw in opening_kw):
                    opening_col = ci
                elif closing_col is None and any(kw in h for kw in closing_kw):
                    closing_col = ci
            # fallback：第一个数值列=本期，第二个=上期
            if closing_col is None and opening_col is None and len(num_cols) >= 2:
                closing_col = num_cols[0]
                opening_col = num_cols[1]

            if closing_col is not None and opening_col is not None:
                # 本期列的期初值
                current_opening = self._get_row_col_value(
                    note_table, opening_row_idx, closing_col
                )
                # 上期列的期末值
                prior_closing = self._get_row_col_value(
                    note_table, closing_row_idx, opening_col
                )
                if (current_opening is not None and prior_closing is not None
                        and not _amounts_equal(current_opening, prior_closing)):
                    diff = round(current_opening - prior_closing, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=note_table.account_name,
                        location=f"附注-{note_table.account_name}-{note_table.section_title}-跨期衔接",
                        description=(
                            f"跨期衔接不平：本期列的调整后期初未分配利润({current_opening})"
                            f"≠上期列的期末未分配利润({prior_closing})，差异{diff}"
                        ),
                        difference=diff,
                        statement_amount=current_opening,
                        note_amount=prior_closing,
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=(
                            f"跨期衔接: 本期期初={current_opening}, "
                            f"上期期末={prior_closing}"
                        ),
                        note_table_ids=[note_table.id],
                    ))

        return findings

    def check_note_table_integrity(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """基于 LLM 识别的合计行/列结构校验横纵加总。"""
        findings: List[ReportReviewFinding] = []

        # 跳过汇总性质的财务信息表格（如"重要合营企业的主要财务信息"及其续表）
        if self._should_skip_integrity(note_table):
            return findings

        # 纵向加总校验：数据行之和 == 合计行
        for total_idx in table_structure.total_row_indices:
            data_indices = self._get_data_rows_for_total(table_structure, total_idx)
            if not data_indices:
                continue

            for col in table_structure.columns:
                if col.semantic in ("label", "other"):
                    continue

                total_val = self._get_row_col_value(note_table, total_idx, col.col_index)
                if total_val is None:
                    continue

                data_sum = 0.0
                has_data = False
                # 构建行索引→sign映射，用于纵向加总时区分加减行
                row_sign_map: Dict[int, int] = {
                    r.row_index: r.sign for r in table_structure.rows
                }
                for di in data_indices:
                    v = self._get_row_col_value(note_table, di, col.col_index)
                    if v is not None:
                        sign = row_sign_map.get(di, 1)
                        data_sum += sign * v
                        has_data = True

                if has_data and not _amounts_equal(data_sum, total_val):
                    diff = round(data_sum - total_val, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=note_table.account_name,
                        statement_amount=total_val,
                        note_amount=data_sum,
                        difference=diff,
                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{total_idx + 1}行合计-列{col.col_index + 1}",
                        description=f"纵向加总不平：数据行合计{data_sum}，合计行{total_val}，差异{diff}",
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=f"校验: sum(数据行)={data_sum}, 合计行={total_val}, 差异={diff}",
                        note_table_ids=[note_table.id],
                    ))

        return findings

    # ─── 余额变动公式校验 ───

    def check_balance_formula(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """校验 期初+增加-减少=期末 余额变动公式。"""
        findings: List[ReportReviewFinding] = []
        if self._should_skip_integrity(note_table):
            return findings
        if not table_structure.has_balance_formula:
            return findings

        # 收集各语义列（可能有多个增加/减少列）
        opening_cols = [c.col_index for c in table_structure.columns if c.semantic == "opening_balance"]
        closing_cols = [c.col_index for c in table_structure.columns if c.semantic == "closing_balance"]
        increase_cols = [c.col_index for c in table_structure.columns if c.semantic == "current_increase"]
        decrease_cols = [c.col_index for c in table_structure.columns if c.semantic == "current_decrease"]

        if not opening_cols or not closing_cols:
            return findings
        # 如果没有增减列，无法校验公式
        if not increase_cols and not decrease_cols:
            return findings

        opening_col = opening_cols[0]
        closing_col = closing_cols[0]

        for row_struct in table_structure.rows:
            # 跳过表头行和其中项行（其中项是父项的部分拆分，不一定满足余额变动公式）
            if row_struct.role in ("header", "sub_item"):
                continue

            opening = self._get_row_col_value(note_table, row_struct.row_index, opening_col)
            closing = self._get_row_col_value(note_table, row_struct.row_index, closing_col)

            if opening is None or closing is None:
                continue

            # 汇总所有增加列
            total_increase = 0.0
            for ic in increase_cols:
                v = self._get_row_col_value(note_table, row_struct.row_index, ic)
                if v is not None:
                    total_increase += v

            # 汇总所有减少列
            total_decrease = 0.0
            for dc in decrease_cols:
                v = self._get_row_col_value(note_table, row_struct.row_index, dc)
                if v is not None:
                    total_decrease += v

            expected = opening + total_increase - total_decrease
            if not _amounts_equal(expected, closing):
                diff = round(expected - closing, 2)
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=note_table.account_name,
                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_struct.row_index + 1}行'{row_struct.label}'",
                    description=f"余额变动公式不平：期初{opening}+增加{total_increase}-减少{total_decrease}={expected}，期末{closing}，差异{diff}",
                    difference=diff,
                    statement_amount=expected,
                    note_amount=closing,
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=f"公式: {opening}+{total_increase}-{total_decrease}={expected}, 实际期末={closing}",
                    note_table_ids=[note_table.id],
                ))

        return findings

    # ─── 宽表横向公式校验（LLM 辅助识别列语义，本地数值验证）───

    def check_wide_table_formula(
        self,
        note_table: NoteTable,
        wide_table_formula: dict,
    ) -> List[ReportReviewFinding]:
        """根据 LLM 识别的宽表公式结构，逐行验证横向公式。

        支持两种格式：
        - movement（变动公式型/国企版）：期初 + 变动列 = 期末
        - category_sum（分类合计型/上市版）：各分类数据列之和 = 合计列

        wide_table_formula 格式由 TableStructureAnalyzer.analyze_wide_table_formula 返回。
        所有数值计算在本地完成，LLM 只提供列语义和符号。
        """
        findings: List[ReportReviewFinding] = []
        if not wide_table_formula or "columns" not in wide_table_formula:
            return findings

        columns = wide_table_formula["columns"]

        # 判断公式类型：优先使用 LLM 返回的 formula_type，否则根据列角色自动推断
        formula_type = wide_table_formula.get("formula_type", "")
        if not formula_type:
            has_total = any(c.get("role") == "total" for c in columns)
            has_data = any(c.get("role") == "data" for c in columns)
            has_opening = any(c.get("role") == "opening" for c in columns)
            if has_total and has_data:
                formula_type = "category_sum"
            elif has_opening:
                formula_type = "movement"
            else:
                formula_type = "movement"

        if formula_type == "category_sum":
            return self._check_wide_table_category_sum(note_table, wide_table_formula)
        else:
            return self._check_wide_table_movement(note_table, wide_table_formula)

    def _check_wide_table_movement(
        self,
        note_table: NoteTable,
        wide_table_formula: dict,
    ) -> List[ReportReviewFinding]:
        """变动公式型（国企版）：期初 + Σ变动 = 期末"""
        findings: List[ReportReviewFinding] = []
        columns = wide_table_formula["columns"]
        data_row_start = wide_table_formula.get("data_row_start", 0)

        opening_cols = [c for c in columns if c.get("role") == "opening"]
        closing_cols = [c for c in columns if c.get("role") == "closing"]
        movement_cols = [c for c in columns if c.get("role") == "movement"]

        if not opening_cols or not closing_cols:
            return findings

        opening_col_idx = opening_cols[0]["col_index"]
        closing_col_idx = closing_cols[0]["col_index"]

        # 构建公式描述
        formula_parts = [opening_cols[0].get("name", "期初")]
        for mc in movement_cols:
            sign = mc.get("sign", "+")
            name = mc.get("name", f"列{mc['col_index']}")
            formula_parts.append(f"{sign} {name}")
        formula_parts.append(f"= {closing_cols[0].get('name', '期末')}")
        formula_desc = " ".join(formula_parts)

        total_keywords = ["合计", "总计", "小计", "合 计", "合\u3000计"]

        for row_idx in range(data_row_start, len(note_table.rows)):
            row = note_table.rows[row_idx]
            if not row:
                continue

            label = self._get_wide_table_row_label(row, columns)
            if not label:
                continue

            if label.startswith("其中") or label.startswith("其中：") or label.startswith("其中:"):
                continue

            opening = self._get_row_col_value(note_table, row_idx, opening_col_idx)
            closing = self._get_row_col_value(note_table, row_idx, closing_col_idx)

            if opening is None and closing is None:
                continue
            opening = opening or 0.0
            closing = closing or 0.0

            all_zero = abs(opening) < 0.01 and abs(closing) < 0.01
            if all_zero:
                has_movement = False
                for mc in movement_cols:
                    v = self._get_row_col_value(note_table, row_idx, mc["col_index"])
                    if v is not None and abs(v) >= 0.01:
                        has_movement = True
                        break
                if not has_movement:
                    continue

            expected = opening
            movement_details = []
            for mc in movement_cols:
                v = self._get_row_col_value(note_table, row_idx, mc["col_index"])
                if v is None:
                    v = 0.0
                sign = mc.get("sign", "+")
                name = mc.get("name", f"列{mc['col_index']}")
                if sign == "-":
                    expected -= v
                    movement_details.append(f"-{name}({v})")
                else:
                    expected += v
                    movement_details.append(f"+{name}({v})")

            if not _amounts_equal(expected, closing):
                diff = round(expected - closing, 2)
                is_total = any(kw in label for kw in total_keywords)
                risk = RiskLevel.HIGH if is_total else RiskLevel.MEDIUM

                detail_str = f"期初({opening})" + "".join(movement_details) + f"={expected}"
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=note_table.account_name,
                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_idx + 1}行'{label}'",
                    description=f"宽表横向公式不平：{detail_str}，期末{closing}，差异{diff}",
                    difference=diff,
                    statement_amount=expected,
                    note_amount=closing,
                    risk_level=risk,
                    reasoning=f"公式: {formula_desc}",
                    note_table_ids=[note_table.id],
                ))

        return findings

    def _check_wide_table_category_sum(
        self,
        note_table: NoteTable,
        wide_table_formula: dict,
    ) -> List[ReportReviewFinding]:
        """分类合计型（上市版）：各分类数据列之和 = 合计列"""
        findings: List[ReportReviewFinding] = []
        columns = wide_table_formula["columns"]
        data_row_start = wide_table_formula.get("data_row_start", 0)

        data_cols = [c for c in columns if c.get("role") == "data"]
        total_cols = [c for c in columns if c.get("role") == "total"]

        if not data_cols or not total_cols:
            return findings

        total_col_idx = total_cols[0]["col_index"]

        # 构建公式描述
        data_names = [c.get("name", f"列{c['col_index']}") for c in data_cols]
        total_name = total_cols[0].get("name", "合计")
        formula_desc = " + ".join(data_names) + f" = {total_name}"

        # 合计行 / 小计行关键词
        total_row_keywords = ["合计", "总计", "小计", "合 计", "合\u3000计"]

        for row_idx in range(data_row_start, len(note_table.rows)):
            row = note_table.rows[row_idx]
            if not row:
                continue

            label = self._get_wide_table_row_label(row, columns)
            if not label:
                continue

            # 跳过"其中"行
            if label.startswith("其中") or label.startswith("其中：") or label.startswith("其中:"):
                continue

            # 获取合计列值
            total_val = self._get_row_col_value(note_table, row_idx, total_col_idx)
            if total_val is None:
                continue

            # 计算各分类列之和
            computed_sum = 0.0
            all_none = True
            detail_parts = []
            for dc in data_cols:
                col_name = dc.get("name", f"列{dc['col_index']}")
                v = self._get_row_col_value(note_table, row_idx, dc["col_index"])
                if v is not None:
                    all_none = False
                    computed_sum += v
                    detail_parts.append(f"{col_name}({v})")
                else:
                    detail_parts.append(f"{col_name}(0)")

            # 如果所有分类列都是 None 且合计也是 0，跳过空行
            if all_none and abs(total_val) < 0.01:
                continue

            computed_sum = round(computed_sum, 2)

            if not _amounts_equal(computed_sum, total_val):
                diff = round(computed_sum - total_val, 2)
                is_total_row = any(kw in label for kw in total_row_keywords)
                risk = RiskLevel.HIGH if is_total_row else RiskLevel.MEDIUM

                detail_str = " + ".join(detail_parts) + f" = {computed_sum}"
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=note_table.account_name,
                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_idx + 1}行'{label}'",
                    description=f"宽表横向合计不平：{detail_str}，合计列{total_val}，差异{diff}",
                    difference=diff,
                    statement_amount=computed_sum,
                    note_amount=total_val,
                    risk_level=risk,
                    reasoning=f"公式: {formula_desc}",
                    note_table_ids=[note_table.id],
                ))

        return findings

    @staticmethod
    def _get_wide_table_row_label(row: list, columns: list) -> str:
        """从宽表行中提取行标签。"""
        label_cols = [c for c in columns if c.get("role") == "label"]
        if label_cols:
            label_col_idx = label_cols[0]["col_index"]
            if label_col_idx < len(row):
                return str(row[label_col_idx] or "").strip()
        if len(row) > 0:
            return str(row[0] or "").strip()
        return ""

    # ─── 其中项校验 ───

    def check_sub_items(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """验证各 sub_item 之和 ≤ 父项金额。"""
        findings: List[ReportReviewFinding] = []
        if self._should_skip_integrity(note_table):
            return findings

        # 按 parent 分组
        parent_children: Dict[int, List[int]] = {}
        for row in table_structure.rows:
            if row.role == "sub_item" and row.parent_row_index is not None:
                # 跳过纯"其中："标记行（只有"其中"关键词，没有实际明细名称）
                stripped = row.label.strip()
                is_bare_header = stripped in ("其中：", "其中:", "其中")
                if is_bare_header:
                    continue
                parent_children.setdefault(row.parent_row_index, []).append(row.row_index)

        for parent_idx, child_indices in parent_children.items():
            for col in table_structure.columns:
                if col.semantic in ("label", "other"):
                    continue

                parent_val = self._get_row_col_value(note_table, parent_idx, col.col_index)
                if parent_val is None:
                    continue

                child_sum = 0.0
                has_child = False
                for ci in child_indices:
                    v = self._get_row_col_value(note_table, ci, col.col_index)
                    if v is not None:
                        child_sum += v
                        has_child = True

                if has_child and child_sum > parent_val + TOLERANCE:
                    diff = round(child_sum - parent_val, 2)
                    parent_label = ""
                    for r in table_structure.rows:
                        if r.row_index == parent_idx:
                            parent_label = r.label
                            break
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=note_table.account_name,
                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{parent_idx + 1}行'{parent_label}'",
                        description=f"其中项之和{child_sum}超过父项{parent_val}，差异{diff}",
                        difference=diff,
                        statement_amount=parent_val,
                        note_amount=child_sum,
                        risk_level=RiskLevel.LOW,
                        reasoning=f"其中项校验: sum(子项)={child_sum} > 父项={parent_val}",
                        note_table_ids=[note_table.id],
                    ))

        return findings

    def check_ratio_columns(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """校验比例列，自动区分两种比例类型：

        1. 纵向占比：比例(%) = 本行金额 / 合计行金额 × 100（如分类占比）
        2. 横向计提率：比例(%) = 紧邻左侧金额 / 同行某金额 × 100（如坏账计提比例）

        判断依据：合计行的比例值 ≈ 100 → 纵向占比；否则 → 横向计提率。
        横向计提率的分母通过合计行数据自动探测。
        """
        findings: List[ReportReviewFinding] = []
        if self._should_skip_integrity(note_table):
            return findings

        RATIO_KEYWORDS = ["比例", "%", "占比", "百分比", "预期信用损失率", "计提比例"]

        # ── 检测比例列：按表头关键词识别，不依赖 LLM 的 semantic 标注 ──
        ratio_cols: List[int] = []
        for ci, header in enumerate(note_table.headers):
            header_str = str(header).strip() if header else ""
            if any(kw in header_str for kw in RATIO_KEYWORDS):
                ratio_cols.append(ci)

        if not ratio_cols:
            return findings

        # ── 收集所有非比例、非标签的金额列索引（按表头判断）──
        amount_col_indices: List[int] = []
        for ci, header in enumerate(note_table.headers):
            if ci in ratio_cols:
                continue
            header_str = str(header).strip() if header else ""
            # 第一列通常是标签列
            if ci == 0:
                continue
            # 跳过明显的非金额列
            if any(kw in header_str for kw in RATIO_KEYWORDS):
                continue
            amount_col_indices.append(ci)

        for ratio_col_idx in ratio_cols:
            # 找比例列左侧最近的金额列作为分子候选
            numerator_col = None
            for ci in reversed(amount_col_indices):
                if ci < ratio_col_idx:
                    numerator_col = ci
                    break
            if numerator_col is None:
                continue

            # ── 判断比例类型：检查合计行的比例值 ──
            total_ratio_val = None
            for ti in table_structure.total_row_indices:
                v = self._get_row_col_value(note_table, ti, ratio_col_idx)
                if v is not None:
                    total_ratio_val = v
                    break

            is_vertical = (total_ratio_val is not None and abs(total_ratio_val - 100.0) < 1.0)

            if is_vertical:
                # ── 纵向占比：比例 = 本行金额 / 合计行金额 × 100 ──
                total_amount = None
                for ti in table_structure.total_row_indices:
                    v = self._get_row_col_value(note_table, ti, numerator_col)
                    if v is not None and abs(v) > 0.01:
                        total_amount = v
                        break
                if total_amount is None:
                    continue

                for row_s in table_structure.rows:
                    if row_s.role not in ("data", "sub_item"):
                        continue
                    amount_val = self._get_row_col_value(note_table, row_s.row_index, numerator_col)
                    ratio_val = self._get_row_col_value(note_table, row_s.row_index, ratio_col_idx)
                    if amount_val is None or ratio_val is None:
                        continue
                    if abs(total_amount) < 0.01:
                        continue
                    expected_ratio = amount_val / total_amount * 100
                    diff = abs(ratio_val - expected_ratio)
                    if diff > 0.5:
                        findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                            account_name=note_table.account_name,
                            location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_s.row_index + 1}行'{row_s.label}'-列{ratio_col_idx + 1}",
                            description=f"比例列数值{ratio_val:.2f}%与计算值{expected_ratio:.2f}%不符，差异{diff:.2f}个百分点",
                            difference=round(diff, 2),
                            statement_amount=expected_ratio,
                            note_amount=ratio_val,
                            risk_level=RiskLevel.LOW,
                            reasoning=f"纵向占比校验: {amount_val}/{total_amount}*100={expected_ratio:.2f}%, 实际={ratio_val:.2f}%",
                            note_table_ids=[note_table.id],
                        ))
            else:
                # ── 横向计提率：比例 = 分子列 / 分母列 × 100 ──
                # 分子 = 紧邻左侧金额列（numerator_col）
                # 分母 = 通过合计行数据自动探测：遍历所有更左侧的金额列，
                #        找到使 numerator_total / denominator_candidate * 100 ≈ total_ratio_val 的列
                denominator_col = None

                if total_ratio_val is not None and abs(total_ratio_val) > 0.001:
                    # 获取合计行分子值
                    numerator_total = None
                    for ti in table_structure.total_row_indices:
                        v = self._get_row_col_value(note_table, ti, numerator_col)
                        if v is not None:
                            numerator_total = v
                            break

                    if numerator_total is not None:
                        best_diff = 999.0
                        for ci in amount_col_indices:
                            if ci >= numerator_col:
                                continue  # 分母必须在分子左侧
                            for ti in table_structure.total_row_indices:
                                denom_val = self._get_row_col_value(note_table, ti, ci)
                                if denom_val is not None and abs(denom_val) > 0.01:
                                    candidate_ratio = numerator_total / denom_val * 100
                                    d = abs(candidate_ratio - total_ratio_val)
                                    if d < best_diff:
                                        best_diff = d
                                        denominator_col = ci
                                    break  # 只用第一个合计行

                        # 如果最佳匹配差异太大，放弃
                        if best_diff > 1.0:
                            denominator_col = None

                if denominator_col is None:
                    continue

                for row_s in table_structure.rows:
                    if row_s.role not in ("data", "sub_item", "total"):
                        continue
                    numerator_val = self._get_row_col_value(note_table, row_s.row_index, numerator_col)
                    denominator_val = self._get_row_col_value(note_table, row_s.row_index, denominator_col)
                    ratio_val = self._get_row_col_value(note_table, row_s.row_index, ratio_col_idx)
                    if numerator_val is None or denominator_val is None or ratio_val is None:
                        continue
                    if abs(denominator_val) < 0.01:
                        continue
                    expected_ratio = numerator_val / denominator_val * 100
                    diff = abs(ratio_val - expected_ratio)
                    if diff > 0.5:
                        findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                            account_name=note_table.account_name,
                            location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_s.row_index + 1}行'{row_s.label}'-列{ratio_col_idx + 1}",
                            description=f"比例列数值{ratio_val:.2f}%与计算值{expected_ratio:.2f}%不符，差异{diff:.2f}个百分点",
                            difference=round(diff, 2),
                            statement_amount=expected_ratio,
                            note_amount=ratio_val,
                            risk_level=RiskLevel.LOW,
                            reasoning=f"横向计提率校验: {numerator_val}/{denominator_val}*100={expected_ratio:.2f}%, 实际={ratio_val:.2f}%",
                            note_table_ids=[note_table.id],
                        ))

        return findings

    # ─── 同科目跨表交叉核对 ───

    # 坏账准备类科目关键词（这些科目通常有 总表 + 分类表 + 坏账变动表 的多表结构）
    BAD_DEBT_ACCOUNT_KEYWORDS = [
        "应收票据", "应收账款", "其他应收款", "合同资产",
        "应收款项融资", "长期应收款",
    ]

    # 坏账准备变动表标题关键词
    BAD_DEBT_MOVEMENT_KEYWORDS = ["坏账准备", "减值准备"]
    BAD_DEBT_MOVEMENT_TITLE_KEYWORDS = ["计提", "收回", "转回", "核销", "变动"]

    # 按坏账计提方法分类表标题关键词
    BAD_DEBT_CLASSIFY_KEYWORDS = ["坏账计提方法", "计提方法分类", "按单项", "按组合"]

    # 应付职工薪酬子表关键词
    PAYROLL_SUB_KEYWORDS = {
        "短期薪酬": ["短期薪酬"],
        "设定提存计划": ["设定提存", "离职后福利"],
    }

    # 固定资产/在建工程/无形资产 汇总表 vs 明细表
    # 国企报表中，投资性房地产（成本模式）、使用权资产、油气资产、生产性生物资产
    # 也采用相同的多段式表格结构（原价/累计折旧/净值/减值准备/账面价值）
    ASSET_SUMMARY_ACCOUNTS = [
        "固定资产", "在建工程", "无形资产",
        "投资性房地产", "使用权资产", "油气资产", "生产性生物资产",
    ]

    # 存货：分类表 vs 跌价准备变动表
    INVENTORY_KEYWORDS = ["存货"]

    # 商誉：原值表 vs 减值准备表
    GOODWILL_KEYWORDS = ["商誉"]

    # 债权投资类科目：总表 vs 减值准备变动表
    DEBT_INVESTMENT_KEYWORDS = ["债权投资", "其他债权投资"]

    # 合同资产：总表 vs 减值准备变动表
    CONTRACT_ASSET_KEYWORDS = ["合同资产"]

    # 营业收入/营业成本：汇总表 vs 按行业/地区/商品转让时间划分的明细表
    REVENUE_COST_KEYWORDS = ["营业收入", "营业成本"]

    # 营业收入/营业成本明细子表标题关键词
    # 国企模板：按行业（或产品类型）划分、按地区划分、按商品转让时间划分
    # 上市模板：按行业（或产品类型）划分、按地区划分、按商品转让时间划分
    _REVENUE_COST_DETAIL_KW = [
        "按行业", "按产品", "按地区", "按商品转让时间",
        "前五名", "前5名",
    ]

    def check_cross_table_consistency(
        self,
        notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """同科目下多个表格之间的交叉核对。

        校验规则：
        1. 坏账准备类科目：总表坏账准备 vs 坏账准备变动表期末余额；
           总表金额 vs 分类表(单项+组合)合计
        2. 应付职工薪酬：汇总表"短期薪酬"行 vs 短期薪酬明细表合计行
        3. 固定资产/在建工程/无形资产/投资性房地产/使用权资产/油气资产/生产性生物资产：
           汇总表 vs 明细表账面价值/净值合计
        4. 在建工程：明细表减值准备合计 vs 减值准备变动表期末余额
        5. 存货：分类表跌价准备 vs 跌价准备变动表期末余额
        6. 商誉：原值表期末 - 减值准备表期末 = 账面价值
        7. 债权投资/其他债权投资：总表减值准备 vs 减值准备变动表期末余额
        8. 合同资产：总表减值准备 vs 减值准备变动表期末余额
        9. 营业收入/营业成本：汇总表合计 vs 按行业/地区/商品转让时间划分明细表合计
        """
        findings: List[ReportReviewFinding] = []

        # 按 account_name 分组
        account_notes: Dict[str, List[NoteTable]] = {}
        for n in notes:
            account_notes.setdefault(n.account_name, []).append(n)

        for acct_name, acct_notes in account_notes.items():
            # ── 1. 坏账准备类科目跨表核对 ──
            if any(kw in acct_name for kw in self.BAD_DEBT_ACCOUNT_KEYWORDS):
                findings.extend(self._check_bad_debt_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 2. 应付职工薪酬跨表核对 ──
            if "应付职工薪酬" in acct_name:
                findings.extend(self._check_payroll_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 3. 固定资产/在建工程/无形资产 汇总表 vs 明细表 ──
            if any(kw == acct_name or acct_name.startswith(kw) for kw in self.ASSET_SUMMARY_ACCOUNTS):
                findings.extend(self._check_asset_summary_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 4. 存货：分类表跌价准备 vs 跌价准备变动表 ──
            if any(kw in acct_name for kw in self.INVENTORY_KEYWORDS):
                findings.extend(self._check_inventory_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 5. 商誉：原值表 vs 减值准备表 ──
            if any(kw in acct_name for kw in self.GOODWILL_KEYWORDS):
                findings.extend(self._check_goodwill_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 6. 债权投资/其他债权投资：总表减值准备 vs 减值准备变动表 ──
            if any(kw == acct_name for kw in self.DEBT_INVESTMENT_KEYWORDS):
                findings.extend(self._check_debt_investment_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 7. 合同资产：总表减值准备 vs 减值准备变动表 ──
            if any(kw in acct_name for kw in self.CONTRACT_ASSET_KEYWORDS):
                findings.extend(self._check_contract_asset_cross(
                    acct_name, acct_notes, table_structures,
                ))

            # ── 8. 营业收入/营业成本：汇总表 vs 明细表 ──
            if any(kw in acct_name for kw in self.REVENUE_COST_KEYWORDS):
                findings.extend(self._check_revenue_cost_cross(
                    acct_name, acct_notes, table_structures,
                ))

        return findings

    def _check_bad_debt_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """坏账准备类科目：总表 vs 坏账准备变动表 vs 分类表。"""
        findings: List[ReportReviewFinding] = []

        # 识别各类表格
        summary_table = None       # 总表（账面余额 | 坏账准备 | 账面价值）
        movement_table = None      # 坏账准备变动表（期初/计提/转回/核销/期末）
        classify_table = None      # 按坏账计提方法分类表

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 按坏账计提方法分类表：标题含"坏账计提方法"或"按单项"等（优先匹配，避免被变动表误吞）
            if any(kw in title for kw in self.BAD_DEBT_CLASSIFY_KEYWORDS):
                classify_table = note
                continue

            # 坏账准备变动表：标题含"坏账准备"且含"计提/收回/转回/核销/变动"
            if (any(kw in title for kw in self.BAD_DEBT_MOVEMENT_KEYWORDS)
                    and any(kw in title for kw in self.BAD_DEBT_MOVEMENT_TITLE_KEYWORDS)):
                movement_table = note
                continue

            # 总表：表头含"账面余额"和"坏账准备"（或"减值准备"）和"账面价值"
            if ("账面余额" in headers_str
                    and ("坏账准备" in headers_str or "减值准备" in headers_str)
                    and "账面价值" in headers_str):
                # 优先选第一个匹配的作为总表（通常是科目下的第一个表）
                if summary_table is None:
                    summary_table = note
                    continue

        if not summary_table:
            return findings

        ts_summary = table_structures.get(summary_table.id)
        if not ts_summary:
            return findings

        # 从总表合计行提取坏账准备金额
        summary_bad_debt = self._extract_bad_debt_from_summary(
            summary_table, ts_summary, "期末",
        )
        summary_bad_debt_opening = self._extract_bad_debt_from_summary(
            summary_table, ts_summary, "期初",
        )
        summary_balance = self._extract_balance_from_summary(
            summary_table, ts_summary, "期末",
        )

        # ── 规则 1：总表坏账准备 vs 坏账准备变动表期末余额 ──
        if movement_table and summary_bad_debt is not None:
            movement_end = self._extract_movement_end_balance(movement_table, table_structures)
            if movement_end is not None and not _amounts_equal(summary_bad_debt, movement_end):
                diff = round(summary_bad_debt - movement_end, 2)
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=acct_name,
                    location=f"附注-{acct_name}-跨表核对-总表vs坏账变动表",
                    description=(
                        f"总表坏账准备期末{summary_bad_debt}与坏账准备变动表期末余额"
                        f"{movement_end}不一致，差异{diff}"
                    ),
                    difference=diff,
                    statement_amount=summary_bad_debt,
                    note_amount=movement_end,
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=(
                        f"跨表核对: 总表坏账准备({summary_bad_debt}) vs "
                        f"坏账变动表期末({movement_end}), 差异={diff}"
                    ),
                    note_table_ids=[summary_table.id, movement_table.id],
                ))

        # ── 规则 2：总表账面余额/坏账准备 vs 分类表合计 ──
        if classify_table and summary_bad_debt is not None:
            ts_classify = table_structures.get(classify_table.id)
            if ts_classify:
                classify_bad_debt = self._extract_bad_debt_from_summary(
                    classify_table, ts_classify, "期末",
                )
                if (classify_bad_debt is not None
                        and not _amounts_equal(summary_bad_debt, classify_bad_debt)):
                    diff = round(summary_bad_debt - classify_bad_debt, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=acct_name,
                        location=f"附注-{acct_name}-跨表核对-总表vs分类表",
                        description=(
                            f"总表坏账准备{summary_bad_debt}与分类表坏账准备合计"
                            f"{classify_bad_debt}不一致，差异{diff}"
                        ),
                        difference=diff,
                        statement_amount=summary_bad_debt,
                        note_amount=classify_bad_debt,
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=(
                            f"跨表核对: 总表坏账准备({summary_bad_debt}) vs "
                            f"分类表合计({classify_bad_debt}), 差异={diff}"
                        ),
                        note_table_ids=[summary_table.id, classify_table.id],
                    ))

                # 账面余额也核对
                classify_balance = self._extract_balance_from_summary(
                    classify_table, ts_classify, "期末",
                )
                if (summary_balance is not None and classify_balance is not None
                        and not _amounts_equal(summary_balance, classify_balance)):
                    diff = round(summary_balance - classify_balance, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=acct_name,
                        location=f"附注-{acct_name}-跨表核对-总表vs分类表-账面余额",
                        description=(
                            f"总表账面余额{summary_balance}与分类表账面余额合计"
                            f"{classify_balance}不一致，差异{diff}"
                        ),
                        difference=diff,
                        statement_amount=summary_balance,
                        note_amount=classify_balance,
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=(
                            f"跨表核对: 总表账面余额({summary_balance}) vs "
                            f"分类表合计({classify_balance}), 差异={diff}"
                        ),
                        note_table_ids=[summary_table.id, classify_table.id],
                    ))

        return findings

    def _check_payroll_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """应付职工薪酬：汇总表 vs 短期薪酬/设定提存计划明细表。"""
        findings: List[ReportReviewFinding] = []

        # 识别汇总表和子表
        summary_table = None
        sub_tables: Dict[str, NoteTable] = {}  # "短期薪酬" → NoteTable

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 汇总表：表头含"期初余额"和"本期增加"和"本期减少"和"期末余额"，
            # 且行中含"短期薪酬"
            has_movement_headers = (
                "期初" in headers_str and "期末" in headers_str
                and ("增加" in headers_str or "减少" in headers_str)
            )
            if not has_movement_headers:
                continue

            # 检查行内容判断是汇总表还是子表
            row_labels = [str(r[0]).strip() for r in note.rows if r and r[0]]
            has_short_term = any("短期薪酬" in lbl for lbl in row_labels)
            has_salary_detail = any(
                kw in lbl for lbl in row_labels
                for kw in ["工资", "奖金", "福利费", "社会保险", "住房公积金"]
            )
            has_pension_detail = any(
                kw in lbl for lbl in row_labels
                for kw in ["基本养老", "失业保险", "企业年金"]
            )

            if has_short_term and not has_salary_detail:
                summary_table = note
            elif has_salary_detail:
                sub_tables["短期薪酬"] = note
            elif has_pension_detail:
                sub_tables["设定提存计划"] = note

        if not summary_table or not sub_tables:
            return findings

        ts_summary = table_structures.get(summary_table.id)
        if not ts_summary:
            return findings

        # 从汇总表中找到"短期薪酬"行
        for sub_name, sub_note in sub_tables.items():
            ts_sub = table_structures.get(sub_note.id)
            if not ts_sub:
                continue

            # 在汇总表中找到对应行
            target_row_idx = None
            for row_s in ts_summary.rows:
                if any(kw in row_s.label for kws in self.PAYROLL_SUB_KEYWORDS.get(sub_name, []) for kw in [kws]):
                    target_row_idx = row_s.row_index
                    break

            if target_row_idx is None:
                continue

            # 子表的合计行
            sub_total_idx = None
            for ti in ts_sub.total_row_indices:
                sub_total_idx = ti
                break
            if sub_total_idx is None:
                continue

            # 逐列比对（期初/本期增加/本期减少/期末 — 跳过标签列）
            for col_s in ts_summary.columns:
                if col_s.semantic in ("label", "other"):
                    continue

                summary_val = self._get_row_col_value(
                    summary_table, target_row_idx, col_s.col_index,
                )
                if summary_val is None:
                    continue

                # 在子表中找同语义列
                sub_col_idx = None
                for col_sub in ts_sub.columns:
                    if col_sub.semantic == col_s.semantic:
                        sub_col_idx = col_sub.col_index
                        break
                if sub_col_idx is None:
                    continue

                sub_val = self._get_row_col_value(sub_note, sub_total_idx, sub_col_idx)
                if sub_val is None:
                    continue

                if not _amounts_equal(summary_val, sub_val):
                    diff = round(summary_val - sub_val, 2)
                    col_label = str(summary_table.headers[col_s.col_index]) if col_s.col_index < len(summary_table.headers) else f"列{col_s.col_index + 1}"
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=acct_name,
                        location=f"附注-{acct_name}-跨表核对-汇总表'{sub_name}'vs{sub_name}明细表-{col_label}",
                        description=(
                            f"汇总表'{sub_name}'行{col_label}={summary_val}，"
                            f"{sub_name}明细表合计行={sub_val}，差异{diff}"
                        ),
                        difference=diff,
                        statement_amount=summary_val,
                        note_amount=sub_val,
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=(
                            f"跨表核对: 汇总表'{sub_name}'({summary_val}) vs "
                            f"明细表合计({sub_val}), 差异={diff}"
                        ),
                        note_table_ids=[summary_table.id, sub_note.id],
                    ))

        return findings

    def _check_asset_summary_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """固定资产/在建工程/无形资产：汇总表 vs 明细变动表。"""
        findings: List[ReportReviewFinding] = []

        summary_table = None
        detail_table = None
        impairment_movement_table = None  # 减值准备变动表（在建工程用）

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 减值准备变动表：标题含"减值准备"
            # 期初/期末可能在表头或行标签中，_extract_movement_end_balance 都能处理
            if "减值准备" in title:
                impairment_movement_table = note
                continue

            # 汇总表：行数少（通常 2-5 行），表头含"期末余额"和"上年年末余额"
            # 且行中含子项名称（如"固定资产"+"固定资产清理"，或"在建工程"+"工程物资"）
            row_count = len(note.rows)
            if (row_count <= 6
                    and ("期末" in headers_str or "上年" in headers_str)
                    and "账面原值" not in headers_str
                    and "累计折旧" not in headers_str
                    and "本期增加" not in headers_str):
                if summary_table is None:
                    summary_table = note
                continue

            # 明细变动表：表头含"账面原值"或"累计折旧"或"账面余额"+"减值准备"+"账面净值"
            if ("账面原值" in headers_str or "累计折旧" in headers_str):
                detail_table = note
                continue
            if ("账面余额" in headers_str and "减值准备" in headers_str
                    and ("账面净值" in headers_str or "账面价值" in headers_str)):
                if detail_table is None:
                    detail_table = note
                continue

        # ── 汇总表 vs 明细表 ──
        if summary_table and detail_table:
            ts_summary = table_structures.get(summary_table.id)
            ts_detail = table_structures.get(detail_table.id)
            if ts_summary and ts_detail:
                # 从明细表取期末账面价值/净值合计
                detail_closing = self._get_cell_value(detail_table, ts_detail.closing_balance_cell)
                detail_opening = self._get_cell_value(detail_table, ts_detail.opening_balance_cell)

                # 从汇总表找到对应行（第一个非合计数据行，通常就是科目本身）
                summary_closing = self._get_cell_value(summary_table, ts_summary.closing_balance_cell)
                summary_opening = self._get_cell_value(summary_table, ts_summary.opening_balance_cell)

                # 但汇总表的合计行包含了"固定资产清理"等，我们需要找到科目本身的行
                # 尝试在汇总表中找到与 acct_name 匹配的行
                target_row = None
                for row_s in ts_summary.rows:
                    if row_s.role == "data" and acct_name in row_s.label:
                        target_row = row_s.row_index
                        break

                if target_row is not None:
                    # 从汇总表的科目行取值
                    for col_s in ts_summary.columns:
                        if col_s.semantic == "closing_balance":
                            v = self._get_row_col_value(summary_table, target_row, col_s.col_index)
                            if v is not None:
                                summary_closing = v
                            break
                    for col_s in ts_summary.columns:
                        if col_s.semantic == "opening_balance":
                            v = self._get_row_col_value(summary_table, target_row, col_s.col_index)
                            if v is not None:
                                summary_opening = v
                            break

                if (summary_closing is not None and detail_closing is not None
                        and not _amounts_equal(summary_closing, detail_closing)):
                    diff = round(summary_closing - detail_closing, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=acct_name,
                        location=f"附注-{acct_name}-跨表核对-汇总表vs明细表-期末",
                        description=(
                            f"汇总表'{acct_name}'期末{summary_closing}与"
                            f"明细表期末账面价值合计{detail_closing}不一致，差异{diff}"
                        ),
                        difference=diff,
                        statement_amount=summary_closing,
                        note_amount=detail_closing,
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=(
                            f"跨表核对: 汇总表({summary_closing}) vs "
                            f"明细表({detail_closing}), 差异={diff}"
                        ),
                        note_table_ids=[summary_table.id, detail_table.id],
                    ))

                if (summary_opening is not None and detail_opening is not None
                        and not _amounts_equal(summary_opening, detail_opening)):
                    diff = round(summary_opening - detail_opening, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=acct_name,
                        location=f"附注-{acct_name}-跨表核对-汇总表vs明细表-期初",
                        description=(
                            f"汇总表'{acct_name}'期初{summary_opening}与"
                            f"明细表期初账面价值合计{detail_opening}不一致，差异{diff}"
                        ),
                        difference=diff,
                        statement_amount=summary_opening,
                        note_amount=detail_opening,
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=(
                            f"跨表核对: 汇总表({summary_opening}) vs "
                            f"明细表({detail_opening}), 差异={diff}"
                        ),
                        note_table_ids=[summary_table.id, detail_table.id],
                    ))

        # ── 在建工程：明细表减值准备 vs 减值准备变动表 ──
        if detail_table and impairment_movement_table and "在建工程" in acct_name:
            ts_detail = table_structures.get(detail_table.id)
            if ts_detail:
                # 从明细表合计行找"减值准备"列
                impairment_col = None
                for col in ts_detail.columns:
                    header_str = str(detail_table.headers[col.col_index]).strip() if col.col_index < len(detail_table.headers) else ""
                    if "减值准备" in header_str:
                        impairment_col = col.col_index
                        break

                if impairment_col is not None and ts_detail.total_row_indices:
                    detail_impairment = self._get_row_col_value(
                        detail_table, ts_detail.total_row_indices[-1], impairment_col,
                    )
                    movement_end = self._extract_movement_end_balance(
                        impairment_movement_table, table_structures,
                    )
                    if (detail_impairment is not None and movement_end is not None
                            and not _amounts_equal(detail_impairment, movement_end)):
                        diff = round(detail_impairment - movement_end, 2)
                        findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                            account_name=acct_name,
                            location=f"附注-{acct_name}-跨表核对-明细表减值准备vs减值变动表",
                            description=(
                                f"明细表减值准备合计{detail_impairment}与"
                                f"减值准备变动表期末余额{movement_end}不一致，差异{diff}"
                            ),
                            difference=diff,
                            statement_amount=detail_impairment,
                            note_amount=movement_end,
                            risk_level=RiskLevel.MEDIUM,
                            reasoning=(
                                f"跨表核对: 明细表减值准备({detail_impairment}) vs "
                                f"变动表期末({movement_end}), 差异={diff}"
                            ),
                            note_table_ids=[detail_table.id, impairment_movement_table.id],
                        ))

        return findings

    def _check_inventory_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """存货：分类表跌价准备 vs 跌价准备变动表期末余额。"""
        findings: List[ReportReviewFinding] = []

        classification_table = None  # 分类表（账面余额 | 跌价准备 | 账面价值）
        provision_movement_table = None  # 跌价准备变动表

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 分类表优先判断（特征更具体）：表头含"账面余额"和"跌价准备"（或"减值准备"）和"账面价值"
            if ("账面余额" in headers_str
                    and ("跌价准备" in headers_str or "减值准备" in headers_str)
                    and "账面价值" in headers_str):
                if classification_table is None:
                    classification_table = note
                continue

            # 跌价准备变动表：标题含"跌价准备"或"减值准备"
            # 期初/期末可能在表头或行标签中，_extract_movement_end_balance 都能处理
            if ("跌价准备" in title or "减值准备" in title):
                if provision_movement_table is None:
                    provision_movement_table = note
                continue

        if not classification_table or not provision_movement_table:
            return findings

        ts_class = table_structures.get(classification_table.id)
        if not ts_class or not ts_class.total_row_indices:
            return findings

        # 从分类表合计行提取跌价准备金额
        total_row = ts_class.total_row_indices[-1]
        class_provision = None
        for ci, header in enumerate(classification_table.headers):
            header_str = str(header).strip() if header else ""
            if "跌价准备" in header_str or "减值准备" in header_str:
                val = self._get_row_col_value(classification_table, total_row, ci)
                if val is not None:
                    class_provision = val
                    break

        # 从变动表提取期末余额
        movement_end = self._extract_movement_end_balance(
            provision_movement_table, table_structures,
        )

        if (class_provision is not None and movement_end is not None
                and not _amounts_equal(class_provision, movement_end)):
            diff = round(class_provision - movement_end, 2)
            findings.append(self._make_finding(
                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                account_name=acct_name,
                location=f"附注-{acct_name}-跨表核对-分类表vs跌价准备变动表",
                description=(
                    f"分类表跌价准备合计{class_provision}与"
                    f"跌价准备变动表期末余额{movement_end}不一致，差异{diff}"
                ),
                difference=diff,
                statement_amount=class_provision,
                note_amount=movement_end,
                risk_level=RiskLevel.MEDIUM,
                reasoning=(
                    f"跨表核对: 分类表跌价准备({class_provision}) vs "
                    f"变动表期末({movement_end}), 差异={diff}"
                ),
                note_table_ids=[classification_table.id, provision_movement_table.id],
            ))

        return findings

    def _check_goodwill_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """商誉：原值表期末 - 减值准备表期末 = 账面价值。"""
        findings: List[ReportReviewFinding] = []

        cost_table = None       # 商誉账面原值表
        impairment_table = None  # 商誉减值准备表

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 减值准备表：标题含"减值准备"
            if "减值准备" in title:
                if "期初" in headers_str or "本期" in headers_str or "期末" in headers_str:
                    impairment_table = note
                    continue

            # 原值表：标题含"账面原值"或"商誉"（非减值准备），表头含"期初"/"期末"
            if "减值" not in title:
                if "期初" in headers_str or "本期" in headers_str or "期末" in headers_str:
                    if cost_table is None:
                        cost_table = note
                    continue

        if not cost_table or not impairment_table:
            return findings

        # 从原值表提取期末余额
        cost_end = self._extract_movement_end_balance(cost_table, table_structures)
        # 从减值准备表提取期末余额
        impairment_end = self._extract_movement_end_balance(impairment_table, table_structures)

        if cost_end is not None and impairment_end is not None:
            # 原值表和减值准备表各自的期初也可以核对，但最核心的是：
            # 两表的期末余额应该各自内部一致（已由 balance_formula 覆盖）
            # 跨表核对：原值表合计行期末 vs 减值准备表合计行期末 的差 = 账面价值
            # 但我们没有独立的"账面价值"来源，所以核对两表的合计行是否各自有值即可
            # 更有价值的核对：如果两表都有合计行，核对合计行的期初/期末是否与各自明细行一致
            # 这已经由 check_note_table_integrity 覆盖
            pass

        # 更实用的核对：两表的被投资单位名称应一致
        # 提取两表合计行的期末余额，确保减值准备 ≤ 原值
        if cost_end is not None and impairment_end is not None:
            if impairment_end > cost_end + TOLERANCE:
                diff = round(impairment_end - cost_end, 2)
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=acct_name,
                    location=f"附注-{acct_name}-跨表核对-原值表vs减值准备表",
                    description=(
                        f"商誉减值准备期末{impairment_end}超过"
                        f"商誉原值期末{cost_end}，差异{diff}"
                    ),
                    difference=diff,
                    statement_amount=cost_end,
                    note_amount=impairment_end,
                    risk_level=RiskLevel.HIGH,
                    reasoning=(
                        f"跨表核对: 减值准备({impairment_end}) > "
                        f"原值({cost_end}), 差异={diff}"
                    ),
                    note_table_ids=[cost_table.id, impairment_table.id],
                ))

        # 核对两表的逐行被投资单位是否金额匹配
        # 原值表每个被投资单位的期末余额 >= 减值准备表对应单位的期末余额
        ts_cost = table_structures.get(cost_table.id)
        ts_impairment = table_structures.get(impairment_table.id)
        if ts_cost and ts_impairment:
            # 找到两表中期末余额列
            cost_end_col = None
            for col in ts_cost.columns:
                if col.semantic == "closing_balance":
                    cost_end_col = col.col_index
                    break
            # 回退：取最后一列
            if cost_end_col is None and cost_table.headers:
                for ci in range(len(cost_table.headers) - 1, 0, -1):
                    h = str(cost_table.headers[ci]).strip()
                    if "期末" in h:
                        cost_end_col = ci
                        break

            impairment_end_col = None
            for col in ts_impairment.columns:
                if col.semantic == "closing_balance":
                    impairment_end_col = col.col_index
                    break
            if impairment_end_col is None and impairment_table.headers:
                for ci in range(len(impairment_table.headers) - 1, 0, -1):
                    h = str(impairment_table.headers[ci]).strip()
                    if "期末" in h:
                        impairment_end_col = ci
                        break

            if cost_end_col is not None and impairment_end_col is not None:
                # 构建减值准备表的 label → 期末值 映射
                impairment_map: Dict[str, float] = {}
                for row_s in ts_impairment.rows:
                    if row_s.role in ("data",):
                        val = self._get_row_col_value(
                            impairment_table, row_s.row_index, impairment_end_col,
                        )
                        if val is not None:
                            impairment_map[row_s.label.strip()] = val

                # 逐行核对原值表
                for row_s in ts_cost.rows:
                    if row_s.role not in ("data",):
                        continue
                    label = row_s.label.strip()
                    cost_val = self._get_row_col_value(
                        cost_table, row_s.row_index, cost_end_col,
                    )
                    if cost_val is None:
                        continue
                    imp_val = impairment_map.get(label)
                    if imp_val is not None and imp_val > cost_val + TOLERANCE:
                        diff = round(imp_val - cost_val, 2)
                        findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                            account_name=acct_name,
                            location=f"附注-{acct_name}-跨表核对-'{label}'-减值超原值",
                            description=(
                                f"'{label}'减值准备{imp_val}超过原值{cost_val}，差异{diff}"
                            ),
                            difference=diff,
                            statement_amount=cost_val,
                            note_amount=imp_val,
                            risk_level=RiskLevel.HIGH,
                            reasoning=(
                                f"跨表核对: '{label}'减值({imp_val}) > "
                                f"原值({cost_val}), 差异={diff}"
                            ),
                            note_table_ids=[cost_table.id, impairment_table.id],
                        ))

        return findings

    def _check_debt_investment_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """债权投资/其他债权投资：总表减值准备 vs 减值准备变动表期末余额。"""
        findings: List[ReportReviewFinding] = []

        summary_table = None       # 总表（账面余额 | 减值准备 | 账面价值）
        movement_table = None      # 减值准备变动表

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 总表优先判断（特征更具体）：表头含"账面余额"和"减值准备"和"账面价值"
            if ("账面余额" in headers_str
                    and "减值准备" in headers_str
                    and "账面价值" in headers_str):
                if summary_table is None:
                    summary_table = note
                continue

            # 减值准备变动表：标题含"减值准备"
            # 期初/期末可能在表头或行标签中，_extract_movement_end_balance 都能处理
            if "减值准备" in title:
                if movement_table is None:
                    movement_table = note
                continue

        if not summary_table or not movement_table:
            return findings

        ts_summary = table_structures.get(summary_table.id)
        if not ts_summary or not ts_summary.total_row_indices:
            return findings

        # 从总表合计行提取减值准备金额
        total_row = ts_summary.total_row_indices[-1]
        summary_provision = None
        for ci, header in enumerate(summary_table.headers):
            header_str = str(header).strip() if header else ""
            if "减值准备" in header_str:
                val = self._get_row_col_value(summary_table, total_row, ci)
                if val is not None:
                    summary_provision = val
                    break

        # 从变动表提取期末余额
        movement_end = self._extract_movement_end_balance(
            movement_table, table_structures,
        )

        if (summary_provision is not None and movement_end is not None
                and not _amounts_equal(summary_provision, movement_end)):
            diff = round(summary_provision - movement_end, 2)
            findings.append(self._make_finding(
                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                account_name=acct_name,
                location=f"附注-{acct_name}-跨表核对-总表vs减值准备变动表",
                description=(
                    f"总表减值准备合计{summary_provision}与"
                    f"减值准备变动表期末余额{movement_end}不一致，差异{diff}"
                ),
                difference=diff,
                statement_amount=summary_provision,
                note_amount=movement_end,
                risk_level=RiskLevel.MEDIUM,
                reasoning=(
                    f"跨表核对: 总表减值准备({summary_provision}) vs "
                    f"变动表期末({movement_end}), 差异={diff}"
                ),
                note_table_ids=[summary_table.id, movement_table.id],
            ))

        return findings

    def _check_contract_asset_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """合同资产：总表减值准备 vs 减值准备变动表期末余额。"""
        findings: List[ReportReviewFinding] = []

        summary_table = None       # 总表（账面余额 | 减值准备 | 账面价值）
        movement_table = None      # 减值准备变动表

        for note in acct_notes:
            title = note.section_title or ""
            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""

            # 总表优先判断：表头含"账面余额"和"减值准备"和"账面价值"
            if ("账面余额" in headers_str
                    and "减值准备" in headers_str
                    and "账面价值" in headers_str):
                if summary_table is None:
                    summary_table = note
                continue

            # 减值准备变动表：标题含"减值准备"
            if "减值准备" in title:
                if movement_table is None:
                    movement_table = note
                continue

        if not summary_table or not movement_table:
            return findings

        ts_summary = table_structures.get(summary_table.id)
        if not ts_summary or not ts_summary.total_row_indices:
            return findings

        # 从总表合计行提取减值准备金额
        total_row = ts_summary.total_row_indices[-1]
        summary_provision = None
        for ci, header in enumerate(summary_table.headers):
            header_str = str(header).strip() if header else ""
            if "减值准备" in header_str:
                val = self._get_row_col_value(summary_table, total_row, ci)
                if val is not None:
                    summary_provision = val
                    break

        # 从变动表提取期末余额
        movement_end = self._extract_movement_end_balance(
            movement_table, table_structures,
        )

        if (summary_provision is not None and movement_end is not None
                and not _amounts_equal(summary_provision, movement_end)):
            diff = round(summary_provision - movement_end, 2)
            findings.append(self._make_finding(
                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                account_name=acct_name,
                location=f"附注-{acct_name}-跨表核对-总表vs减值准备变动表",
                description=(
                    f"总表减值准备合计{summary_provision}与"
                    f"减值准备变动表期末余额{movement_end}不一致，差异{diff}"
                ),
                difference=diff,
                statement_amount=summary_provision,
                note_amount=movement_end,
                risk_level=RiskLevel.MEDIUM,
                reasoning=(
                    f"跨表核对: 总表减值准备({summary_provision}) vs "
                    f"变动表期末({movement_end}), 差异={diff}"
                ),
                note_table_ids=[summary_table.id, movement_table.id],
            ))

        return findings

    def _check_revenue_cost_cross(
        self,
        acct_name: str,
        acct_notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """营业收入/营业成本：汇总表合计 vs 按行业/地区/商品转让时间划分明细表合计。

        国企和上市报表中，营业收入、营业成本科目下通常有多张合并表格：
        - 汇总表（主营业务/其他业务/合计）
        - 按行业（或产品类型）划分
        - 按地区划分
        - 按商品转让时间划分

        核对：汇总表的收入/成本合计 应等于 各明细表的收入/成本合计。
        """
        findings: List[ReportReviewFinding] = []

        # 分离汇总表和明细表
        summary_tables: List[NoteTable] = []
        detail_tables: List[NoteTable] = []

        for note in acct_notes:
            if not self._is_revenue_cost_combined_table(note):
                continue
            if self._is_revenue_cost_detail_table(note):
                detail_tables.append(note)
            else:
                summary_tables.append(note)

        if not summary_tables or not detail_tables:
            return findings

        summary = summary_tables[0]

        # 从汇总表提取收入和成本的本期合计
        summary_rev_closing, _ = self._extract_revenue_cost_from_combined_table(
            summary, "营业收入",
        )
        summary_cost_closing, _ = self._extract_revenue_cost_from_combined_table(
            summary, "营业成本",
        )

        # 逐个明细表核对
        for detail in detail_tables:
            detail_title = detail.section_title or detail.account_name or ""

            detail_rev_closing, _ = self._extract_revenue_cost_from_combined_table(
                detail, "营业收入",
            )
            detail_cost_closing, _ = self._extract_revenue_cost_from_combined_table(
                detail, "营业成本",
            )

            # 核对收入
            if (summary_rev_closing is not None and detail_rev_closing is not None
                    and not _amounts_equal(summary_rev_closing, detail_rev_closing)):
                diff = round(summary_rev_closing - detail_rev_closing, 2)
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=acct_name,
                    location=f"附注-{acct_name}-跨表核对-汇总表vs{detail_title}-收入",
                    description=(
                        f"汇总表营业收入合计{summary_rev_closing}与"
                        f"'{detail_title}'收入合计{detail_rev_closing}不一致，差异{diff}"
                    ),
                    difference=diff,
                    statement_amount=summary_rev_closing,
                    note_amount=detail_rev_closing,
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=(
                        f"跨表核对: 汇总表收入({summary_rev_closing}) vs "
                        f"明细表收入({detail_rev_closing}), 差异={diff}"
                    ),
                    note_table_ids=[summary.id, detail.id],
                ))

            # 核对成本
            if (summary_cost_closing is not None and detail_cost_closing is not None
                    and not _amounts_equal(summary_cost_closing, detail_cost_closing)):
                diff = round(summary_cost_closing - detail_cost_closing, 2)
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=acct_name,
                    location=f"附注-{acct_name}-跨表核对-汇总表vs{detail_title}-成本",
                    description=(
                        f"汇总表营业成本合计{summary_cost_closing}与"
                        f"'{detail_title}'成本合计{detail_cost_closing}不一致，差异{diff}"
                    ),
                    difference=diff,
                    statement_amount=summary_cost_closing,
                    note_amount=detail_cost_closing,
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=(
                        f"跨表核对: 汇总表成本({summary_cost_closing}) vs "
                        f"明细表成本({detail_cost_closing}), 差异={diff}"
                    ),
                    note_table_ids=[summary.id, detail.id],
                ))

        return findings

    # ─── 权益法投资损益跨科目交叉核对 ───

    # 长期股权投资明细表中"权益法下确认的投资损益"列的关键词
    EQUITY_METHOD_INCOME_COL_KEYWORDS = [
        "权益法下确认的投资损益", "权益法下确认的投资收益",
        "权益法确认的投资损益", "投资损益",
    ]

    # 投资收益附注表中"权益法核算的长期股权投资收益"行的关键词
    EQUITY_METHOD_INCOME_ROW_KEYWORDS = [
        "权益法核算的长期股权投资收益",
        "权益法核算的长期股权投资",
    ]

    # 利润表中"对联营企业和合营企业的投资收益"行的关键词
    INCOME_STMT_EQUITY_KEYWORDS = [
        "对联营企业和合营企业的投资收益",
        "联营企业和合营企业的投资收益",
        "对联营、合营企业的投资收益",
    ]

    def check_equity_method_income_consistency(
        self,
        items: List[StatementItem],
        notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """权益法投资损益跨科目交叉核对。

        校验三方一致：
        A. 长期股权投资明细表 → "权益法下确认的投资损益"列的合计行
        B. 投资收益附注表 → "权益法核算的长期股权投资收益"行的本期发生额
        C. 利润表 → "其中：对联营企业和合营企业的投资收益"行的本期金额

        A = B = C
        """
        findings: List[ReportReviewFinding] = []

        # ── 1. 从长期股权投资明细表提取"权益法下确认的投资损益"合计 ──
        equity_detail_amount: Optional[float] = None
        equity_detail_note: Optional[NoteTable] = None

        # 期初/期末余额列排除关键词：含这些词的列是余额列，不是当期变动列
        _balance_col_exclude = ["期初", "期末", "年初", "年末", "余额", "投资成本"]

        for note in notes:
            if "长期股权投资" not in (note.account_name or ""):
                continue
            # 跳过母公司附注表格（母公司口径的投资损益不应与合并利润表比对）
            if self._is_parent_company_note(note):
                continue
            # 宽表：列数 ≥ 8 且含"投资损益"列
            if not note.headers or len(note.headers) < 8:
                continue
            headers_text = [str(h) for h in note.headers]
            income_col_idx = None
            for ci, h in enumerate(headers_text):
                # 跳过期初/期末余额列，避免误匹配
                if any(bk in h for bk in _balance_col_exclude):
                    continue
                for kw in self.EQUITY_METHOD_INCOME_COL_KEYWORDS:
                    if kw in h:
                        income_col_idx = ci
                        break
                if income_col_idx is not None:
                    break

            if income_col_idx is None:
                continue

            # 找合计行
            for ri, row in enumerate(note.rows):
                if not row:
                    continue
                label = str(row[0] or "").strip()
                if any(kw in label for kw in ["合计", "合 计", "合\u3000计", "总计"]):
                    val = self._get_row_col_value(note, ri, income_col_idx)
                    if val is not None:
                        equity_detail_amount = val
                        equity_detail_note = note
                        break
            if equity_detail_amount is not None:
                break

        # ── 2. 从投资收益附注表提取"权益法核算的长期股权投资收益" ──
        invest_income_amount: Optional[float] = None
        invest_income_note: Optional[NoteTable] = None

        for note in notes:
            combined = (note.account_name or "") + (note.section_title or "")
            if "投资收益" not in combined:
                continue
            # 动态定位"本期"列（通常是"本期发生额"/"本期金额"/"本年金额"等）
            current_col_idx = 1  # 默认第2列
            if note.headers:
                for ci, h in enumerate(note.headers):
                    h_str = str(h or "")
                    if any(kw in h_str for kw in ["本期", "本年"]) and "上期" not in h_str and "上年" not in h_str:
                        current_col_idx = ci
                        break
            for ri, row in enumerate(note.rows):
                if not row:
                    continue
                label = str(row[0] or "").strip()
                for kw in self.EQUITY_METHOD_INCOME_ROW_KEYWORDS:
                    if kw in label:
                        val = self._get_row_col_value(note, ri, current_col_idx)
                        if val is not None:
                            invest_income_amount = val
                            invest_income_note = note
                        break
                if invest_income_amount is not None:
                    break
            if invest_income_amount is not None:
                break

        # ── 3. 从利润表提取"对联营企业和合营企业的投资收益" ──
        stmt_equity_income: Optional[float] = None
        stmt_equity_item: Optional[StatementItem] = None

        for item in items:
            if item.statement_type != StatementType.INCOME_STATEMENT:
                continue
            for kw in self.INCOME_STMT_EQUITY_KEYWORDS:
                if kw in item.account_name:
                    stmt_equity_income = item.closing_balance
                    stmt_equity_item = item
                    break
            if stmt_equity_income is not None:
                break

        # ── 4. 交叉核对 ──
        # 收集所有可用的值
        values = {}
        note_ids = []
        if equity_detail_amount is not None:
            values["长期股权投资明细表-权益法投资损益合计"] = equity_detail_amount
            if equity_detail_note:
                note_ids.append(equity_detail_note.id)
        if invest_income_amount is not None:
            values["投资收益附注-权益法核算的长期股权投资收益"] = invest_income_amount
            if invest_income_note:
                note_ids.append(invest_income_note.id)
        if stmt_equity_income is not None:
            values["利润表-对联营企业和合营企业的投资收益"] = stmt_equity_income

        # 至少需要两个值才能比对
        if len(values) < 2:
            return findings

        # 两两比对
        keys = list(values.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a_name, a_val = keys[i], values[keys[i]]
                b_name, b_val = keys[j], values[keys[j]]
                if not _amounts_equal(a_val, b_val):
                    diff = round(a_val - b_val, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name="长期股权投资/投资收益",
                        location=f"跨科目核对-权益法投资损益",
                        description=(
                            f"权益法投资损益跨科目不一致：{a_name}={a_val:,.2f}，"
                            f"{b_name}={b_val:,.2f}，差异{diff:,.2f}"
                        ),
                        difference=diff,
                        statement_amount=a_val,
                        note_amount=b_val,
                        risk_level=self._assess_risk(abs(diff), max(abs(a_val), abs(b_val)) if max(abs(a_val), abs(b_val)) > 0 else None),
                        reasoning=(
                            f"三方核对: {' / '.join(f'{k}={v:,.2f}' for k, v in values.items())}"
                        ),
                        note_table_ids=note_ids,
                    ))

        return findings

    # ─── 跨表核对辅助方法 ───

    def _extract_bad_debt_from_summary(
        self, note: NoteTable, ts: TableStructure, period: str,
    ) -> Optional[float]:
        """从总表/分类表的合计行提取坏账准备金额。

        period: "期末" 或 "期初"
        """
        if not ts.total_row_indices:
            return None

        total_row = ts.total_row_indices[-1]

        # 找"坏账准备"或"减值准备"列
        for ci, header in enumerate(note.headers):
            header_str = str(header).strip() if header else ""
            if "坏账准备" in header_str or "减值准备" in header_str:
                # 区分期末/期初：如果表格有"期末余额"和"上年年末余额"两组列，
                # 坏账准备列可能出现两次。简单策略：期末取第一个，期初取第二个
                if period == "期末":
                    val = self._get_row_col_value(note, total_row, ci)
                    if val is not None:
                        return val
                # 期初暂不处理（续表结构复杂，后续可扩展）

        return None

    def _extract_balance_from_summary(
        self, note: NoteTable, ts: TableStructure, period: str,
    ) -> Optional[float]:
        """从总表/分类表的合计行提取账面余额。"""
        if not ts.total_row_indices:
            return None

        total_row = ts.total_row_indices[-1]

        for ci, header in enumerate(note.headers):
            header_str = str(header).strip() if header else ""
            if "账面余额" in header_str and "坏账" not in header_str:
                if period == "期末":
                    val = self._get_row_col_value(note, total_row, ci)
                    if val is not None:
                        return val

        return None

    def _extract_movement_end_balance(
        self, note: NoteTable, table_structures: Dict[str, TableStructure],
    ) -> Optional[float]:
        """从坏账准备/减值准备变动表中提取期末余额。

        变动表结构：期初余额 / 本期计提 / 本期收回或转回 / 本期核销 / 期末余额
        期末余额通常在最后一个数据行。
        """
        # 尝试通过行标签找"期末余额"行
        for ri, row in enumerate(note.rows):
            label = str(row[0]).strip() if row and row[0] else ""
            if "期末" in label and "余额" in label:
                # 取第二列（金额列）
                for ci in range(1, len(row)):
                    val = _safe_float(row[ci])
                    if val is not None:
                        return val

        # 回退：取最后一行的金额
        if note.rows:
            last_row = note.rows[-1]
            for ci in range(1, len(last_row)):
                val = _safe_float(last_row[ci])
                if val is not None:
                    return val

        return None

    # ─── 现金流量表补充资料 vs 利润表/现金流量表 跨报表校验 ───

    # 补充资料行标签 → (对应报表科目名称, 符号关系)
    # sign=1 表示同号（补充资料值 == 报表值），sign=-1 表示反号（补充资料值 == -报表值）
    CASHFLOW_SUPPLEMENT_MAPPINGS = [
        {"label_keywords": ["净利润"], "statement_name": "净利润",
         "statement_type": StatementType.INCOME_STATEMENT, "sign": 1,
         "exclude_keywords": ["调节"]},
        {"label_keywords": ["资产减值损失"], "statement_name": "资产减值损失",
         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,
         "exclude_keywords": []},
        {"label_keywords": ["信用减值损失"], "statement_name": "信用减值损失",
         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,
         "exclude_keywords": []},
        {"label_keywords": ["公允价值变动损失", "公允价值变动"],
         "statement_name": "公允价值变动收益",
         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,
         "exclude_keywords": []},
        {"label_keywords": ["投资损失"], "statement_name": "投资收益",
         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,
         "exclude_keywords": []},
        {"label_keywords": ["财务费用"], "statement_name": "财务费用",
         "statement_type": StatementType.INCOME_STATEMENT, "sign": 1,
         "exclude_keywords": [],
         "sub_item": "利息支出"},
    ]

    # 补充资料中"经营活动产生的现金流量净额" vs 现金流量表主表
    CASHFLOW_SUPPLEMENT_TOTAL_KEYWORDS = ["经营活动产生的现金流量净额"]

    # 识别现金流量表补充资料的附注表格
    CASHFLOW_SUPPLEMENT_NOTE_KEYWORDS = [
        "现金流量表补充资料",
        "将净利润调节为经营活动现金流量",
        "补充资料",
    ]

    def check_cashflow_supplement_consistency(
        self,
        items: List[StatementItem],
        notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """现金流量表补充资料中的利润表/现金流量表数值交叉核对。

        校验规则：
        1. 净利润 == 利润表.净利润
        2. 资产减值损失 == 利润表.资产减值损失
        3. 信用减值损失 == 利润表.信用减值损失
        4. 公允价值变动损失 == -利润表.公允价值变动收益
        5. 投资损失 == -利润表.投资收益
        6. 财务费用 == 利润表.财务费用（仅利息支出部分，需从附注明细取值）
        7. 经营活动产生的现金流量净额 == 现金流量表主表.经营活动产生的现金流量净额
        """
        findings: List[ReportReviewFinding] = []

        # 1. 找到补充资料附注表格
        supplement_notes: List[NoteTable] = []
        for n in notes:
            combined = (n.section_title or "") + (n.account_name or "")
            if any(kw in combined for kw in self.CASHFLOW_SUPPLEMENT_NOTE_KEYWORDS):
                supplement_notes.append(n)

        if not supplement_notes:
            return findings

        # 2. 构建报表科目索引（按 statement_type + account_name）
        income_items: Dict[str, StatementItem] = {}
        cashflow_items: Dict[str, StatementItem] = {}
        for item in items:
            if item.statement_type == StatementType.INCOME_STATEMENT:
                income_items[item.account_name] = item
            elif item.statement_type == StatementType.CASH_FLOW:
                cashflow_items[item.account_name] = item

        # 3. 构建财务费用明细索引（从附注中查找财务费用的利息支出子项）
        interest_expense: Optional[float] = None
        for n in notes:
            if "财务费用" in (n.account_name or "") or "财务费用" in (n.section_title or ""):
                # 在补充资料表格本身之外的财务费用明细表中查找利息支出
                if n in supplement_notes:
                    continue
                for row in n.rows:
                    if not row:
                        continue
                    label = str(row[0]).strip() if row else ""
                    if "利息支出" in label:
                        # 取本期发生额（通常第2列）
                        for ci in range(1, len(row)):
                            val = _safe_float(row[ci])
                            if val is not None:
                                interest_expense = val
                                break
                        break

        # 4. 遍历补充资料表格，逐行匹配校验
        for supp_note in supplement_notes:
            ts = table_structures.get(supp_note.id)

            for row_idx, row in enumerate(supp_note.rows):
                if not row:
                    continue
                row_label = str(row[0]).strip() if row else ""
                if not row_label:
                    continue

                # 取本期发生额（第2列，即索引1）
                supp_value: Optional[float] = None
                for ci in range(1, len(row)):
                    val = _safe_float(row[ci])
                    if val is not None:
                        supp_value = val
                        break

                if supp_value is None:
                    continue

                # ── 4a. 利润表项目校验 ──
                for mapping in self.CASHFLOW_SUPPLEMENT_MAPPINGS:
                    # 检查行标签是否匹配
                    label_match = any(kw in row_label for kw in mapping["label_keywords"])
                    if not label_match:
                        continue
                    # 排除关键词（如"将净利润调节为..."不是"净利润"行）
                    if mapping.get("exclude_keywords"):
                        if any(ekw in row_label for ekw in mapping["exclude_keywords"]):
                            continue

                    # 特殊处理：财务费用仅比对利息支出
                    if mapping.get("sub_item") == "利息支出":
                        if interest_expense is not None:
                            expected = interest_expense * mapping["sign"]
                            if not _amounts_equal(supp_value, expected):
                                diff = round(supp_value - expected, 2)
                                findings.append(self._make_finding(
                                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                                    account_name="现金流量表补充资料",
                                    location=f"附注-现金流量表补充资料-第{row_idx + 1}行'{row_label}'",
                                    description=(
                                        f"补充资料'{row_label}'金额 {supp_value:,.2f} "
                                        f"与附注财务费用明细中利息支出 {interest_expense:,.2f} 不一致，"
                                        f"差异 {diff:,.2f}"
                                    ),
                                    statement_amount=interest_expense,
                                    note_amount=supp_value,
                                    difference=diff,
                                    risk_level=self._assess_risk(abs(diff), interest_expense),
                                    reasoning=(
                                        f"校验公式: 补充资料.财务费用({supp_value:,.2f}) "
                                        f"应等于 附注.财务费用.利息支出({interest_expense:,.2f})"
                                    ),
                                    note_table_ids=[supp_note.id],
                                ))
                        # 财务费用已处理，跳过后续通用逻辑
                        break

                    # 通用逻辑：从利润表找对应科目
                    stmt_item = income_items.get(mapping["statement_name"])
                    if not stmt_item:
                        # 尝试模糊匹配
                        for name, item in income_items.items():
                            if mapping["statement_name"] in name or name in mapping["statement_name"]:
                                stmt_item = item
                                break

                    if stmt_item and stmt_item.closing_balance is not None:
                        expected = stmt_item.closing_balance * mapping["sign"]
                        if not _amounts_equal(supp_value, expected):
                            diff = round(supp_value - expected, 2)
                            stmt_display = f"{mapping['statement_name']}({stmt_item.closing_balance:,.2f})"
                            sign_desc = "" if mapping["sign"] == 1 else "（取反）"
                            findings.append(self._make_finding(
                                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                                account_name="现金流量表补充资料",
                                location=f"附注-现金流量表补充资料-第{row_idx + 1}行'{row_label}'",
                                description=(
                                    f"补充资料'{row_label}'金额 {supp_value:,.2f} "
                                    f"与利润表{stmt_display}{sign_desc}不一致，"
                                    f"差异 {diff:,.2f}"
                                ),
                                statement_amount=stmt_item.closing_balance,
                                note_amount=supp_value,
                                difference=diff,
                                risk_level=self._assess_risk(abs(diff), abs(stmt_item.closing_balance)),
                                reasoning=(
                                    f"校验公式: 补充资料.{row_label}({supp_value:,.2f}) "
                                    f"应等于 {'- ' if mapping['sign'] == -1 else ''}"
                                    f"利润表.{mapping['statement_name']}({stmt_item.closing_balance:,.2f})"
                                ),
                                note_table_ids=[supp_note.id],
                            ))
                    break  # 一行只匹配一个 mapping

                # ── 4b. 经营活动现金流量净额 vs 现金流量表主表 ──
                if any(kw in row_label for kw in self.CASHFLOW_SUPPLEMENT_TOTAL_KEYWORDS):
                    cf_item = cashflow_items.get("经营活动产生的现金流量净额")
                    if not cf_item:
                        for name, item in cashflow_items.items():
                            if "经营活动" in name and "净额" in name:
                                cf_item = item
                                break

                    if cf_item and cf_item.closing_balance is not None:
                        if not _amounts_equal(supp_value, cf_item.closing_balance):
                            diff = round(supp_value - cf_item.closing_balance, 2)
                            findings.append(self._make_finding(
                                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                                account_name="现金流量表补充资料",
                                location=f"附注-现金流量表补充资料-第{row_idx + 1}行'{row_label}'",
                                description=(
                                    f"补充资料'{row_label}'金额 {supp_value:,.2f} "
                                    f"与现金流量表主表({cf_item.closing_balance:,.2f})不一致，"
                                    f"差异 {diff:,.2f}"
                                ),
                                statement_amount=cf_item.closing_balance,
                                note_amount=supp_value,
                                difference=diff,
                                risk_level=self._assess_risk(abs(diff), abs(cf_item.closing_balance)),
                                reasoning=(
                                    f"校验公式: 补充资料.经营活动现金流量净额({supp_value:,.2f}) "
                                    f"应等于 现金流量表.经营活动产生的现金流量净额({cf_item.closing_balance:,.2f})"
                                ),
                                note_table_ids=[supp_note.id],
                            ))

        return findings

    # ─── 应交所得税本期增加 vs 当期所得税费用 ───

    # 应交税费表中识别"企业所得税"/"应交所得税"行的关键词
    TAX_PAYABLE_NOTE_KEYWORDS = ["应交税费"]
    INCOME_TAX_ROW_KEYWORDS = ["企业所得税", "应交所得税"]
    # 本期增加列的表头关键词
    CURRENT_INCREASE_HEADER_KEYWORDS = ["本期增加", "本期计提", "本年增加", "本年计提"]

    # 所得税费用表中识别"当期所得税费用"行的关键词
    INCOME_TAX_EXPENSE_NOTE_KEYWORDS = ["所得税费用"]
    CURRENT_TAX_EXPENSE_ROW_KEYWORDS = [
        "当期所得税费用",
        "当期所得税",
        "按税法及相关规定计算的当期所得税",
    ]

    def check_income_tax_consistency(
        self,
        notes: List[NoteTable],
    ) -> List[ReportReviewFinding]:
        """应交税费中应交所得税的本期增加额 vs 所得税费用中的当期所得税费用。

        校验规则：
        应交税费表.企业所得税.本期增加 == 所得税费用表.当期所得税费用.本期发生额
        """
        findings: List[ReportReviewFinding] = []

        # 1. 找到应交税费附注表格，提取企业所得税的本期增加额
        tax_payable_increase: Optional[float] = None
        tax_payable_note_id: Optional[str] = None

        for n in notes:
            combined = (n.account_name or "") + (n.section_title or "")
            if not any(kw in combined for kw in self.TAX_PAYABLE_NOTE_KEYWORDS):
                continue

            # 找"本期增加"列索引
            increase_col: Optional[int] = None
            for ci, h in enumerate(n.headers):
                if any(kw in h for kw in self.CURRENT_INCREASE_HEADER_KEYWORDS):
                    increase_col = ci
                    break

            if increase_col is None:
                continue

            # 找"企业所得税"行
            for row in n.rows:
                if not row:
                    continue
                label = str(row[0]).strip() if row else ""
                if any(kw in label for kw in self.INCOME_TAX_ROW_KEYWORDS):
                    if increase_col < len(row):
                        val = _safe_float(row[increase_col])
                        if val is not None:
                            tax_payable_increase = val
                            tax_payable_note_id = n.id
                    break

        if tax_payable_increase is None:
            return findings

        # 2. 找到所得税费用附注表格，提取当期所得税费用
        current_tax_expense: Optional[float] = None
        tax_expense_note_id: Optional[str] = None

        for n in notes:
            combined = (n.account_name or "") + (n.section_title or "")
            if not any(kw in combined for kw in self.INCOME_TAX_EXPENSE_NOTE_KEYWORDS):
                continue

            for row in n.rows:
                if not row:
                    continue
                label = str(row[0]).strip() if row else ""
                if any(kw in label for kw in self.CURRENT_TAX_EXPENSE_ROW_KEYWORDS):
                    # 取第一个数值列（通常是本期发生额）
                    for ci in range(1, len(row)):
                        val = _safe_float(row[ci])
                        if val is not None:
                            current_tax_expense = val
                            tax_expense_note_id = n.id
                            break
                    break

        if current_tax_expense is None:
            return findings

        # 3. 比对
        if not _amounts_equal(tax_payable_increase, current_tax_expense):
            diff = round(tax_payable_increase - current_tax_expense, 2)
            note_ids = [nid for nid in [tax_payable_note_id, tax_expense_note_id] if nid]
            findings.append(self._make_finding(
                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                account_name="应交税费/所得税费用",
                location="附注-应交税费(企业所得税本期增加) vs 所得税费用(当期所得税费用)",
                description=(
                    f"应交税费中企业所得税本期增加额 {tax_payable_increase:,.2f} "
                    f"与所得税费用中当期所得税费用 {current_tax_expense:,.2f} 不一致，"
                    f"差异 {diff:,.2f}"
                ),
                statement_amount=current_tax_expense,
                note_amount=tax_payable_increase,
                difference=diff,
                risk_level=self._assess_risk(abs(diff), abs(current_tax_expense)),
                reasoning=(
                    f"校验公式: 应交税费.企业所得税.本期增加({tax_payable_increase:,.2f}) "
                    f"应等于 所得税费用.当期所得税费用({current_tax_expense:,.2f})"
                ),
                note_table_ids=note_ids,
            ))

        return findings

    # ─── 受限资产交叉披露验证（LLM 辅助）───

    RESTRICTED_ASSET_NOTE_KEYWORDS = [
        "所有权或使用权受到限制",
        "所有权和使用权受到限制",
        "受限资产",
    ]

    async def check_restricted_asset_disclosure(
        self,
        notes: List[NoteTable],
        note_sections: list,
        openai_service,
    ) -> List[ReportReviewFinding]:
        """受限资产表中的每个资产明细，验证对应科目附注中是否有受限相关披露。

        对于受限资产表中有金额的每个资产项目（如"货币资金"、"固定资产"等），
        收集该科目在附注中的所有文字内容，调用 LLM 判断是否有受限/抵押/质押等披露。
        """
        findings: List[ReportReviewFinding] = []

        if not openai_service:
            return findings

        # 1. 找到受限资产附注表格
        restricted_note: Optional[NoteTable] = None
        for n in notes:
            combined = (n.section_title or "") + (n.account_name or "")
            if any(kw in combined for kw in self.RESTRICTED_ASSET_NOTE_KEYWORDS):
                restricted_note = n
                break

        if not restricted_note:
            return findings

        # 2. 提取有金额的受限资产明细行
        restricted_items: List[dict] = []
        skip_labels = {"合计", "小计", "总计", "项目", "项  目", ""}
        for row in restricted_note.rows:
            if not row:
                continue
            label = str(row[0]).strip() if row else ""
            # 跳过合计行、表头行
            if label in skip_labels or "合" in label and "计" in label:
                continue
            # 检查是否有数值
            has_amount = False
            amount_val = None
            for ci in range(1, len(row)):
                val = _safe_float(row[ci])
                if val is not None and abs(val) > 0.01:
                    has_amount = True
                    amount_val = val
                    break
            if has_amount:
                restricted_items.append({
                    "asset_name": label,
                    "amount": amount_val,
                })

        if not restricted_items:
            return findings

        # 3. 为每个受限资产项目收集对应科目的附注文字内容
        # 构建 account_name → 附注文字内容 映射
        def _collect_section_text(nodes: list, target_name: str) -> str:
            """递归搜索 note_sections 树，收集与目标科目相关的文字内容。"""
            texts = []
            for node in nodes:
                title = node.title if hasattr(node, 'title') else ""
                # 科目名称出现在标题中
                if target_name in title:
                    for p in (node.content_paragraphs if hasattr(node, 'content_paragraphs') else []):
                        if p.strip():
                            texts.append(p.strip())
                if hasattr(node, 'children') and node.children:
                    texts.append(_collect_section_text(node.children, target_name))
            return "\n".join(t for t in texts if t)

        # 同时从 note_tables 中收集相关表格的标题信息
        note_account_map: Dict[str, List[str]] = {}
        for n in notes:
            if n == restricted_note:
                continue
            note_account_map.setdefault(n.account_name, []).append(n.section_title or "")

        # 4. 对每个受限资产项目调用 LLM 判断
        import asyncio

        async def _check_one_asset(item: dict) -> Optional[ReportReviewFinding]:
            asset_name = item["asset_name"]
            amount = item["amount"]

            # 收集该科目的附注文字
            section_text = ""
            if note_sections:
                section_text = _collect_section_text(note_sections, asset_name)

            # 收集该科目的附注表格标题
            related_titles = note_account_map.get(asset_name, [])
            # 也尝试模糊匹配
            for acct, titles in note_account_map.items():
                if asset_name in acct or acct in asset_name:
                    related_titles.extend(titles)

            context_parts = []
            if section_text:
                # 截断避免过长
                context_parts.append(f"【{asset_name}附注文字内容】\n{section_text[:3000]}")
            if related_titles:
                context_parts.append(f"【{asset_name}附注表格标题】\n" + "\n".join(set(related_titles)))

            if not context_parts:
                # 没有找到该科目的附注内容，直接报告
                return self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=f"受限资产/{asset_name}",
                    location=f"附注-受限资产-{asset_name}",
                    description=(
                        f"受限资产表中'{asset_name}'有受限金额 {amount:,.2f}，"
                        f"但未找到'{asset_name}'科目的附注内容，无法验证是否有受限披露"
                    ),
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=f"受限资产表列示'{asset_name}'受限金额 {amount:,.2f}，需在对应科目附注中披露",
                    note_table_ids=[restricted_note.id],
                )

            context = "\n\n".join(context_parts)

            prompt = (
                f"受限资产表中列示了'{asset_name}'有受限金额 {amount:,.2f}。\n"
                f"请判断以下'{asset_name}'科目的附注内容中，是否有关于资产受限、抵押、质押、"
                f"冻结、查封、担保等相关的说明或披露。\n\n"
                f"{context}\n\n"
                "请以JSON格式返回判断结果：\n"
                '{"has_disclosure": true/false, "evidence": "找到的相关披露内容摘要（如有）", '
                '"reason": "判断理由"}\n'
                "如果附注中有任何关于该资产受限、抵押、质押、冻结、查封、担保的说明，"
                "has_disclosure 为 true；否则为 false。"
            )

            try:
                messages = [
                    {"role": "system", "content": "你是审计报告附注复核专家，负责验证受限资产的交叉披露完整性。"},
                    {"role": "user", "content": prompt},
                ]
                response = ""
                async for chunk in openai_service.stream_chat_completion(messages, temperature=0.2):
                    if isinstance(chunk, str):
                        response += chunk

                import re as _re
                match = _re.search(r'\{[\s\S]*\}', response)
                if match:
                    result = json.loads(match.group())
                    if not result.get("has_disclosure", True):
                        reason = result.get("reason", "")
                        return self._make_finding(
                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                            account_name=f"受限资产/{asset_name}",
                            location=f"附注-受限资产-{asset_name} vs 附注-{asset_name}",
                            description=(
                                f"受限资产表中'{asset_name}'有受限金额 {amount:,.2f}，"
                                f"但'{asset_name}'科目附注中未发现受限相关披露。{reason}"
                            ),
                            risk_level=RiskLevel.MEDIUM,
                            reasoning=(
                                f"受限资产表列示'{asset_name}'受限金额 {amount:,.2f}，"
                                f"对应科目附注应有受限/抵押/质押等说明"
                            ),
                            note_table_ids=[restricted_note.id],
                        )
            except Exception as e:
                logger.warning("受限资产交叉披露验证失败 %s: %s", asset_name, e)

            return None

        semaphore = asyncio.Semaphore(3)

        async def _check_with_limit(item: dict):
            async with semaphore:
                return await _check_one_asset(item)

        results = await asyncio.gather(
            *[_check_with_limit(item) for item in restricted_items],
            return_exceptions=True,
        )

        for r in results:
            if isinstance(r, ReportReviewFinding):
                findings.append(r)
            elif isinstance(r, Exception):
                logger.warning("受限资产交叉披露验证异常: %s", r)

        return findings

    # ─── 统计汇总 ───

    def get_reconciliation_summary(
        self, findings: List[ReportReviewFinding]
    ) -> Dict[str, int]:
        """生成匹配/不匹配/未检查统计。"""
        matched = sum(1 for f in findings if f.difference is not None and abs(f.difference) < TOLERANCE)
        not_found = sum(1 for f in findings if self.NOTE_VALUE_NOT_FOUND_TAG in (f.description or ""))
        mismatched = sum(1 for f in findings if f.difference is not None and abs(f.difference) >= TOLERANCE)
        return {
            "matched": matched,
            "mismatched": mismatched,
            "unchecked": not_found,
        }

    # ─── 规则引擎：从附注表格中提取期末/期初合计值（LLM 识别的兜底） ───

    # 变动列关键词（排除这些列，它们不是余额列）
    _MOVEMENT_COL_KW = [
        "增加", "减少", "增减", "转入", "转出", "摊销", "折旧",
        "计提", "处置", "变动", "核销", "转回",
    ]
    # 期末列关键词
    _CLOSING_COL_KW = ["期末", "年末", "本期", "本年"]
    # 期初列关键词
    _OPENING_COL_KW = ["期初", "年初", "上期", "上年"]
    # 账面价值关键词
    _BOOK_VALUE_KW = ["账面价值", "账面净值", "净值"]
    # 原值/成本段关键词
    _COST_SECTION_KW = ["原价", "原值", "账面原值"]
    # 累计摊销/折旧段关键词
    _AMORT_SECTION_KW = ["累计摊销", "累计折旧"]
    # 减值准备段关键词
    _IMPAIR_SECTION_KW = ["减值准备"]

    @staticmethod
    def _is_movement_col(header: str) -> bool:
        """判断表头是否为变动列（本期增加/减少等）。"""
        return any(kw in header for kw in ReconciliationEngine._MOVEMENT_COL_KW)

    @staticmethod
    def _extract_note_totals_by_rules(
        note: NoteTable,
    ) -> Tuple[Optional[float], Optional[float]]:
        """规则引擎：从附注表格中提取期末/期初合计值。

        当 LLM 的 TableStructure 未识别出 closing_balance_cell / opening_balance_cell 时，
        用本方法作为兜底。返回 (closing, opening)。

        策略优先级：
        1. 找"合计"/"总计"行 → 通过表头语义分配期末/期初
        2. 找"期末账面价值"/"期初账面价值"行
        3. 多段表格（原价-累计摊销-减值准备）→ 计算账面价值
        4. 单行表格回退
        """
        if not note.rows:
            return (None, None)

        headers = note.headers or []
        header_rows = getattr(note, "header_rows", None) or []
        # 标准化表头（去空格）
        norm_headers = [str(h or "").replace(" ", "").replace("\u3000", "") for h in headers]

        # ── 策略 1：找"合计"/"总计"行 ──
        total_row = None
        for ri in range(len(note.rows) - 1, -1, -1):
            first = str(note.rows[ri][0] if note.rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()
            if first in ("合计", "总计"):
                total_row = note.rows[ri]
                break

        if total_row is not None:
            return ReconciliationEngine._extract_from_total_row(
                total_row, norm_headers, header_rows,
            )

        # ── 策略 2：找"账面价值"行（固定资产/投资性房地产等） ──
        book_result = ReconciliationEngine._extract_book_value_rows(note)
        if book_result != (None, None):
            return book_result

        # ── 策略 3：多段表格（原价-累计摊销-减值准备）→ 计算账面价值 ──
        calc_result = ReconciliationEngine._extract_by_section_calculation(note)
        if calc_result != (None, None):
            return calc_result

        # ── 策略 4：变动表中找"期末余额"/"期末未分配利润"行 ──
        # 未分配利润等科目的附注表格是变动表（期初+增减=期末），
        # 没有"合计"行，但有"期末余额"/"期末未分配利润"行直接包含期末值。
        balance_row_result = ReconciliationEngine._extract_from_balance_label_rows(
            note, norm_headers, header_rows,
        )
        if balance_row_result != (None, None):
            return balance_row_result

        # ── 策略 5：单行表格回退 ──
        if len(note.rows) == 1:
            return ReconciliationEngine._extract_from_total_row(
                note.rows[0], norm_headers, header_rows,
            )

        return (None, None)

    @staticmethod
    def _extract_from_balance_label_rows(
        note: NoteTable,
        norm_headers: List[str],
        header_rows: List[List[str]],
    ) -> Tuple[Optional[float], Optional[float]]:
        """从变动表中找"期末余额"/"期末未分配利润"/"期初余额"行提取值。

        未分配利润等科目的附注表格是变动表（期初+增减变动=期末），
        没有"合计"行，但有标签行直接包含期末/期初值。
        """
        closing_label_kw = ["期末余额", "期末未分配", "本期期末余额", "年末余额", "期末数"]
        opening_label_kw = ["期初余额", "期初未分配", "本期期初余额", "年初余额", "期初数"]

        closing_val: Optional[float] = None
        opening_val: Optional[float] = None

        for row in note.rows:
            if not row:
                continue
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()

            is_closing_row = any(kw in first for kw in closing_label_kw)
            is_opening_row = any(kw in first for kw in opening_label_kw)

            if not is_closing_row and not is_opening_row:
                continue

            # 从该行提取第一个数值（跳过标签列）
            for ci in range(1, len(row)):
                v = _safe_float(row[ci])
                if v is not None:
                    if is_closing_row and closing_val is None:
                        closing_val = v
                    elif is_opening_row and opening_val is None:
                        opening_val = v
                    break

        return (closing_val, opening_val)

    @staticmethod
    def _extract_from_total_row(
        total_row: list,
        norm_headers: List[str],
        header_rows: List[List[str]],
    ) -> Tuple[Optional[float], Optional[float]]:
        """从合计行中根据表头语义提取期末/期初值。"""
        # 收集所有数值列
        nums: List[Tuple[int, float]] = []
        for ci in range(1, len(total_row)):
            v = _safe_float(total_row[ci])
            if v is not None:
                nums.append((ci, v))
        if not nums:
            return (None, None)

        is_move = ReconciliationEngine._is_movement_col
        closing_kw = ReconciliationEngine._CLOSING_COL_KW
        opening_kw = ReconciliationEngine._OPENING_COL_KW

        # ── 多行表头：先尝试最后一行表头中的"账面价值"列 ──
        if header_rows and len(header_rows) >= 2:
            last_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[-1]]
            first_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[0]]

            def _parent_group_of(col_idx: int) -> str:
                """回溯第一行表头，找到 col_idx 所属的父列标签。

                多行表头中，第一行通常是"期末数 | | | 期初数 | | |"这样的合并单元格，
                空列继承左边最近的非空列标签。
                """
                for ci in range(col_idx, -1, -1):
                    h = first_row_h[ci] if ci < len(first_row_h) else ""
                    if h:
                        return h
                return ""

            def _is_closing_group(col_idx: int) -> bool:
                """判断 col_idx 是否属于"期末"组。"""
                parent = _parent_group_of(col_idx)
                has_close = any(kw in parent for kw in closing_kw)
                has_open = any(kw in parent for kw in opening_kw)
                return has_close and not has_open

            def _is_opening_group(col_idx: int) -> bool:
                """判断 col_idx 是否属于"期初"组。"""
                parent = _parent_group_of(col_idx)
                return any(kw in parent for kw in opening_kw)

            # 在最后一行找"账面价值"列
            bv_cols = [ci for ci, h in enumerate(last_row_h)
                       if any(kw in h for kw in ReconciliationEngine._BOOK_VALUE_KW)]
            if len(bv_cols) >= 2:
                # 根据第一行表头判断哪个是期末、哪个是期初
                closing_bv = None
                opening_bv = None
                for ci in bv_cols:
                    if closing_bv is None and _is_closing_group(ci):
                        closing_bv = ci
                    elif opening_bv is None and _is_opening_group(ci):
                        opening_bv = ci
                # 如果无法通过父列判断，回退到位置顺序（期末在前）
                if closing_bv is None and opening_bv is None:
                    closing_bv, opening_bv = bv_cols[0], bv_cols[1]
                elif closing_bv is None:
                    closing_bv = [ci for ci in bv_cols if ci != opening_bv][0] if len(bv_cols) > 1 else None
                elif opening_bv is None:
                    opening_bv = [ci for ci in bv_cols if ci != closing_bv][0] if len(bv_cols) > 1 else None
                return (_safe_float(total_row[closing_bv]) if closing_bv is not None and closing_bv < len(total_row) else None,
                        _safe_float(total_row[opening_bv]) if opening_bv is not None and opening_bv < len(total_row) else None)
            if len(bv_cols) == 1:
                vci = bv_cols[0]
                parent_label = _parent_group_of(vci)
                val = _safe_float(total_row[vci]) if vci < len(total_row) else None
                if any(kw in parent_label for kw in opening_kw):
                    return (None, val)
                return (val, None)

            # 在最后一行找"账面余额/原值"和"减值准备"列 → 计算
            bal_cols = [ci for ci, h in enumerate(last_row_h)
                        if "账面余额" in h or "原值" in h]
            prov_cols = [ci for ci, h in enumerate(last_row_h)
                         if "减值准备" in h or "坏账准备" in h]
            if len(bal_cols) >= 2 and len(prov_cols) >= 2:
                # 根据第一行表头判断哪组是期末、哪组是期初
                closing_bal_idx = None
                opening_bal_idx = None
                for ci in bal_cols:
                    if closing_bal_idx is None and _is_closing_group(ci):
                        closing_bal_idx = ci
                    elif opening_bal_idx is None and _is_opening_group(ci):
                        opening_bal_idx = ci
                closing_prov_idx = None
                opening_prov_idx = None
                for ci in prov_cols:
                    if closing_prov_idx is None and _is_closing_group(ci):
                        closing_prov_idx = ci
                    elif opening_prov_idx is None and _is_opening_group(ci):
                        opening_prov_idx = ci
                # 回退到位置顺序
                if closing_bal_idx is None and opening_bal_idx is None:
                    closing_bal_idx, opening_bal_idx = bal_cols[0], bal_cols[1]
                elif closing_bal_idx is None:
                    closing_bal_idx = [ci for ci in bal_cols if ci != opening_bal_idx][0] if len(bal_cols) > 1 else None
                elif opening_bal_idx is None:
                    opening_bal_idx = [ci for ci in bal_cols if ci != closing_bal_idx][0] if len(bal_cols) > 1 else None
                if closing_prov_idx is None and opening_prov_idx is None:
                    closing_prov_idx, opening_prov_idx = prov_cols[0], prov_cols[1]
                elif closing_prov_idx is None:
                    closing_prov_idx = [ci for ci in prov_cols if ci != opening_prov_idx][0] if len(prov_cols) > 1 else None
                elif opening_prov_idx is None:
                    opening_prov_idx = [ci for ci in prov_cols if ci != closing_prov_idx][0] if len(prov_cols) > 1 else None

                cb = _safe_float(total_row[closing_bal_idx]) if closing_bal_idx is not None and closing_bal_idx < len(total_row) else None
                cp = _safe_float(total_row[closing_prov_idx]) if closing_prov_idx is not None and closing_prov_idx < len(total_row) else 0
                ob = _safe_float(total_row[opening_bal_idx]) if opening_bal_idx is not None and opening_bal_idx < len(total_row) else None
                op = _safe_float(total_row[opening_prov_idx]) if opening_prov_idx is not None and opening_prov_idx < len(total_row) else 0
                closing = (cb - (cp or 0)) if cb is not None else None
                opening = (ob - (op or 0)) if ob is not None else None
                return (closing, opening)

            # 在最后一行找期末/期初列（排除变动列）
            closing_cols = [ci for ci, h in enumerate(last_row_h)
                            if any(kw in h for kw in closing_kw) and not is_move(h)
                            and not any(kw in h for kw in opening_kw)]
            opening_cols = [ci for ci, h in enumerate(last_row_h)
                            if any(kw in h for kw in opening_kw) and not is_move(h)]
            if closing_cols or opening_cols:
                c_val = _safe_float(total_row[closing_cols[0]]) if closing_cols and closing_cols[0] < len(total_row) else None
                o_val = _safe_float(total_row[opening_cols[0]]) if opening_cols and opening_cols[0] < len(total_row) else None
                return (c_val, o_val)

            # 在第一行找期末/期初父列，取子列范围内第一个非变动数值
            closing_parent = -1
            opening_parent = -1
            for ci, h in enumerate(first_row_h):
                if not h or is_move(h):
                    continue
                has_open = any(kw in h for kw in opening_kw)
                if closing_parent < 0 and any(kw in h for kw in closing_kw) and not has_open:
                    closing_parent = ci
                if opening_parent < 0 and has_open:
                    opening_parent = ci

            def _pick_from_range(start: int, end: int) -> Optional[float]:
                """在列范围内找第一个非变动列的数值。
                优先选择含"账面价值"的列（应收类科目的表头中，
                同一期间组下有"账面余额"、"坏账准备"、"账面价值"三列，
                应取"账面价值"列的值）。
                """
                bv_kw_local = ReconciliationEngine._BOOK_VALUE_KW
                # 先找含"账面价值"的列
                for ci, v in nums:
                    if start <= ci < end:
                        h = last_row_h[ci] if ci < len(last_row_h) else ""
                        if not is_move(h) and any(kw in h for kw in bv_kw_local):
                            return v
                # 回退：取第一个非变动列
                for ci, v in nums:
                    if start <= ci < end:
                        h = last_row_h[ci] if ci < len(last_row_h) else ""
                        if not is_move(h):
                            return v
                return None

            if closing_parent >= 0 or opening_parent >= 0:
                c_val = None
                o_val = None
                if closing_parent >= 0:
                    parent_val = first_row_h[closing_parent]
                    end = len(total_row)
                    for ci in range(closing_parent + 1, len(first_row_h)):
                        h = first_row_h[ci]
                        if h and h != parent_val:
                            end = ci
                            break
                    c_val = _pick_from_range(closing_parent, end)
                if opening_parent >= 0:
                    parent_val = first_row_h[opening_parent]
                    end = len(total_row)
                    for ci in range(opening_parent + 1, len(first_row_h)):
                        h = first_row_h[ci]
                        if h and h != parent_val:
                            end = ci
                            break
                    o_val = _pick_from_range(opening_parent, end)
                if c_val is not None or o_val is not None:
                    return (c_val, o_val)

        # ── 单行表头或多行表头策略都未命中 → 用 norm_headers ──
        # 优先选择含"账面价值"的期末/期初列（应收类科目的合并表头如
        # "期末余额-账面余额"、"期末余额-坏账准备"、"期末余额-账面价值"，
        # 应取"账面价值"列而非"账面余额"列）
        bv_kw = ReconciliationEngine._BOOK_VALUE_KW
        closing_idx = -1
        opening_idx = -1
        closing_bv_idx = -1  # 含"账面价值"的期末列
        opening_bv_idx = -1  # 含"账面价值"的期初列
        for ci, h in enumerate(norm_headers):
            if is_move(h):
                continue
            has_open = any(kw in h for kw in opening_kw)
            has_close = any(kw in h for kw in closing_kw) and not has_open
            has_bv = any(kw in h for kw in bv_kw)
            if has_close:
                if closing_idx < 0:
                    closing_idx = ci
                if has_bv and closing_bv_idx < 0:
                    closing_bv_idx = ci
            if has_open:
                if opening_idx < 0:
                    opening_idx = ci
                if has_bv and opening_bv_idx < 0:
                    opening_bv_idx = ci
        # 优先使用含"账面价值"的列
        if closing_bv_idx >= 0:
            closing_idx = closing_bv_idx
        if opening_bv_idx >= 0:
            opening_idx = opening_bv_idx

        # ── 当表头含"账面余额"+"坏账准备"但无"账面价值"时，计算净值 ──
        # 应收类科目的合并表头可能是 ["项目", "期末余额-账面余额", "期末余额-坏账准备",
        # "期初余额-账面余额", "期初余额-坏账准备"]，没有"账面价值"列。
        # 此时需要计算 账面价值 = 账面余额 - 坏账准备。
        provision_kw = ["坏账准备", "减值准备", "跌价准备"]
        balance_kw_net = ["账面余额", "原值"]
        c_bal_idx, c_prov_idx, o_bal_idx, o_prov_idx = -1, -1, -1, -1
        for ci, h in enumerate(norm_headers):
            has_open = any(kw in h for kw in opening_kw)
            has_close_h = any(kw in h for kw in closing_kw) and not has_open
            has_bal = any(kw in h for kw in balance_kw_net)
            has_prov = any(kw in h for kw in provision_kw)
            if has_close_h and has_bal and c_bal_idx < 0:
                c_bal_idx = ci
            if has_close_h and has_prov and c_prov_idx < 0:
                c_prov_idx = ci
            if has_open and has_bal and o_bal_idx < 0:
                o_bal_idx = ci
            if has_open and has_prov and o_prov_idx < 0:
                o_prov_idx = ci
        # 如果有"账面余额"和"坏账准备"列但没有"账面价值"列，计算净值
        if c_bal_idx >= 0 and c_prov_idx >= 0 and closing_bv_idx < 0:
            cb = _safe_float(total_row[c_bal_idx]) if c_bal_idx < len(total_row) else None
            cp = _safe_float(total_row[c_prov_idx]) if c_prov_idx < len(total_row) else None
            ob = _safe_float(total_row[o_bal_idx]) if o_bal_idx >= 0 and o_bal_idx < len(total_row) else None
            op = _safe_float(total_row[o_prov_idx]) if o_prov_idx >= 0 and o_prov_idx < len(total_row) else None
            c_net = (cb - (cp or 0)) if cb is not None else None
            o_net = (ob - (op or 0)) if ob is not None else None
            if c_net is not None or o_net is not None:
                return (c_net, o_net)
        if closing_idx < 0:
            for ci, h in enumerate(norm_headers):
                if ("本期" in h or "本年" in h) and not is_move(h) and not any(kw in h for kw in opening_kw):
                    closing_idx = ci
                    break
        if opening_idx < 0:
            for ci, h in enumerate(norm_headers):
                if ("上期" in h or "上年" in h) and not is_move(h):
                    opening_idx = ci
                    break

        if closing_idx >= 0 or opening_idx >= 0:
            c_val = _safe_float(total_row[closing_idx]) if closing_idx >= 0 and closing_idx < len(total_row) else None
            o_val = _safe_float(total_row[opening_idx]) if opening_idx >= 0 and opening_idx < len(total_row) else None
            return (c_val, o_val)

        # 最终 fallback：≤2 个数值列时按位置分配
        if len(nums) <= 2:
            return (nums[0][1] if nums else None, nums[1][1] if len(nums) > 1 else None)

        return (None, None)

    @staticmethod
    def _extract_book_value_rows(
        note: NoteTable,
    ) -> Tuple[Optional[float], Optional[float]]:
        """从"期末账面价值"/"期初账面价值"行中提取值。"""
        import re as _re
        bv_kw = ReconciliationEngine._BOOK_VALUE_KW
        closing_val = None
        opening_val = None

        # 找"合计"列索引
        total_col = -1
        for ci in range(len(note.headers) - 1, 0, -1):
            h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")
            if h in ("合计", "总计"):
                total_col = ci
                break

        def _pick_row_val(row: list) -> Optional[float]:
            if total_col > 0 and total_col < len(row):
                v = _safe_float(row[total_col])
                if v is not None:
                    return v
            for ci in range(len(row) - 1, 0, -1):
                v = _safe_float(row[ci])
                if v is not None:
                    return v
            return None

        # 策略 A：分别找"期末账面价值"和"期初账面价值"行
        for row in note.rows:
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
            if ("期末" in first or "年末" in first) and any(kw in first for kw in bv_kw):
                closing_val = _pick_row_val(row)
            if ("期初" in first or "年初" in first) and any(kw in first for kw in bv_kw):
                opening_val = _pick_row_val(row)

        if closing_val is not None or opening_val is not None:
            return (closing_val, opening_val)

        # 策略 B：在"账面价值"标题行之后找"期末"/"期初"子行
        in_bv_section = False
        for row in note.rows:
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
            if any(kw in first for kw in bv_kw) and "期末" not in first and "期初" not in first and "年末" not in first and "年初" not in first:
                in_bv_section = True
                continue
            if in_bv_section:
                if "期末" in first or "年末" in first:
                    closing_val = _pick_row_val(row)
                if "期初" in first or "年初" in first:
                    opening_val = _pick_row_val(row)
                if _re.match(r"^[一二三四五六七八九十]+[、.]", first) and not any(kw in first for kw in bv_kw):
                    break

        if closing_val is not None or opening_val is not None:
            return (closing_val, opening_val)

        # 策略 C（国企报表）：找"X、…账面价值…合计"行，按表头语义提取期末/期初
        # 国企报表中固定资产/无形资产等科目的附注表格，账面价值行的标签形如
        # "五、固定资产账面价值合计"，值在"期初余额"和"期末余额"列中。
        # 优先匹配"账面价值"，其次"账面净值"/"净值"。
        section_pattern = _re.compile(r"^[一二三四五六七八九十]+[、.]")
        closing_kw = ReconciliationEngine._CLOSING_COL_KW
        opening_kw = ReconciliationEngine._OPENING_COL_KW
        is_move = ReconciliationEngine._is_movement_col
        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]

        # 预计算表头中的期末/期初列索引
        c_idx = -1
        o_idx = -1
        for ci, h in enumerate(norm_h):
            if is_move(h):
                continue
            has_open = any(kw in h for kw in opening_kw)
            if c_idx < 0 and any(kw in h for kw in closing_kw) and not has_open:
                c_idx = ci
            if o_idx < 0 and has_open:
                o_idx = ci

        if c_idx > 0 or o_idx > 0:
            best_cv, best_ov = None, None
            best_priority = 0  # 1=净值, 2=账面价值
            for row in note.rows:
                first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
                if not (section_pattern.match(first) and any(kw in first for kw in bv_kw)):
                    continue
                # 判断优先级："账面价值" > "账面净值"/"净值"
                priority = 2 if "账面价值" in first else 1
                if priority <= best_priority:
                    continue
                cv = _safe_float(row[c_idx]) if 0 < c_idx < len(row) else None
                ov = _safe_float(row[o_idx]) if 0 < o_idx < len(row) else None
                if cv is not None or ov is not None:
                    best_cv, best_ov, best_priority = cv, ov, priority
            if best_cv is not None or best_ov is not None:
                return (best_cv, best_ov)

        return (None, None)

    @staticmethod
    def _extract_by_section_calculation(
        note: NoteTable,
    ) -> Tuple[Optional[float], Optional[float]]:
        """多段表格（原价-累计摊销-减值准备）→ 计算账面价值。"""
        import re as _re
        section_pattern = _re.compile(r"^[一二三四五六七八九十]+[、.]")
        cost_kw = ReconciliationEngine._COST_SECTION_KW
        amort_kw = ReconciliationEngine._AMORT_SECTION_KW
        impair_kw = ReconciliationEngine._IMPAIR_SECTION_KW

        has_cost = False
        has_amort = False
        for row in note.rows:
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
            if section_pattern.match(first):
                if any(kw in first for kw in cost_kw):
                    has_cost = True
                if any(kw in first for kw in amort_kw):
                    has_amort = True

        if not (has_cost and has_amort):
            return (None, None)

        # 找"合计"列索引
        total_col = -1
        for ci in range(len(note.headers) - 1, 0, -1):
            h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")
            if h in ("合计", "总计"):
                total_col = ci
                break
        if total_col < 0 and len(note.headers) > 1:
            total_col = len(note.headers) - 1

        if total_col <= 0:
            return (None, None)

        current_section = ""
        section_vals: Dict[str, Dict[str, Optional[float]]] = {}

        # 国企报表：段标题行本身包含数值（如"一、账面原值合计 | XX | XX | XX | XX"），
        # 需要按表头语义（期初余额/期末余额）从段标题行直接提取。
        closing_kw = ReconciliationEngine._CLOSING_COL_KW
        opening_kw = ReconciliationEngine._OPENING_COL_KW
        is_move = ReconciliationEngine._is_movement_col
        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]
        # 预计算表头中的期末/期初列索引（排除变动列）
        hdr_closing_idx = -1
        hdr_opening_idx = -1
        for ci, h in enumerate(norm_h):
            if is_move(h):
                continue
            has_open = any(kw in h for kw in opening_kw)
            if hdr_closing_idx < 0 and any(kw in h for kw in closing_kw) and not has_open:
                hdr_closing_idx = ci
            if hdr_opening_idx < 0 and has_open:
                hdr_opening_idx = ci

        for row in note.rows:
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()
            if section_pattern.match(first):
                if any(kw in first for kw in cost_kw):
                    current_section = "cost"
                elif any(kw in first for kw in amort_kw):
                    current_section = "amort"
                elif any(kw in first for kw in impair_kw):
                    current_section = "impair"
                else:
                    current_section = ""
                # 国企报表：段标题行本身可能包含数值，按表头语义提取
                if current_section and (hdr_closing_idx > 0 or hdr_opening_idx > 0):
                    if hdr_closing_idx > 0 and hdr_closing_idx < len(row):
                        v = _safe_float(row[hdr_closing_idx])
                        if v is not None:
                            section_vals.setdefault(current_section, {})["closing"] = v
                    if hdr_opening_idx > 0 and hdr_opening_idx < len(row):
                        v = _safe_float(row[hdr_opening_idx])
                        if v is not None:
                            section_vals.setdefault(current_section, {})["opening"] = v
                continue
            if not current_section:
                continue
            if "期末" in first or "年末" in first:
                v = _safe_float(row[total_col]) if total_col < len(row) else None
                if v is not None:
                    section_vals.setdefault(current_section, {})["closing"] = v
            if "期初" in first or "年初" in first:
                v = _safe_float(row[total_col]) if total_col < len(row) else None
                if v is not None:
                    section_vals.setdefault(current_section, {})["opening"] = v

        cost_v = section_vals.get("cost", {})
        amort_v = section_vals.get("amort", {})
        impair_v = section_vals.get("impair", {})

        closing_bv = None
        opening_bv = None
        if cost_v.get("closing") is not None:
            closing_bv = cost_v["closing"] - (amort_v.get("closing") or 0) - (impair_v.get("closing") or 0)
        if cost_v.get("opening") is not None:
            opening_bv = cost_v["opening"] - (amort_v.get("opening") or 0) - (impair_v.get("opening") or 0)

        if closing_bv is not None or opening_bv is not None:
            return (closing_bv, opening_bv)

        return (None, None)

    # ─── 营业收入/营业成本合并表格专用提取 ───

    # 识别"营业收入、营业成本"合并表格的关键词
    _REVENUE_COST_TABLE_KW = ["营业收入", "营业成本"]
    _REVENUE_ACCOUNT_KW = ["营业收入", "收入"]
    _COST_ACCOUNT_KW_INCOME = ["营业成本", "成本"]

    @staticmethod
    def _is_revenue_cost_combined_table(note: NoteTable) -> bool:
        """判断附注表格是否为"营业收入、营业成本"合并表格。

        这类表格的特征：section_title 或 account_name 同时包含"营业收入"和"营业成本"，
        且表头中有"收入"和"成本"子列。
        """
        combined = (note.section_title or "") + (note.account_name or "")
        has_revenue = "营业收入" in combined
        has_cost = "营业成本" in combined
        if not (has_revenue and has_cost):
            return False
        # 检查表头中是否有"收入"和"成本"子列
        all_headers = []
        for h in (note.headers or []):
            all_headers.append(str(h or "").replace(" ", "").replace("\u3000", ""))
        for row in (getattr(note, "header_rows", None) or []):
            for h in row:
                all_headers.append(str(h or "").replace(" ", "").replace("\u3000", ""))
        header_text = " ".join(all_headers)
        return "收入" in header_text and "成本" in header_text

    @staticmethod
    def _extract_revenue_cost_from_combined_table(
        note: NoteTable,
        account_name: str,
    ) -> Tuple[Optional[float], Optional[float]]:
        """从"营业收入、营业成本按行业划分"合并表格中，按科目名称提取对应列的合计值。

        表格结构（多行表头）：
        Row0: [项目, 本期发生额, (merged), 上期发生额, (merged)]
        Row1: [项目, 收入, 成本, 收入, 成本]
        ...
        合计: [合计, 本期收入合计, 本期成本合计, 上期收入合计, 上期成本合计]

        对于"营业收入"：closing = 本期收入列, opening = 上期收入列
        对于"营业成本"：closing = 本期成本列, opening = 上期成本列

        返回 (closing, opening)。
        """
        if not note.rows:
            return (None, None)

        # 判断要提取的是"收入"还是"成本"
        clean_name = ReconciliationEngine._strip_parenthetical(account_name)
        want_cost = "成本" in clean_name

        # 找合计行
        total_row = None
        for ri in range(len(note.rows) - 1, -1, -1):
            first = str(note.rows[ri][0] if note.rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()
            if first in ("合计", "总计"):
                total_row = note.rows[ri]
                break
        if total_row is None:
            return (None, None)

        # 从多行表头或合并表头中定位"收入"和"成本"列
        header_rows = getattr(note, "header_rows", None) or []
        norm_headers = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]

        # 策略：在最后一行表头中找"收入"和"成本"列
        last_row_h = norm_headers
        if header_rows and len(header_rows) >= 2:
            last_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[-1]]

        revenue_cols: List[int] = []
        cost_cols: List[int] = []
        for ci, h in enumerate(last_row_h):
            if ci == 0:
                continue  # 跳过标签列
            if "成本" in h:
                cost_cols.append(ci)
            elif "收入" in h:
                revenue_cols.append(ci)

        if not revenue_cols and not cost_cols:
            return (None, None)

        target_cols = cost_cols if want_cost else revenue_cols
        if not target_cols:
            return (None, None)

        # 多行表头时，通过父列（第一行）区分"本期"和"上期"
        first_row_h = []
        if header_rows and len(header_rows) >= 2:
            first_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[0]]

        closing_col = None
        opening_col = None

        closing_kw = ReconciliationEngine._CLOSING_COL_KW
        opening_kw = ReconciliationEngine._OPENING_COL_KW

        if first_row_h:
            # 为每个目标列找其父列标签
            for ci in target_cols:
                parent = ""
                for pi in range(ci, -1, -1):
                    if pi < len(first_row_h) and first_row_h[pi]:
                        parent = first_row_h[pi]
                        break
                is_opening = any(kw in parent for kw in opening_kw)
                is_closing = any(kw in parent for kw in closing_kw)
                if is_opening and opening_col is None:
                    opening_col = ci
                elif is_closing and closing_col is None:
                    closing_col = ci
                elif closing_col is None:
                    closing_col = ci  # 默认第一个为本期
                elif opening_col is None:
                    opening_col = ci  # 第二个为上期
        else:
            # 单行表头：按位置分配（第一个=本期，第二个=上期）
            if len(target_cols) >= 2:
                closing_col = target_cols[0]
                opening_col = target_cols[1]
            elif len(target_cols) == 1:
                closing_col = target_cols[0]

        closing_val = None
        opening_val = None
        if closing_col is not None and closing_col < len(total_row):
            closing_val = _safe_float(total_row[closing_col])
        if opening_col is not None and opening_col < len(total_row):
            opening_val = _safe_float(total_row[opening_col])

        return (closing_val, opening_val)

    # ─── 内部工具 ───

    @staticmethod
    def _strip_parenthetical(name: str) -> str:
        """去掉科目名称中的括号说明文字，如 '资产处置收益(损失以"-"号填列）' → '资产处置收益'。"""
        import re
        return re.sub(r'[（(][^）)]*[）)]', '', name).strip()

    @staticmethod
    def _match_score(name1: str, name2: str) -> float:
        """科目名称匹配评分（精确优先）。"""
        if not name1 or not name2:
            return 0.0
        # 先去掉括号说明文字，避免共同的括号内容（如"损失以号填列"）抬高分数
        name1 = ReconciliationEngine._strip_parenthetical(name1)
        name2 = ReconciliationEngine._strip_parenthetical(name2)
        if not name1 or not name2:
            return 0.0
        if name1 == name2:
            return 1.0
        # 包含匹配：较短名称被较长名称完全包含
        if name1 in name2 or name2 in name1:
            shorter, longer = (name1, name2) if len(name1) <= len(name2) else (name2, name1)
            ratio = len(shorter) / len(longer)
            # shorter 不是 longer 的前缀 → longer 有额外前缀，通常是不同科目
            # 如"营业收入" in "营业外收入"，shorter 不是前缀 → 不同科目
            if not longer.startswith(shorter):
                return ratio * 0.5
            # 前缀包含：shorter 是 longer 的前缀（如"应收账款" → "应收账款——账龄"）
            # 短名称（≤2字）区分度低（如"其他" in "其他收益"），要求 ratio ≥ 0.8
            # 较长名称（>2字）前缀包含是强信号，保证 ≥ 0.5
            if len(shorter) <= 2:
                if ratio < 0.8:
                    return ratio * 0.8
            return max(0.5, ratio)
        # Jaccard — 仅作为兜底参考，上限 0.49 确保不会单独触发匹配
        # （只有精确匹配和前缀包含匹配才能达到 0.5 阈值）
        s1, s2 = set(name1), set(name2)
        inter = s1 & s2
        union = s1 | s2
        jaccard = len(inter) / len(union) if union else 0.0
        return min(jaccard, 0.49)

    @staticmethod
    def _get_cell_value(note: NoteTable, cell_ref: Optional[str]) -> Optional[float]:
        """从 RxCy 格式引用获取单元格值。"""
        if not cell_ref:
            return None
        try:
            parts = cell_ref.upper().replace("R", "").split("C")
            row_idx = int(parts[0])
            col_idx = int(parts[1])
            if row_idx < len(note.rows) and col_idx < len(note.rows[row_idx]):
                return _safe_float(note.rows[row_idx][col_idx])
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _get_row_col_value(note: NoteTable, row_idx: int, col_idx: int) -> Optional[float]:
        """获取指定行列的浮点值。"""
        try:
            if row_idx < len(note.rows) and col_idx < len(note.rows[row_idx]):
                return _safe_float(note.rows[row_idx][col_idx])
        except (IndexError, TypeError):
            pass
        return None

    def _get_data_rows_for_total(
        self, ts: TableStructure, total_idx: int
    ) -> List[int]:
        """获取某合计行对应的数据行索引。

        策略：
        - 如果 total 行与前一个 total/subtotal 之间存在 subtotal 行，
          说明该 total 是对 subtotal 行的汇总，此时只收集 subtotal 行。
        - 否则只收集 data 行（排除 sub_item，避免重复计算）。
        """
        # 找到当前 total 行之前最近的 total 行索引作为起始边界
        prev_boundary = -1
        for r in ts.rows:
            if r.row_index >= total_idx:
                break
            if r.role == "total":
                prev_boundary = r.row_index

        # 检查区间内是否有 subtotal 行
        subtotal_rows = []
        data_rows = []
        for r in ts.rows:
            if r.row_index >= total_idx:
                break
            if r.row_index <= prev_boundary:
                continue
            if r.role == "subtotal":
                subtotal_rows.append(r.row_index)
            elif r.role == "data":
                data_rows.append(r.row_index)

        # 如果有 subtotal 行，total 应该是对 subtotal 的汇总
        if subtotal_rows:
            return subtotal_rows
        return data_rows

    @staticmethod
    def _assess_risk(abs_diff: float, base_amount: Optional[float]) -> RiskLevel:
        """基于差异金额评估风险等级。"""
        if base_amount and abs(base_amount) > 0:
            ratio = abs_diff / abs(base_amount)
            if ratio > 0.05:
                return RiskLevel.HIGH
            elif ratio > 0.01:
                return RiskLevel.MEDIUM
        if abs_diff > 10000:
            return RiskLevel.HIGH
        elif abs_diff > 100:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _make_finding(
        category: ReportReviewFindingCategory,
        account_name: str,
        location: str,
        description: str,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        statement_amount: Optional[float] = None,
        note_amount: Optional[float] = None,
        difference: Optional[float] = None,
        reasoning: str = "",
        note_table_ids: Optional[List[str]] = None,
    ) -> ReportReviewFinding:
        return ReportReviewFinding(
            id=str(uuid.uuid4())[:8],
            category=category,
            risk_level=risk_level,
            account_name=account_name,
            statement_amount=statement_amount,
            note_amount=note_amount,
            difference=difference,
            location=location,
            description=description,
            suggestion="请核实数据并修正",
            analysis_reasoning=reasoning,
            note_table_ids=note_table_ids or [],
            confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
            status=FindingStatus.OPEN,
        )



# 模块级单例
reconciliation_engine = ReconciliationEngine()
