"""表格结构识别服务（LLM 辅助）。

分析附注表格的语义结构（合计行/其中项/列语义/余额变动结构），
输出结构化的 TableStructure 供 Reconciliation_Engine 使用。
LLM 调用失败时回退到基于关键词的规则识别。
"""
import json
import logging
import re
import uuid
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

    # 结构缓存
    _cache: Dict[str, TableStructure] = {}

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
        self._cache[note_table.id] = structure
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
    ) -> Optional[TableStructure]:
        """强制使用 LLM 重新分析表格结构（跳过缓存和置信度检查）。

        用于金额核对不一致时，对疑似识别错误的表格进行二次校验。
        如果 LLM 返回了不同的结构（closing_balance_cell 或 opening_balance_cell 变化），
        则更新缓存并返回新结构；否则返回 None 表示结构未变。

        Args:
            template_hint: 模板中该科目的表格格式参考（帮助 LLM 理解表格结构）
            statement_amount_hint: 报表金额提示（帮助 LLM 定位正确的余额单元格）
        """
        old_structure = self._cache.get(note_table.id)

        try:
            llm_structure = await self._analyze_with_llm(
                note_table, openai_service,
                template_hint=template_hint,
                statement_amount_hint=statement_amount_hint,
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
                    self._cache[note_table.id] = llm_structure
                    return llm_structure
                else:
                    logger.info("LLM 重新分析结果与规则一致，结构确认无误: %s", note_table.id)
                    return None
            else:
                # 没有旧结构，直接使用 LLM 结果
                self._cache[note_table.id] = llm_structure
                return llm_structure

        except Exception as e:
            logger.warning("LLM 重新分析失败 %s: %s", note_table.id, e)
            return None


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
    {{"row_index": 0, "role": "data|total|subtotal|sub_item|header", "parent_row_index": null, "indent_level": 0, "label": "行标签"}}
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
            role = "data"
            parent_row_index = None
            indent_level = 0

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
