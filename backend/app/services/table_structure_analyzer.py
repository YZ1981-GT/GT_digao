"""表格结构识别服务（LLM 辅助）。

分析附注表格的语义结构（合计行/其中项/列语义/余额变动结构），
输出结构化的 TableStructure 供 Reconciliation_Engine 使用。
LLM 调用失败时回退到基于关键词的规则识别。
"""
import json
import logging
import re
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from ..models.audit_schemas import (
    MatchingAnalysis,
    NoteTable,
    StatementItem,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from .openai_service import OpenAIService, estimate_token_count, truncate_to_token_limit

logger = logging.getLogger(__name__)


class TableStructureAnalyzer:
    """表格结构识别服务，调用 LLM 分析附注表格语义结构。"""

    # 合计行关键词
    TOTAL_KEYWORDS = ["合计", "总计", "合计数", "小计", "总额", "合 计"]
    SUBTOTAL_KEYWORDS = ["小计", "分计"]

    # 其中项关键词
    SUB_ITEM_KEYWORDS = ["其中：", "其中:", "其中"]

    # 社会保险费"其中"子项区域的截断关键词：这些行是独立的薪酬科目，不是社会保险费的子项
    _SOCIAL_INSURANCE_SUB_ITEM_CUTOFF = ["住房公积金"]

    # 列语义关键词
    COLUMN_KEYWORDS = {
        "opening_balance": ["期初余额", "期初", "年初余额", "年初", "上期余额", "上年末"],
        "closing_balance": ["期末余额", "期末", "年末余额", "年末", "本期余额"],
        "current_increase": ["本期增加", "增加额", "增加", "本期转入", "借方发生额", "本年增加"],
        "current_decrease": ["本期减少", "减少额", "减少", "本期转出", "贷方发生额", "本年减少"],
        "current_period": ["本期发生额", "本期金额", "本年金额", "本年累计", "本年发生额"],
        "prior_period": ["上期发生额", "上期金额", "上年金额", "上年同期", "上年发生额"],
        "book_value": ["账面价值", "账面净值"],
        "label": ["项目", "科目", "类别", "名称", "内容"],
    }

    # 余额变动结构关键词组合
    BALANCE_FORMULA_INDICATORS = [
        ("期初", "增加", "减少", "期末"),
        ("年初", "增加", "减少", "年末"),
        ("期初余额", "本期增加", "本期减少", "期末余额"),
    ]

    # 含并列分组的表格（account_name 关键词），余额变动公式不适用于整行
    MULTI_GROUP_ACCOUNT_KEYWORDS = [
        "开发支出",
        "在建工程",
    ]

    # 结构缓存（LRU，上限 500 条，避免长时间运行内存无限增长）
    _CACHE_MAXSIZE = 500
    _cache: OrderedDict  # 实例级别初始化

    def __init__(self):
        self._cache: OrderedDict[str, TableStructure] = OrderedDict()

    def _cache_put(self, key: str, value: TableStructure):
        """写入缓存，超出上限时淘汰最早的条目。"""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        while len(self._cache) > self._CACHE_MAXSIZE:
            self._cache.popitem(last=False)

    def _is_total_row(self, label: str) -> bool:
        """判断是否为合计行。要求关键词在 label 末尾或 label 就是关键词，
        避免误匹配"按组合计提"这类包含"合计"子串的科目名。"""
        if not label:
            return False
        for kw in self.TOTAL_KEYWORDS:
            if label == kw:
                return True
            # label 以关键词结尾，如"应收账款合计"、"  合计"
            if label.endswith(kw):
                return True
            # label 以关键词开头，如"合计数"、"总计"
            if label.startswith(kw):
                return True
        return False

    # ─── Public API ───

    async def analyze_table_structure(
        self, note_table: NoteTable, openai_service: Optional[OpenAIService] = None,
        template_hint: Optional[str] = None,
        statement_amount_hint: Optional[str] = None,
    ) -> TableStructure:
        """分析附注表格语义结构，返回 TableStructure。

        优先使用规则识别（速度快），仅当规则识别置信度低且 LLM 可用时才调用 LLM 增强。
        结果缓存到内存避免重复调用。

        Args:
            template_hint: 模板中该科目的表格格式参考（帮助 LLM 理解表格结构）
            statement_amount_hint: 报表金额提示（帮助 LLM 定位正确的余额单元格）
        """
        # 检查缓存
        if note_table.id in self._cache:
            self._cache.move_to_end(note_table.id)
            return self._cache[note_table.id]

        # 先用规则识别（纯本地计算，毫秒级）
        structure = self._analyze_with_rules(note_table)

        # 仅当规则识别置信度低且有 LLM 服务时，才调用 LLM 增强
        if structure.structure_confidence == "low" and openai_service and note_table.headers:
            try:
                llm_structure = await self._analyze_with_llm(
                    note_table, openai_service,
                    template_hint=template_hint,
                    statement_amount_hint=statement_amount_hint,
                )
                if llm_structure is not None:
                    structure = llm_structure
            except Exception as e:
                logger.warning("LLM 增强分析失败，使用规则识别结果: %s", e)

        # 缓存结果
        self._cache_put(note_table.id, structure)
        return structure

    def analyze_matching_relationship(
        self,
        statement_item: StatementItem,
        note_table: NoteTable,
        table_structure: Optional[TableStructure] = None,
    ) -> MatchingAnalysis:
        """分析报表科目与附注表格之间的对应关系。"""
        confidence = 0.0
        matched_cell_closing = None
        matched_cell_opening = None
        mapping_desc = ""

        # 名称匹配置信度
        if statement_item.account_name == note_table.account_name:
            confidence = 1.0
        elif statement_item.account_name in note_table.account_name:
            confidence = 0.8
        elif note_table.account_name in statement_item.account_name:
            confidence = 0.7
        else:
            # 模糊匹配
            confidence = self._fuzzy_match_score(
                statement_item.account_name, note_table.account_name
            )

        # 如果有结构信息，定位合计单元格
        if table_structure:
            matched_cell_closing = table_structure.closing_balance_cell
            matched_cell_opening = table_structure.opening_balance_cell
            mapping_desc = (
                f"报表'{statement_item.account_name}'对应附注"
                f"'{note_table.section_title}'的合计行"
            )
        else:
            mapping_desc = f"报表'{statement_item.account_name}'对应附注'{note_table.section_title}'"

        return MatchingAnalysis(
            statement_item_id=statement_item.id,
            note_table_id=note_table.id,
            matched_cell_closing=matched_cell_closing,
            matched_cell_opening=matched_cell_opening,
            mapping_description=mapping_desc,
            confidence=confidence,
        )

    def clear_cache(self):
        """清除结构缓存。"""
        self._cache.clear()

    async def reanalyze_with_llm(
        self, note_table: NoteTable, openai_service: OpenAIService,
        template_hint: Optional[str] = None,
        statement_amount_hint: Optional[str] = None,
        error_hint: Optional[str] = None,
    ) -> Optional[TableStructure]:
        """强制使用 LLM 重新分析表格结构（跳过缓存和置信度检查）。

        用于金额核对不一致时，对疑似识别错误的表格进行二次校验。
        如果 LLM 返回了不同的结构（closing_balance_cell 或 opening_balance_cell 变化），
        则更新缓存并返回新结构；否则返回 None 表示结构未变。

        Args:
            template_hint: 模板中该科目的表格格式参考（帮助 LLM 理解表格结构）
            statement_amount_hint: 报表金额提示（帮助 LLM 定位正确的余额单元格）
            error_hint: 上一轮本地校验发现的错误描述（帮助 LLM 针对性修正结构）
        """
        old_structure = self._cache.get(note_table.id)

        # 如果有错误提示，将其附加到 statement_amount_hint 中传递给 LLM
        enhanced_hint = statement_amount_hint or ""
        if error_hint:
            enhanced_hint += f"\n\n【上一轮校验发现的问题】\n{error_hint}\n请特别注意上述问题，可能是行角色（total/data/sub_item）或列语义（opening_balance/closing_balance/current_increase/current_decrease）识别有误。"

        try:
            llm_structure = await self._analyze_with_llm(
                note_table, openai_service,
                template_hint=template_hint,
                statement_amount_hint=enhanced_hint if enhanced_hint.strip() else statement_amount_hint,
            )
            if llm_structure is None:
                logger.info("LLM 重新分析未返回有效结构，保留原结构: %s", note_table.id)
                return None

            # 比较关键字段是否变化
            if old_structure:
                closing_changed = llm_structure.closing_balance_cell != old_structure.closing_balance_cell
                opening_changed = llm_structure.opening_balance_cell != old_structure.opening_balance_cell
                if closing_changed or opening_changed:
                    logger.info(
                        "LLM 重新分析发现结构差异 %s: closing %s→%s, opening %s→%s",
                        note_table.id,
                        old_structure.closing_balance_cell, llm_structure.closing_balance_cell,
                        old_structure.opening_balance_cell, llm_structure.opening_balance_cell,
                    )
                    # 更新缓存
                    self._cache_put(note_table.id, llm_structure)
                    return llm_structure
                else:
                    logger.info("LLM 重新分析结果与规则一致，结构确认无误: %s", note_table.id)
                    return None
            else:
                # 没有旧结构，直接使用 LLM 结果
                self._cache_put(note_table.id, llm_structure)
                return llm_structure

        except Exception as e:
            logger.warning("LLM 重新分析失败 %s: %s", note_table.id, e)
            return None

    # ─── 宽表横向公式 LLM 分析 ───

    # 宽表关键词和公式预设从独立模块导入，便于维护和扩展
    from .wide_table_presets import WIDE_TABLE_ACCOUNT_KEYWORDS, WIDE_TABLE_FORMULA_PRESETS

    @classmethod
    def _find_preset_for_note(cls, note_table: NoteTable) -> Optional[Dict]:
        """根据科目名称和标题匹配最佳预设。

        匹配规则：
        - 必须匹配科目关键词
        - 如果预设定义了 match_title_keywords，则至少需要匹配一个标题关键词
        - 排除关键词命中时跳过
        """
        combined = (note_table.account_name or "") + (note_table.section_title or "")
        title = note_table.section_title or ""

        best_preset = None
        best_score = 0

        for preset in cls.WIDE_TABLE_FORMULA_PRESETS:
            # 必须匹配科目关键词
            acct_match = any(kw in combined for kw in preset["match_keywords"])
            if not acct_match:
                continue

            # 排除关键词
            if preset.get("exclude_title_keywords"):
                if any(kw in title for kw in preset["exclude_title_keywords"]):
                    continue

            score = 1  # 基础分：科目匹配
            # 标题关键词加分
            if preset.get("match_title_keywords"):
                title_matched = False
                for kw in preset["match_title_keywords"]:
                    if kw in title:
                        score += 2
                        title_matched = True
                # 如果预设要求标题关键词但一个都没匹配上，跳过该预设
                if not title_matched:
                    continue
            else:
                # 无标题关键词要求，给一个小加分
                score += 0.5

            if score > best_score:
                best_score = score
                best_preset = preset

        return best_preset


    @classmethod
    def try_build_formula_from_preset(
        cls,
        note_table: NoteTable,
    ) -> Optional[Dict]:
        """尝试基于预设模板和表头关键词匹配，直接构建宽表公式（不依赖 LLM）。

        对于长期股权投资明细等标准表格，通过关键词匹配表头列与预设列的对应关系，
        生成与 LLM 返回格式一致的公式结构。

        同时支持检测 category_sum（上市版分类合计型）布局：
        当表头列名是具体项目/公司名称而非变动关键词，且最后一列为"合计"时，
        直接构建 category_sum 公式。

        返回 None 表示无法匹配。
        """
        preset = cls._find_preset_for_note(note_table)
        if not preset:
            return None
        if not note_table.headers or len(note_table.headers) < 5:
            return None

        headers = [str(h or "") for h in note_table.headers]

        # ── 先检测是否为 category_sum（上市版分类合计型）布局 ──
        # 特征：最后一列为"合计"，中间列是具体项目/公司名称而非变动关键词
        category_sum_result = cls._try_build_category_sum_from_headers(note_table, headers)
        if category_sum_result is not None:
            return category_sum_result

        # ── 以下为 movement（变动公式型）构建逻辑 ──
        template_cols = preset["template_columns"]

        # 为每个预设列生成匹配关键词
        def _col_keywords(tc: Dict) -> List[str]:
            """从预设列名中提取匹配关键词。"""
            name = tc.get("name", "")
            keywords = []
            # 直接使用列名中的关键词
            for seg in ["追加", "新增投资", "减少投资", "投资损益", "其他综合",
                         "其他权益", "现金股利", "宣告发放", "计提减值", "减值准备",
                         "本期增加", "本期减少", "转入固定", "本期摊销",
                         "其他减少", "其他增加",
                         "内部开发", "确认为无形", "计入当期", "转入当期",
                         "计提", "转回",
                         "转销", "企业合并", "处置", "账面价值",
                         "利息资本化", "投资成本",
                         "收回或转回", "核销", "暂时性差异",
                         "递延所得税"]:
                if seg in name:
                    keywords.append(seg)
            # 如果没有提取到关键词，使用列名本身（去掉括号内容）
            if not keywords:
                import re
                clean = re.sub(r'[（(][^）)]*[）)]', '', name).strip()
                if clean:
                    keywords.append(clean)
            return keywords

        # ── 逐列匹配 ──
        columns: List[Dict] = []
        used_col_indices: set = set()

        # 先匹配 label 列（通常是第0列）
        label_idx = 0
        columns.append({"col_index": label_idx, "role": "label", "sign": None, "name": headers[label_idx]})
        used_col_indices.add(label_idx)

        # 匹配 opening 和 closing 列
        opening_idx = None
        closing_idx = None
        for ci, h in enumerate(headers):
            if ci in used_col_indices:
                continue
            h_clean = h.replace(" ", "").replace("\u3000", "").replace("\n", "").replace("\r", "")
            # opening: 含"期初"或"年初"，且含"账面价值"或"余额"（排除"减值准备"和"投资成本"）
            if opening_idx is None and any(k in h_clean for k in ["期初", "年初"]):
                if "减值" not in h_clean and "投资成本" not in h_clean:
                    opening_idx = ci
            # closing: 含"期末"或"年末"，且含"账面价值"或"余额"（排除"减值准备"）
            if closing_idx is None and any(k in h_clean for k in ["期末", "年末"]):
                if "减值" not in h_clean and "投资成本" not in h_clean:
                    closing_idx = ci

        if opening_idx is None or closing_idx is None:
            return None

        used_col_indices.add(opening_idx)
        used_col_indices.add(closing_idx)
        columns.append({"col_index": opening_idx, "role": "opening", "sign": "+",
                         "name": headers[opening_idx]})

        # 匹配 movement 和 skip 列
        # 从预设中提取非 label/opening/closing 的列
        movement_templates = [tc for tc in template_cols
                              if tc["role"] in ("movement", "skip")]

        # 第一轮：关键词匹配
        unmatched_templates: List[Dict] = []
        matched_movement_count = 0
        for tc in movement_templates:
            kws = _col_keywords(tc)
            best_ci = None
            best_score = 0
            for ci, h in enumerate(headers):
                if ci in used_col_indices:
                    continue
                h_clean = h.replace(" ", "").replace("\u3000", "").replace("\n", "").replace("\r", "")
                score = 0
                for kw in kws:
                    if kw in h_clean:
                        score += len(kw)  # 更长的关键词匹配得分更高
                if score > best_score:
                    best_score = score
                    best_ci = ci

            if best_ci is not None:
                used_col_indices.add(best_ci)
                columns.append({
                    "col_index": best_ci,
                    "role": tc["role"],
                    "sign": tc.get("sign"),
                    "name": headers[best_ci],
                })
                if tc["role"] == "movement":
                    matched_movement_count += 1
            else:
                unmatched_templates.append(tc)

        # 第二轮：位置顺序兜底
        remaining_cols = sorted(
            ci for ci in range(opening_idx + 1, closing_idx)
            if ci not in used_col_indices
        )
        if remaining_cols:
            _inc_kw = ["增加", "转入", "计提", "追加"]
            _dec_kw = ["减少", "转出", "摊销", "折旧", "处置", "转回", "转销", "核销"]

            if matched_movement_count > 0:
                # 预设基本匹配（如存货跌价准备的两个"其他"列）：
                # 按预设顺序继承符号
                for tc, ci in zip(unmatched_templates, remaining_cols):
                    used_col_indices.add(ci)
                    columns.append({
                        "col_index": ci,
                        "role": tc["role"],
                        "sign": tc.get("sign"),
                        "name": headers[ci],
                    })
            else:
                # 简化版表格（如开发支出只有增加/减少列）：
                # 根据表头自身的增加/减少关键词推断符号
                for ci in remaining_cols:
                    h_clean = headers[ci].replace(" ", "").replace("\u3000", "").replace("\n", "").replace("\r", "")
                    if any(kw in h_clean for kw in _inc_kw):
                        sign = "+"
                    elif any(kw in h_clean for kw in _dec_kw):
                        sign = "-"
                    else:
                        sign = None  # 无法判断，标记为 skip
                    used_col_indices.add(ci)
                    columns.append({
                        "col_index": ci,
                        "role": "movement" if sign else "skip",
                        "sign": sign,
                        "name": headers[ci],
                    })

        # 添加 closing 列
        columns.append({"col_index": closing_idx, "role": "closing", "sign": "=",
                         "name": headers[closing_idx]})

        # 将未匹配的列标记为 skip（如果在 opening 和 closing 之间）
        for ci in range(len(headers)):
            if ci not in used_col_indices:
                columns.append({
                    "col_index": ci,
                    "role": "skip",
                    "sign": None,
                    "name": headers[ci],
                })

        # 按 col_index 排序
        columns.sort(key=lambda c: c["col_index"])

        # 检测 data_row_start：跳过表头行
        data_row_start = cls._detect_data_row_start(note_table)

        return {
            "formula_type": "movement",
            "columns": columns,
            "formula_description": preset.get("formula", ""),
            "data_row_start": data_row_start,
            "multi_section": preset.get("multi_section", False),
        }

    # ── 变动关键词：出现在表头中说明该列是变动/余额语义，而非分类名称 ──
    _MOVEMENT_HEADER_KEYWORDS = [
        "期初", "期末", "年初", "年末", "余额",
        "增加", "减少", "增减", "变动", "摊销", "折旧",
        "转入", "转出", "计提", "转回", "转销", "处置",
        "投资损益", "投资成本", "减值准备", "账面价值",
        "综合收益", "权益变动", "现金股利",
    ]

    @classmethod
    def _try_build_category_sum_from_headers(
        cls,
        note_table: NoteTable,
        headers: List[str],
    ) -> Optional[Dict]:
        """检测并构建 category_sum（上市版分类合计型）公式。

        判断逻辑：
        1. 最后一列（或倒数第二列）为"合计"
        2. 中间列大部分不含变动关键词（即列名是具体项目/公司名称）
        """
        if len(headers) < 3:
            return None

        # 查找"合计"列（通常是最后一列或倒数第二列）
        total_col_idx = None
        for ci in range(len(headers) - 1, max(len(headers) - 3, 0), -1):
            h_clean = headers[ci].replace(" ", "").replace("\u3000", "")
            if h_clean in ("合计", "总计"):
                total_col_idx = ci
                break

        if total_col_idx is None:
            return None

        # 中间列（排除第0列标签和合计列）中，检查有多少列含变动关键词
        data_col_candidates = []
        movement_col_count = 0
        for ci in range(1, len(headers)):
            if ci == total_col_idx:
                continue
            h_clean = headers[ci].replace(" ", "").replace("\u3000", "")
            is_movement = any(kw in h_clean for kw in cls._MOVEMENT_HEADER_KEYWORDS)
            if is_movement:
                movement_col_count += 1
            else:
                data_col_candidates.append(ci)

        # 如果大部分中间列都含变动关键词，说明不是 category_sum 布局
        total_middle = len(headers) - 2  # 排除标签列和合计列
        if total_middle <= 0:
            return None
        # 超过一半的中间列含变动关键词 → 不是 category_sum
        if movement_col_count > total_middle * 0.5:
            return None
        # 至少需要 1 个 data 列
        if not data_col_candidates:
            return None

        # ── 构建 category_sum 公式 ──
        columns: List[Dict] = []
        columns.append({"col_index": 0, "role": "label", "sign": None, "name": headers[0]})

        data_names = []
        for ci in data_col_candidates:
            columns.append({"col_index": ci, "role": "data", "sign": "+", "name": headers[ci]})
            data_names.append(headers[ci])

        columns.append({"col_index": total_col_idx, "role": "total", "sign": "=", "name": headers[total_col_idx]})

        # 合计列之后的列标记为 skip
        for ci in range(total_col_idx + 1, len(headers)):
            columns.append({"col_index": ci, "role": "skip", "sign": None, "name": headers[ci]})

        # 变动关键词列也标记为 skip（它们在 category_sum 中不参与横向公式）
        for ci in range(1, len(headers)):
            if ci == total_col_idx:
                continue
            if ci not in data_col_candidates and ci > total_col_idx:
                continue  # 已在上面处理
            h_clean = headers[ci].replace(" ", "").replace("\u3000", "")
            if any(kw in h_clean for kw in cls._MOVEMENT_HEADER_KEYWORDS):
                columns.append({"col_index": ci, "role": "skip", "sign": None, "name": headers[ci]})

        # 按 col_index 排序并去重
        seen = set()
        unique_columns = []
        columns.sort(key=lambda c: c["col_index"])
        for c in columns:
            if c["col_index"] not in seen:
                seen.add(c["col_index"])
                unique_columns.append(c)

        data_row_start = cls._detect_data_row_start(note_table)
        formula_desc = " + ".join(data_names) + f" = {headers[total_col_idx]}"

        return {
            "formula_type": "category_sum",
            "columns": unique_columns,
            "formula_description": formula_desc,
            "data_row_start": data_row_start,
        }

    @classmethod
    def _detect_data_row_start(cls, note_table: NoteTable) -> int:
        """检测数据行起始索引，跳过表头行。"""
        data_row_start = 0
        if note_table.rows:
            for ri, row in enumerate(note_table.rows):
                if not row:
                    continue
                label = str(row[0] or "").strip()
                # 如果第一行看起来像表头（与 headers 相同），跳过
                if label and note_table.headers and label == str(note_table.headers[0] or "").strip():
                    data_row_start = ri + 1
                    continue
                # 如果第一行有数值，说明是数据行
                has_num = False
                for v in row[1:]:
                    if v is not None:
                        try:
                            float(str(v).replace(",", "").replace("，", ""))
                            has_num = True
                            break
                        except (ValueError, TypeError):
                            pass
                if has_num:
                    data_row_start = ri
                    break
        return data_row_start

    @staticmethod
    def is_wide_table_candidate(note_table: NoteTable, table_structure: Optional[TableStructure] = None) -> bool:
        """判断是否为需要 LLM 公式分析的宽表候选。

        条件：
        1. 列数 ≥ 5（含标签列）— 如 项目|期初|增加|摊销|期末
        2. 科目名称匹配宽表关键词
        3. 表头中同时含有期初/期末类关键词和变动类关键词（排除分类表/余额对照表）
        """
        if not note_table.headers or len(note_table.headers) < 5:
            return False
        # 如果已有结构且标记了余额变动公式，说明已被常规 check_balance_formula 覆盖
        # 但如果列数很多（≥8），常规公式可能遗漏中间列，仍需宽表分析
        if table_structure and table_structure.has_balance_formula and len(note_table.headers) < 8:
            return False

        headers_text = " ".join(str(h) for h in note_table.headers)
        # 表头中是否含期初/期末类关键词
        _balance_kw = ["期初", "年初", "期末", "年末"]
        has_balance = any(k in headers_text for k in _balance_kw)
        # 表头中是否含变动类关键词（增加/减少/计提/转回等）
        # 逐列检查，排除百分比/比例列（如"计提比例(%)"含"计提"但不是变动列）
        _movement_kw = ["增加", "减少", "增减", "变动", "摊销", "折旧",
                        "转入", "转出", "计提", "转回", "转销", "处置",
                        "追加", "投资损益", "综合收益", "权益变动"]
        _pct_kw = ["比例", "%", "比率", "占比"]
        movement_col_count = 0
        for h in note_table.headers:
            h_str = str(h or "")
            if any(pk in h_str for pk in _pct_kw):
                continue  # 跳过百分比列
            if any(mk in h_str for mk in _movement_kw):
                movement_col_count += 1
        has_movement = movement_col_count >= 1
        # 通用检测（无关键词匹配）需要至少2个变动列才算宽表
        has_strong_movement = movement_col_count >= 2

        combined = (note_table.account_name or "") + (note_table.section_title or "")
        title = note_table.section_title or ""
        # 分类表/账龄表标题关键词 → 排除宽表候选
        _classification_kw = ["按组合", "按单项", "分类", "组合方法", "账龄", "逾期"]
        is_classification = any(ck in title for ck in _classification_kw)

        for kw in TableStructureAnalyzer.WIDE_TABLE_ACCOUNT_KEYWORDS:
            if kw in combined:
                if is_classification:
                    continue  # 分类表不是宽表
                # 关键词匹配后，还需验证表头确实含有变动结构
                # 排除余额对照表
                if has_balance and has_movement:
                    return True
                # 列数 ≥ 8 且至少有变动关键词（可能表头用"本期"代替"期初"）
                if has_movement and len(note_table.headers) >= 8:
                    return True
                # 不满足变动结构条件 → 不是宽表
                continue

        # 通用检测：含"期初"和"期末"且列数 ≥ 8 且有足够变动列
        has_opening = any(k in headers_text for k in ["期初", "年初"])
        has_closing = any(k in headers_text for k in ["期末", "年末"])
        if has_opening and has_closing and has_strong_movement and len(note_table.headers) >= 8:
            return True
        return False

    async def analyze_wide_table_formula(
        self,
        note_table: NoteTable,
        openai_service: OpenAIService,
        template_hint: Optional[str] = None,
    ) -> Optional[Dict]:
        """分析宽表的横向公式结构。

        优先尝试基于预设模板的规则匹配（不依赖 LLM），匹配失败时回退到 LLM 分析。

        LLM 只负责识别列语义和公式关系，不做数值计算。
        返回格式：
        {
            "columns": [
                {"col_index": 0, "role": "label"},
                {"col_index": 1, "role": "opening", "sign": "+"},
                {"col_index": 2, "role": "movement", "sign": "+", "name": "追加投资"},
                {"col_index": 3, "role": "movement", "sign": "-", "name": "减少投资"},
                ...
                {"col_index": 11, "role": "closing", "sign": "="},
            ],
            "formula_description": "期初账面价值 + 追加投资 + 投资损益 + ... - 减少投资 - ... = 期末账面价值",
            "skip_col_indices": [2, 12],  // 非数值列（如百分比列）不参与公式
            "data_row_start": 2,  // 数据行起始索引
            "total_row_keywords": ["合计", "小计"]
        }
        """
        # ── 优先：规则匹配预设模板 ──
        rule_result = self.try_build_formula_from_preset(note_table)
        if rule_result is not None:
            return rule_result

        # ── 回退：LLM 分析 ──
        prompt = self._build_wide_table_prompt(note_table, template_hint)
        messages = [
            {"role": "system", "content": "你是一个专业的审计表格结构分析助手。请分析宽表的横向公式结构，返回 JSON 格式结果。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response_text = ""
            async for chunk in openai_service.stream_chat_completion(messages, temperature=0.2):
                if isinstance(chunk, dict) and "content" in chunk:
                    response_text += chunk["content"]
                elif isinstance(chunk, str):
                    response_text += chunk

            result = self._parse_wide_table_response(response_text)
            if result is not None:
                return result
        except Exception as e:
            logger.warning("宽表公式 LLM 分析失败: %s", e)

        # ── 最终降级：尝试从表头关键词构建基础 movement 公式 ──
        return self._try_build_basic_movement_from_headers(note_table)

    def _build_wide_table_prompt(self, note_table: NoteTable, template_hint: Optional[str] = None) -> str:
        """构建宽表公式分析的 LLM prompt。

        如果匹配到预设模板，将预设作为强参考传给 LLM，LLM 只需确认/微调列映射。
        """
        table_text = f"表格标题：{note_table.section_title}\n"
        table_text += f"科目名称：{note_table.account_name}\n\n"

        if note_table.headers:
            table_text += f"表头（共{len(note_table.headers)}列）：\n"
            for i, h in enumerate(note_table.headers):
                table_text += f"  列{i}: {h}\n"

        # 显示原始多行表头（如果有）
        if note_table.header_rows and len(note_table.header_rows) > 1:
            table_text += "\n原始多行表头：\n"
            for ri, row in enumerate(note_table.header_rows):
                table_text += f"  表头行{ri}: {' | '.join(str(v) if v else '' for v in row)}\n"

        table_text += "\n数据行（前20行）：\n"
        for i, row in enumerate(note_table.rows[:20]):
            table_text += f"  行{i}: {' | '.join(str(v) if v else '' for v in row)}\n"

        context = ""
        if template_hint:
            context = f"\n【模板参考】\n{template_hint}\n"

        # ── 预设模板匹配 ──
        # 仅当表格不是 category_sum 布局时才提供 movement 预设提示
        preset = self._find_preset_for_note(note_table)
        preset_block = ""
        if preset:
            headers_list = [str(h or "") for h in note_table.headers] if note_table.headers else []
            is_cat_sum = self._try_build_category_sum_from_headers(note_table, headers_list) is not None
            if not is_cat_sum:
                preset_block = f"""
【预设公式模板】该表格匹配到标准模板"{preset['name']}"，标准列结构如下：
"""
                for tc in preset["template_columns"]:
                    preset_block += f"  - {tc['name']}: role={tc['role']}, sign={tc.get('sign')}\n"
                preset_block += f"标准公式: {preset['formula']}\n"
                preset_block += """
请以此预设为基础，将实际表格的列与预设列进行对应。
注意：实际表格可能比预设多列或少列，也可能列名略有不同，请根据实际表头灵活调整。
如果实际表格有预设中没有的列，请根据列名语义判断其 role 和 sign。
如果实际表格缺少预设中的某些列，直接跳过即可。
"""
                # 多段表格提示
                if preset.get("multi_section"):
                    preset_block += """
【多段表格注意】该表格可能是多段变动表（如固定资产：一、账面原值 → 二、累计折旧 → 三、减值准备 → 四、账面价值）。
每个段落都有相同的列结构，横向公式在每个段落内独立成立。
段标题行（如"一、账面原值"）不参与公式校验。
"账面净值"/"账面价值"段的行不适用变动公式（其值由纵向计算得出：原值-折旧-减值=账面价值）。
"""

        prompt = f"""请分析以下审计附注宽表的横向公式结构。

{table_text}
{context}
{preset_block}
你的任务是识别每一列的语义角色和在横向公式中的符号（正/负），以便后续程序逐行验证横向公式是否成立。

宽表有两种常见格式，请先判断属于哪种：

【格式A：变动公式型（国企版常见）】
列为：项目 | 期初余额 | 本期增加 | 本期减少 | 期末余额
行为各资产类别（如房屋建筑物、机器设备等）
横向公式：期初 + 各增加项 - 各减少项 = 期末

【格式B：分类合计型（上市版常见）】
列为：项目 | 房屋及建筑物 | 机器设备 | 运输设备 | ... | 合计
行为变动项目（如期初余额、本期增加、本期减少、期末余额等）
横向公式：各分类列之和 = 合计列
特征：表头列名是资产分类名称（如"房屋及建筑物"、"机器设备"等），最后一列为"合计"

注意：
1. 你只需要识别结构，不需要做任何数值计算
2. 有些列不参与公式（如百分比列、标签列、减值准备期初/期末等独立列）
3. 减值准备列如果独立于账面价值公式，应标记为 skip
4. "利息资本化率%"等百分比列应标记为 skip
5. "投资成本"列通常是 skip（不参与变动公式）

请返回以下 JSON 结构（不要包含其他文字）：

如果是格式A（变动公式型）：
{{
  "formula_type": "movement",
  "columns": [
    {{"col_index": 0, "role": "label", "sign": null, "name": "项目名称"}},
    {{"col_index": 1, "role": "opening", "sign": "+", "name": "期初余额"}},
    {{"col_index": 2, "role": "movement", "sign": "+", "name": "本期增加"}},
    {{"col_index": 3, "role": "movement", "sign": "-", "name": "本期减少"}},
    {{"col_index": 4, "role": "closing", "sign": "=", "name": "期末余额"}},
    {{"col_index": 5, "role": "skip", "sign": null, "name": "减值准备期末余额"}}
  ],
  "formula_description": "期初余额 + 本期增加 - 本期减少 = 期末余额",
  "data_row_start": 0
}}

如果是格式B（分类合计型）：
{{
  "formula_type": "category_sum",
  "columns": [
    {{"col_index": 0, "role": "label", "sign": null, "name": "项目"}},
    {{"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"}},
    {{"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"}},
    {{"col_index": 3, "role": "data", "sign": "+", "name": "运输设备"}},
    {{"col_index": 4, "role": "total", "sign": "=", "name": "合计"}}
  ],
  "formula_description": "房屋及建筑物 + 机器设备 + 运输设备 = 合计",
  "data_row_start": 0
}}

role 取值说明：
- "label": 标签/名称列，不参与公式
- "opening": 期初余额（格式A公式起点，sign 为 "+"）
- "closing": 期末余额（格式A公式结果，sign 为 "="）
- "movement": 变动列（格式A，sign 为 "+" 表示增加项，"-" 表示减少项）
- "data": 分类数据列（格式B，sign 为 "+"，参与求和）
- "total": 合计列（格式B，sign 为 "="，等于各 data 列之和）
- "skip": 不参与横向公式的列（百分比、减值准备独立列、投资成本等）

formula_type 取值说明：
- "movement": 变动公式型（期初+变动=期末）
- "category_sum": 分类合计型（各分类列之和=合计列）

data_row_start: 第一个数据行的索引（跳过表头行）"""

        return prompt

    def _parse_wide_table_response(self, response_text: str) -> Optional[Dict]:
        """解析宽表公式 LLM 返回的 JSON。"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if not json_match:
                logger.warning("宽表公式 LLM 返回中未找到 JSON")
                return None
            data = json.loads(json_match.group())
            if "columns" not in data:
                logger.warning("宽表公式 LLM 返回缺少 columns 字段")
                return None
            # 验证至少有 opening 和 closing
            roles = [c.get("role") for c in data["columns"]]
            if "opening" not in roles or "closing" not in roles:
                logger.warning("宽表公式 LLM 返回缺少 opening 或 closing 列")
                return None
            return data
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("解析宽表公式 LLM 返回失败: %s", e)
            return None

    @classmethod
    def _try_build_basic_movement_from_headers(cls, note_table: NoteTable) -> Optional[Dict]:
        """LLM 失败时的最终降级：仅通过表头关键词构建基础 movement 公式。

        只匹配 opening/closing 列和明确的增加/减少列，
        无法确定语义的列标记为 skip。比 LLM 分析粗糙，但能覆盖基本校验。
        """
        if not note_table.headers or len(note_table.headers) < 4:
            return None

        headers = [str(h or "") for h in note_table.headers]
        columns: List[Dict] = []
        opening_idx = None
        closing_idx = None

        # 第0列为 label
        columns.append({"col_index": 0, "role": "label", "sign": None, "name": headers[0]})

        _increase_kw = ["增加", "转入", "计提", "追加"]
        _decrease_kw = ["减少", "转出", "摊销", "折旧", "处置", "转回", "转销", "核销"]
        _skip_kw = ["比例", "%", "比率", "占比", "投资成本", "利息资本化"]

        for ci in range(1, len(headers)):
            h = headers[ci].replace(" ", "").replace("\u3000", "")

            # 跳过百分比等非数值列
            if any(kw in h for kw in _skip_kw):
                columns.append({"col_index": ci, "role": "skip", "sign": None, "name": headers[ci]})
                continue

            # opening
            if opening_idx is None and any(k in h for k in ["期初", "年初"]):
                if "减值" not in h:
                    opening_idx = ci
                    columns.append({"col_index": ci, "role": "opening", "sign": "+", "name": headers[ci]})
                    continue

            # closing
            if closing_idx is None and any(k in h for k in ["期末", "年末"]):
                if "减值" not in h:
                    closing_idx = ci
                    columns.append({"col_index": ci, "role": "closing", "sign": "=", "name": headers[ci]})
                    continue

            # movement: increase
            if any(kw in h for kw in _increase_kw):
                columns.append({"col_index": ci, "role": "movement", "sign": "+", "name": headers[ci]})
                continue

            # movement: decrease
            if any(kw in h for kw in _decrease_kw):
                columns.append({"col_index": ci, "role": "movement", "sign": "-", "name": headers[ci]})
                continue

            # 无法确定语义 → skip
            columns.append({"col_index": ci, "role": "skip", "sign": None, "name": headers[ci]})

        if opening_idx is None or closing_idx is None:
            return None

        # 至少需要一个 movement 列
        has_movement = any(c["role"] == "movement" for c in columns)
        if not has_movement:
            return None

        columns.sort(key=lambda c: c["col_index"])
        data_row_start = cls._detect_data_row_start(note_table)

        # 检测是否为多段表格
        acct = note_table.account_name or ""
        is_multi = any(kw in acct for kw in [
            "固定资产", "无形资产", "使用权资产", "投资性房地产",
            "生产性生物资产", "油气资产",
        ])

        logger.info("宽表降级构建：%s，%d 列（%d movement），multi_section=%s",
                     note_table.section_title, len(columns),
                     sum(1 for c in columns if c["role"] == "movement"), is_multi)

        return {
            "formula_type": "movement",
            "columns": columns,
            "formula_description": "（降级构建：基于表头关键词）",
            "data_row_start": data_row_start,
            "multi_section": is_multi,
        }

    # ─── LLM 分析 ───

    async def _analyze_with_llm(
        self, note_table: NoteTable, openai_service: OpenAIService,
        template_hint: Optional[str] = None,
        statement_amount_hint: Optional[str] = None,
    ) -> Optional[TableStructure]:
        """调用 LLM 分析表格结构。"""
        prompt = self._build_llm_prompt(note_table, template_hint=template_hint, statement_amount_hint=statement_amount_hint)

        messages = [
            {"role": "system", "content": "你是一个专业的审计表格结构分析助手。请分析附注表格的语义结构，返回 JSON 格式结果。"},
            {"role": "user", "content": prompt},
        ]

        response_text = ""
        async for chunk in openai_service.stream_chat_completion(messages):
            if isinstance(chunk, dict) and "content" in chunk:
                response_text += chunk["content"]
            elif isinstance(chunk, str):
                response_text += chunk

        # 解析 LLM 返回的 JSON
        structure = self._parse_llm_response(note_table.id, response_text)
        return structure

    def _build_llm_prompt(self, note_table: NoteTable, template_hint: Optional[str] = None, statement_amount_hint: Optional[str] = None) -> str:
        """构建 LLM 分析 prompt。

        LLM 只负责结构识别（行角色、列语义、合计行定位），不做数值计算。
        数值校验由本地 ReconciliationEngine 完成。
        """
        table_text = f"表格标题：{note_table.section_title}\n"
        table_text += f"科目名称：{note_table.account_name}\n\n"

        if note_table.headers:
            table_text += f"表头：{' | '.join(str(h) for h in note_table.headers)}\n"

        table_text += "数据行：\n"
        for i, row in enumerate(note_table.rows[:50]):  # 限制行数
            table_text += f"  行{i}: {' | '.join(str(v) if v else '' for v in row)}\n"

        # ── 构建上下文区块 ──
        context_block = ""
        if template_hint:
            context_block += f"""
【模板参考】以下是该科目在标准审计附注模板中的表格格式和披露要求：
{template_hint}

请对照模板理解该表格的类型和结构：
- 余额对照表（只有"期末余额 | 上年年末余额"）：合计行的期末/期初列直接对应报表金额
- 变动情况表（含"期初余额 | 本期增加 | 本期减少 | 期末余额"）：只有"期末余额"列的合计行才对应报表金额
- 含减值准备的表格（"账面余额 | 减值准备/坏账准备 | 账面价值"）：报表金额对应"账面价值"列（= 账面余额 - 减值准备）
- 含"比例(%)"或"预期信用损失率(%)"的列：semantic 应设为 other，不是金额列
"""
        if statement_amount_hint:
            context_block += f"""
【报表金额】{statement_amount_hint}
请用此金额验证你识别的 closing_balance_cell 和 opening_balance_cell 是否正确：
- 如果该表格是变动情况表，closing_balance_cell 应指向"期末余额"列而非"本期增加"列
- 如果该表格含"账面价值"列，closing_balance_cell 应指向"账面价值"列的合计行
- 如果该表格不含与报表直接对应的余额，closing_balance_cell 和 opening_balance_cell 应设为 null
"""

        # ── 其中项结构识别指引 ──
        sub_item_guide = """
【其中项识别规则】请特别注意以下嵌套结构：

1. "其中："标记行：以"其中："或"其中:"开头的行是子项标记，其后续行是该标记行上方最近 data 行的明细
   - 例如："社会保险费"行后面跟"其中：1.医疗保险费"，则医疗保险费是社会保险费的 sub_item
   - "其中："行本身也是 sub_item，parent_row_index 指向上方最近的 data 行

2. 编号子项：如果"其中："行带编号（如"其中：1.医疗保险费"），后续行必须也带编号才算 sub_item
   - "2.工伤保险费"是 sub_item，但"住房公积金"不是（它是新的顶层 data 行）

3. 坏账准备分类表（应收票据/应收账款/其他应收款/合同资产常见）：
   - "按单项计提坏账准备"和"按组合计提坏账准备"是 data 行
   - 它们各自下面的"其中："及后续行是 sub_item
   - 合计行 = 按单项 + 按组合（不包含其中项）

4. 应付职工薪酬的短期薪酬明细表：
   - "工资、奖金"、"职工福利费"、"社会保险费"、"住房公积金"等是 data 行
   - "社会保险费"下的"其中：1.医疗保险费"、"2.工伤保险费"等是 sub_item
   - 合计行 = 所有 data 行之和（不包含 sub_item）

5. 判断 sub_item 区域结束的标志：
   - 遇到合计行（total/subtotal）
   - 遇到新的"其中："标记行（属于另一个 data 行）
   - 遇到明显是新顶层项目的行（如编号子项区域后出现非编号行）
"""

        prompt = f"""请分析以下附注表格的语义结构，返回 JSON 格式。
注意：你只需要识别结构（行角色、列语义、合计行位置），不需要做任何数值计算。

{table_text}
{context_block}
{sub_item_guide}
请返回以下 JSON 结构（不要包含其他文字）：
{{
  "rows": [
    {{"row_index": 0, "role": "data|total|subtotal|sub_item|header", "parent_row_index": null, "indent_level": 0, "label": "行标签", "sign": 1}}
  ],
  "columns": [
    {{"col_index": 0, "semantic": "label|opening_balance|closing_balance|current_increase|current_decrease|prior_period|current_period|book_value|total|other", "period": null}}
  ],
  "has_balance_formula": true/false,
  "total_row_indices": [行索引],
  "subtotal_row_indices": [行索引],
  "closing_balance_cell": "RxCy 或 null",
  "opening_balance_cell": "RxCy 或 null"
}}

结构识别规则：
- role 取值：data（普通数据行）、total（合计行）、subtotal（小计行）、sub_item（其中项明细）、header（表头行）
- sub_item 的 parent_row_index 必须指向其所属主项行的索引（不是合计行）
- sign 取值：1（默认，加法行）或 -1（减法行，如"减：未确认融资费用"、"减：坏账准备"等以"减："开头的行）
- 如果表格含"期初+增加-减少=期末"结构，has_balance_formula 为 true
- closing_balance_cell 和 opening_balance_cell 用 RxCy 格式（x=行索引, y=列索引）
- 变动情况表中，closing_balance_cell 应指向"期末余额"列的合计行
- 不含可与报表直接比对的余额合计的表格，closing_balance_cell 和 opening_balance_cell 设为 null
- 百分比/比例/预期信用损失率列的 semantic 应设为 other"""

        return prompt

    def _parse_llm_response(
        self, note_table_id: str, response_text: str
    ) -> Optional[TableStructure]:
        """解析 LLM 返回的 JSON 结构。"""
        try:
            # 提取 JSON 块
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if not json_match:
                logger.warning("LLM 返回中未找到 JSON 结构")
                return None

            data = json.loads(json_match.group())

            # 校验必要字段
            if "rows" not in data or "columns" not in data:
                logger.warning("LLM 返回的 JSON 缺少必要字段")
                return None

            rows = [
                TableStructureRow(
                    row_index=r.get("row_index", i),
                    role=r.get("role", "data"),
                    parent_row_index=r.get("parent_row_index"),
                    indent_level=r.get("indent_level", 0),
                    label=r.get("label", ""),
                    sign=r.get("sign", 1),
                )
                for i, r in enumerate(data.get("rows", []))
            ]

            columns = [
                TableStructureColumn(
                    col_index=c.get("col_index", i),
                    semantic=c.get("semantic", "other"),
                    period=c.get("period"),
                )
                for i, c in enumerate(data.get("columns", []))
            ]

            return TableStructure(
                note_table_id=note_table_id,
                rows=rows,
                columns=columns,
                has_balance_formula=data.get("has_balance_formula", False),
                total_row_indices=data.get("total_row_indices", []),
                subtotal_row_indices=data.get("subtotal_row_indices", []),
                closing_balance_cell=data.get("closing_balance_cell"),
                opening_balance_cell=data.get("opening_balance_cell"),
                structure_confidence="high",
                raw_llm_response=response_text,
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("解析 LLM 返回的 JSON 失败: %s", e)
            return None

    # ─── 规则识别（降级策略） ───

    def _analyze_with_rules(self, note_table: NoteTable) -> TableStructure:
        """基于关键词的规则识别（LLM 失败时的降级策略）。

        两遍扫描：
        1. 第一遍：标记合计行、其中行，其余暂标为 data
        2. 第二遍：对每个"其中"行，将其后续行（到下一个 data/total/subtotal 为止）标为 sub_item
        """
        rows: List[TableStructureRow] = []
        total_row_indices: List[int] = []
        subtotal_row_indices: List[int] = []

        # ── 第一遍：识别合计行和"其中"标记行 ──
        for i, row in enumerate(note_table.rows):
            label = str(row[0]).strip() if row and row[0] else ""
            norm_label = label.replace(" ", "").replace("\u3000", "")
            role = "data"
            parent_row_index = None
            indent_level = 0
            sign = 1

            # 检测"减："前缀 → 纵向加总时应减去
            if norm_label.startswith("减：") or norm_label.startswith("减:"):
                sign = -1

            if self._is_total_row(label):
                if any(kw in label for kw in self.SUBTOTAL_KEYWORDS):
                    role = "subtotal"
                    subtotal_row_indices.append(i)
                else:
                    role = "total"
                    total_row_indices.append(i)
            elif any(label.startswith(kw) for kw in self.SUB_ITEM_KEYWORDS):
                role = "sub_item_header"  # 临时标记，第二遍处理
                indent_level = 1

            rows.append(TableStructureRow(
                row_index=i, role=role,
                parent_row_index=parent_row_index,
                indent_level=indent_level, label=label,
                sign=sign,
            ))

        # ── 第二遍：处理"其中"区域，将明细行标为 sub_item ──
        # 找到每个 sub_item_header 前面最近的 data 行作为 parent
        i = 0
        while i < len(rows):
            if rows[i].role == "sub_item_header":
                # 找 parent：往前找最近的 data 行
                parent_idx = None
                for j in range(i - 1, -1, -1):
                    if rows[j].role == "data":
                        parent_idx = j
                        break

                # 标记"其中"行本身
                rows[i].role = "sub_item"
                rows[i].parent_row_index = parent_idx

                # 检测"其中"行是否带编号（如"其中：1. 医疗保险费"），
                # 如果带编号，后续行必须也带编号才算 sub_item
                header_label = rows[i].label
                _sub_header_text = re.sub(r'^其中[：:]?\s*', '', header_label)
                _header_is_numbered = bool(re.match(
                    r'^[\d①②③④⑤⑥⑦⑧⑨⑩⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽㈠㈡㈢㈣㈤]', _sub_header_text
                ))

                # 向后扫描明细行，直到遇到 data/total/subtotal/sub_item_header
                k = i + 1
                while k < len(rows):
                    if rows[k].role in ("total", "subtotal", "sub_item_header"):
                        break
                    if rows[k].role == "data" and rows[k].label:
                        # 检查后面是否紧跟"其中"行 → 说明这是新的顶层 data，不是明细
                        next_is_sub_header = False
                        for m in range(k + 1, len(rows)):
                            if rows[m].label:  # 找到下一个有内容的行
                                next_is_sub_header = rows[m].role == "sub_item_header"
                                break
                        if next_is_sub_header:
                            break  # 这是新的顶层 data 行，结束当前其中区域

                        # 如果"其中"行带编号，后续行也必须带编号才算 sub_item
                        # 否则视为新的顶层 data 行（如"住房公积金"不是"社会保险费"的子项）
                        if _header_is_numbered:
                            row_label = rows[k].label.strip()
                            is_numbered = bool(re.match(
                                r'^[\d①②③④⑤⑥⑦⑧⑨⑩⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽㈠㈡㈢㈣㈤]', row_label
                            ))
                            if not is_numbered:
                                break  # 非编号行，结束当前其中区域

                        # 特殊规则：社会保险费的"其中"子项遇到"住房公积金"等独立科目时截断
                        if parent_idx is not None:
                            parent_norm = rows[parent_idx].label.replace(" ", "").replace("\u3000", "")
                            row_norm = rows[k].label.strip().replace(" ", "").replace("\u3000", "")
                            if "社会保险" in parent_norm and any(
                                kw in row_norm for kw in self._SOCIAL_INSURANCE_SUB_ITEM_CUTOFF
                            ):
                                break

                        # 标记为 sub_item
                        rows[k].role = "sub_item"
                        rows[k].parent_row_index = parent_idx
                        rows[k].indent_level = 1
                    k += 1
                i = k  # 跳过已处理的明细行
            else:
                i += 1

        # ── 更新 current_parent_idx 用于后续（兼容性） ──

        # 识别列语义
        columns = self._identify_columns_by_rules(note_table.headers)

        # 检测余额变动结构
        has_balance_formula = self._detect_balance_formula(note_table.headers)

        # ── 多分组表格检测：如果同一语义出现多次（如两个 opening_balance 列），
        # 说明表格是并列分组结构（如"跌价准备 | 合同履约成本减值准备"），
        # 简单的 期初+增加-减少=期末 公式不适用于整行 ──
        _sem_counts: Dict[str, int] = {}
        for col in columns:
            if col.semantic not in ("label", "other"):
                _sem_counts[col.semantic] = _sem_counts.get(col.semantic, 0) + 1
        _has_dup_semantic = any(v > 1 for v in _sem_counts.values())
        if _has_dup_semantic:
            has_balance_formula = False

        # ── 按 account_name 关键词强制禁用余额变动公式 ──
        # 某些表格（如"开发支出"）含并列子分类列，表头合并后不一定产生重复语义，
        # 但整行公式仍不适用
        acct = note_table.account_name or ""
        if has_balance_formula and any(kw in acct for kw in self.MULTI_GROUP_ACCOUNT_KEYWORDS):
            has_balance_formula = False

        # 定位合计行的期末/期初单元格
        closing_cell = None
        opening_cell = None

        # 确定参考行：优先用合计行，若无合计行但只有一行数据，则用该数据行
        ref_row = None
        if total_row_indices:
            ref_row = total_row_indices[-1]
        else:
            data_rows = [r for r in rows if r.role == "data" and r.label]
            if len(data_rows) == 1:
                ref_row = data_rows[0].row_index

        if ref_row is not None:
            # 优先使用"账面价值"列作为期末余额（净额 = 账面余额 - 减值准备，
            # 与资产负债表金额一致）
            for col in columns:
                if col.semantic == "book_value" and closing_cell is None:
                    closing_cell = f"R{ref_row}C{col.col_index}"

            # 其次查找 closing_balance / opening_balance 列
            # 多分组表格时，重复的语义列不可靠，只取唯一的语义列
            if closing_cell is None:
                for col in columns:
                    if col.semantic == "closing_balance" and closing_cell is None:
                        if _sem_counts.get("closing_balance", 0) <= 1:
                            closing_cell = f"R{ref_row}C{col.col_index}"
            for col in columns:
                if col.semantic == "opening_balance" and opening_cell is None:
                    if _sem_counts.get("opening_balance", 0) <= 1:
                        opening_cell = f"R{ref_row}C{col.col_index}"
            # 回退：对于现金流量表附注等非余额表格，
            # "本期发生额"→current_period 可作为 closing_balance 的替代
            # "上期发生额"→prior_period 可作为 opening_balance 的替代
            if closing_cell is None:
                for col in columns:
                    if col.semantic == "current_period":
                        closing_cell = f"R{ref_row}C{col.col_index}"
                        break
            if opening_cell is None:
                for col in columns:
                    if col.semantic == "prior_period":
                        opening_cell = f"R{ref_row}C{col.col_index}"
                        break

        # 根据识别结果判断置信度
        semantic_cols = [c for c in columns if c.semantic != "other"]
        has_total = len(total_row_indices) > 0
        has_semantic_cols = len(semantic_cols) >= 2
        if has_total and has_semantic_cols:
            confidence = "high"
        elif has_total or has_semantic_cols or has_balance_formula:
            confidence = "medium"
        else:
            confidence = "low"

        return TableStructure(
            note_table_id=note_table.id,
            rows=rows,
            columns=columns,
            has_balance_formula=has_balance_formula,
            total_row_indices=total_row_indices,
            subtotal_row_indices=subtotal_row_indices,
            closing_balance_cell=closing_cell,
            opening_balance_cell=opening_cell,
            structure_confidence=confidence,
        )

    # 百分比/比例列关键词 — 这类列不参与金额校验
    PERCENTAGE_KEYWORDS = ["比例", "%", "比率", "占比", "百分比"]

    # "上年"前缀 → opening_balance（仅当表头含"余额"时，如"上年年末余额"）
    # 不匹配"上期发生额"、"上期金额"等期间金额类表头
    PRIOR_YEAR_BALANCE_KEYWORDS = ["上年年末余额", "上年末余额", "上年余额", "上期余额", "上年度余额"]

    def _identify_columns_by_rules(self, headers: List[str]) -> List[TableStructureColumn]:
        """基于关键词识别列语义。

        改进点：
        1. 百分比/比例列直接归为 other，不参与金额校验
        2. "上年年末余额"等含"上年"+"余额"的列归为 opening_balance
        3. 先尝试精确匹配 prior_period/current_period 关键词，再走通用匹配
        """
        columns: List[TableStructureColumn] = []

        for i, header in enumerate(headers):
            header_str = str(header).strip() if header else ""
            semantic = "other"

            # 规则 1：百分比/比例列 → other（最高优先级）
            if any(kw in header_str for kw in self.PERCENTAGE_KEYWORDS):
                columns.append(TableStructureColumn(col_index=i, semantic="other", period=None))
                continue

            # 规则 2："上年年末余额"等含"上年"+"余额"的列 → opening_balance
            if any(kw in header_str for kw in self.PRIOR_YEAR_BALANCE_KEYWORDS):
                semantic = "opening_balance"
            else:
                # 规则 3：通用关键词匹配
                for sem, keywords in self.COLUMN_KEYWORDS.items():
                    if any(kw in header_str for kw in keywords):
                        semantic = sem
                        break

            columns.append(TableStructureColumn(col_index=i, semantic=semantic, period=None))

        return columns

    def _detect_balance_formula(self, headers: List[str]) -> bool:
        """检测表头是否包含余额变动结构。"""
        header_text = " ".join(str(h) for h in headers if h)

        for indicator_group in self.BALANCE_FORMULA_INDICATORS:
            if all(kw in header_text for kw in indicator_group):
                return True
        return False

    @staticmethod
    def _fuzzy_match_score(name1: str, name2: str) -> float:
        """简单的模糊匹配评分。"""
        if not name1 or not name2:
            return 0.0
        # 计算共同字符比例
        set1 = set(name1)
        set2 = set(name2)
        intersection = set1 & set2
        union = set1 | set2
        if not union:
            return 0.0
        return len(intersection) / len(union)


# 模块级单例
table_structure_analyzer = TableStructureAnalyzer()
