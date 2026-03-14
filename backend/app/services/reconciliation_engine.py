"""勾稽校验引擎（本地规则为主）。

基于 Table_Structure_Analyzer 输出的结构化信息执行确定性数值校验：
- 科目名称模糊匹配构建对照映射
- 金额一致性校验（报表 vs 附注合计值）
- 附注表格内部勾稽（横纵加总）
- 余额变动公式校验（期初+增加-减少=期末）
- 其中项校验（子项之和 ≤ 父项）
"""
import logging
import uuid
from typing import Dict, List, Optional, Tuple

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    MatchingEntry,
    MatchingMap,
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
        name = item.account_name
        # 汇总行（如"非流动负债合计"）
        if any(name.endswith(kw) for kw in self.STATEMENT_SUBTOTAL_KEYWORDS):
            return True
        # 现金流量表科目：仅白名单内的科目有附注披露
        is_cash_flow = (
            item.statement_type == StatementType.CASH_FLOW
            or any(kw in name for kw in self.CASH_FLOW_NAME_INDICATORS)
        )
        if is_cash_flow:
            if not any(kw in name for kw in self.CASH_FLOW_NOTE_KEYWORDS):
                return True
        return False

    # 附注表格标题中含这些关键词时，表示仅披露重要/主要项目，
    # 报表金额应 ≥ 附注合计（附注是部分明细，不是全部）
    PARTIAL_DISCLOSURE_KEYWORDS = [
        "重要", "主要", "重大",
    ]

    def _is_partial_disclosure(self, note: NoteTable) -> bool:
        """判断附注表格是否仅披露部分项目（如"重要在建工程项目变动情况"）。"""
        combined = (note.section_title or "") + (note.account_name or "")
        return any(kw in combined for kw in self.PARTIAL_DISCLOSURE_KEYWORDS)

    def check_amount_consistency(
        self,
        matching_map: MatchingMap,
        items: List[StatementItem],
        notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """基于 TableStructure 定位附注合计值，与报表余额比对。

        当一个报表科目匹配了多个附注表格时，只要有任一表格的金额与报表一致，
        就视为该科目校验通过（跳过变动表等辅助表格的误报）。

        对于"重要项目"类附注表格（仅披露部分明细），采用宽松比对：
        报表金额 ≥ 附注合计即视为通过。
        """
        findings: List[ReportReviewFinding] = []
        item_map = {i.id: i for i in items}
        note_map = {n.id: n for n in notes}

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

            for note_id in entry.note_table_ids:
                note = note_map.get(note_id)
                ts = table_structures.get(note_id)
                if not note or not ts:
                    continue

                is_partial = self._is_partial_disclosure(note)

                # 获取附注合计值
                note_closing = self._get_cell_value(note, ts.closing_balance_cell)
                note_opening = self._get_cell_value(note, ts.opening_balance_cell)

                # 期末余额比对
                if item.closing_balance is not None and note_closing is not None:
                    if _amounts_equal(item.closing_balance, note_closing):
                        closing_matched = True
                    elif is_partial and item.closing_balance >= note_closing - TOLERANCE:
                        # 重要项目表：报表金额 ≥ 附注合计即通过
                        closing_matched = True
                    else:
                        diff = round(item.closing_balance - note_closing, 2)
                        closing_findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                            account_name=item.account_name,
                            statement_amount=item.closing_balance,
                            note_amount=note_closing,
                            difference=diff,
                            location=f"附注-{item.account_name}-{note.section_title}-期末余额",
                            description=f"报表期末余额{item.closing_balance}与附注合计{note_closing}不一致，差异{diff}",
                            risk_level=self._assess_risk(abs(diff), item.closing_balance),
                            reasoning=f"校验公式: 报表期末余额({item.closing_balance}) - 附注合计({note_closing}) = {diff}",
                            note_table_ids=[note_id],
                        ))

                # 期初余额比对
                if item.opening_balance is not None and note_opening is not None:
                    if _amounts_equal(item.opening_balance, note_opening):
                        opening_matched = True
                    elif is_partial and item.opening_balance >= note_opening - TOLERANCE:
                        # 重要项目表：报表金额 ≥ 附注合计即通过
                        opening_matched = True
                    else:
                        diff = round(item.opening_balance - note_opening, 2)
                        opening_findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                            account_name=item.account_name,
                            statement_amount=item.opening_balance,
                            note_amount=note_opening,
                            difference=diff,
                            location=f"附注-{item.account_name}-{note.section_title}-期初余额",
                            description=f"报表期初余额{item.opening_balance}与附注合计{note_opening}不一致，差异{diff}",
                            risk_level=self._assess_risk(abs(diff), item.opening_balance),
                            reasoning=f"校验公式: 报表期初余额({item.opening_balance}) - 附注合计({note_opening}) = {diff}",
                            note_table_ids=[note_id],
                        ))

            # 只有当所有匹配表格都不一致时，才报告差异最小的那个 finding
            if not closing_matched and closing_findings:
                best = min(closing_findings, key=lambda f: abs(f.difference or 0))
                findings.append(best)
            if not opening_matched and opening_findings:
                best = min(opening_findings, key=lambda f: abs(f.difference or 0))
                findings.append(best)

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
        return any(kw in combined for kw in self.SKIP_INTEGRITY_KEYWORDS)

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
                for di in data_indices:
                    v = self._get_row_col_value(note_table, di, col.col_index)
                    if v is not None:
                        data_sum += v
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

    # ─── 统计汇总 ───

    def get_reconciliation_summary(
        self, findings: List[ReportReviewFinding]
    ) -> Dict[str, int]:
        """生成匹配/不匹配/未检查统计。"""
        matched = sum(1 for f in findings if f.difference is not None and abs(f.difference) < TOLERANCE)
        mismatched = sum(1 for f in findings if f.difference is not None and abs(f.difference) >= TOLERANCE)
        return {
            "matched": matched,
            "mismatched": mismatched,
            "unchecked": 0,
        }

    # ─── 内部工具 ───

    @staticmethod
    def _match_score(name1: str, name2: str) -> float:
        """科目名称匹配评分（精确优先）。"""
        if not name1 or not name2:
            return 0.0
        if name1 == name2:
            return 1.0
        # 包含匹配：较短名称被较长名称完全包含
        if name1 in name2 or name2 in name1:
            shorter, longer = (name1, name2) if len(name1) <= len(name2) else (name2, name1)
            # 长度比越接近，匹配越精确；惩罚差异过大的包含匹配
            # 例如 "收入" in "营业外收入" → ratio=0.5 → score=0.5（低于阈值，不匹配）
            # 例如 "营业外收入" in "营业外收入明细" → ratio=0.71 → score=0.71
            ratio = len(shorter) / len(longer)
            return max(0.5, ratio) if ratio >= 0.6 else ratio
        # Jaccard
        s1, s2 = set(name1), set(name2)
        inter = s1 & s2
        union = s1 | s2
        return len(inter) / len(union) if union else 0.0

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
