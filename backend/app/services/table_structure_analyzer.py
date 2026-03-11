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
        "current_increase": ["本期增加", "增加", "本期发生", "借方发生额", "本年增加"],
        "current_decrease": ["本期减少", "减少", "本期转出", "贷方发生额", "本年减少"],
        "current_period": ["本期金额", "本期", "本年金额", "本年累计"],
        "prior_period": ["上期金额", "上期", "上年金额", "上年同期"],
        "label": ["项目", "科目", "类别", "名称", "内容"],
    }

    # 余额变动结构关键词组合
    BALANCE_FORMULA_INDICATORS = [
        ("期初", "增加", "减少", "期末"),
        ("年初", "增加", "减少", "年末"),
        ("期初余额", "本期增加", "本期减少", "期末余额"),
    ]

    # 结构缓存
    _cache: Dict[str, TableStructure] = {}

    # ─── Public API ───

    async def analyze_table_structure(
        self, note_table: NoteTable, openai_service: Optional[OpenAIService] = None
    ) -> TableStructure:
        """分析附注表格语义结构，返回 TableStructure。

        优先使用 LLM 分析，失败时回退到规则识别。
        结果缓存到内存避免重复调用。
        """
        # 检查缓存
        if note_table.id in self._cache:
            return self._cache[note_table.id]

        structure: Optional[TableStructure] = None

        # 尝试 LLM 分析
        if openai_service:
            try:
                structure = await self._analyze_with_llm(note_table, openai_service)
            except Exception as e:
                logger.warning("LLM 分析表格结构失败，回退到规则识别: %s", e)

        # LLM 失败或未提供 service，使用规则识别
        if structure is None:
            structure = self._analyze_with_rules(note_table)

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

    # ─── LLM 分析 ───

    async def _analyze_with_llm(
        self, note_table: NoteTable, openai_service: OpenAIService
    ) -> Optional[TableStructure]:
        """调用 LLM 分析表格结构。"""
        prompt = self._build_llm_prompt(note_table)

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

    def _build_llm_prompt(self, note_table: NoteTable) -> str:
        """构建 LLM 分析 prompt。"""
        table_text = f"表格标题：{note_table.section_title}\n"
        table_text += f"科目名称：{note_table.account_name}\n\n"

        if note_table.headers:
            table_text += f"表头：{' | '.join(str(h) for h in note_table.headers)}\n"

        table_text += "数据行：\n"
        for i, row in enumerate(note_table.rows[:50]):  # 限制行数
            table_text += f"  行{i}: {' | '.join(str(v) if v else '' for v in row)}\n"

        prompt = f"""请分析以下附注表格的语义结构，返回 JSON 格式：

{table_text}

请返回以下 JSON 结构（不要包含其他文字）：
{{
  "rows": [
    {{"row_index": 0, "role": "data|total|subtotal|sub_item|header", "parent_row_index": null, "indent_level": 0, "label": "行标签"}}
  ],
  "columns": [
    {{"col_index": 0, "semantic": "label|opening_balance|closing_balance|current_increase|current_decrease|prior_period|current_period|total|other", "period": null}}
  ],
  "has_balance_formula": true/false,
  "total_row_indices": [行索引],
  "subtotal_row_indices": [行索引],
  "closing_balance_cell": "合计行期末余额单元格位置（如 R5C3）或 null",
  "opening_balance_cell": "合计行期初余额单元格位置（如 R5C2）或 null"
}}

注意：
- role 取值：data（普通数据行）、total（合计行）、subtotal（小计行）、sub_item（其中项）、header（表头行）
- 其中项的 parent_row_index 指向其所属主项行的索引
- 如果表格含"期初+增加-减少=期末"结构，has_balance_formula 为 true
- closing_balance_cell 和 opening_balance_cell 用 RxCy 格式表示（x=行索引, y=列索引）"""

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
        """基于关键词的规则识别（LLM 失败时的降级策略）。"""
        rows: List[TableStructureRow] = []
        total_row_indices: List[int] = []
        subtotal_row_indices: List[int] = []
        current_parent_idx: Optional[int] = None

        for i, row in enumerate(note_table.rows):
            label = str(row[0]).strip() if row and row[0] else ""
            role = "data"
            parent_row_index = None
            indent_level = 0

            # 检测合计行
            if any(kw in label for kw in self.TOTAL_KEYWORDS):
                if any(kw in label for kw in self.SUBTOTAL_KEYWORDS):
                    role = "subtotal"
                    subtotal_row_indices.append(i)
                else:
                    role = "total"
                    total_row_indices.append(i)
            # 检测其中项
            elif any(label.startswith(kw) for kw in self.SUB_ITEM_KEYWORDS):
                role = "sub_item"
                parent_row_index = current_parent_idx
                indent_level = 1
            else:
                current_parent_idx = i

            rows.append(TableStructureRow(
                row_index=i,
                role=role,
                parent_row_index=parent_row_index,
                indent_level=indent_level,
                label=label,
            ))

        # 识别列语义
        columns = self._identify_columns_by_rules(note_table.headers)

        # 检测余额变动结构
        has_balance_formula = self._detect_balance_formula(note_table.headers)

        # 定位合计行的期末/期初单元格
        closing_cell = None
        opening_cell = None
        if total_row_indices:
            last_total = total_row_indices[-1]
            for col in columns:
                if col.semantic == "closing_balance":
                    closing_cell = f"R{last_total}C{col.col_index}"
                elif col.semantic == "opening_balance":
                    opening_cell = f"R{last_total}C{col.col_index}"

        return TableStructure(
            note_table_id=note_table.id,
            rows=rows,
            columns=columns,
            has_balance_formula=has_balance_formula,
            total_row_indices=total_row_indices,
            subtotal_row_indices=subtotal_row_indices,
            closing_balance_cell=closing_cell,
            opening_balance_cell=opening_cell,
            structure_confidence="low",
        )

    def _identify_columns_by_rules(self, headers: List[str]) -> List[TableStructureColumn]:
        """基于关键词识别列语义。"""
        columns: List[TableStructureColumn] = []

        for i, header in enumerate(headers):
            header_str = str(header).strip() if header else ""
            semantic = "other"

            for sem, keywords in self.COLUMN_KEYWORDS.items():
                if any(kw in header_str for kw in keywords):
                    semantic = sem
                    break

            columns.append(TableStructureColumn(
                col_index=i,
                semantic=semantic,
                period=None,
            ))

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
