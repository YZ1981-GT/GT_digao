"""Table_Structure_Analyzer 单元测试（Task 3.7）。

覆盖：简单/复杂表格结构识别、余额变动结构、匹配关系分析、
LLM 失败回退、JSON 校验、confidence 标记、缓存。
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.audit_schemas import (
    MatchingAnalysis,
    NoteTable,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from backend.app.services.table_structure_analyzer import TableStructureAnalyzer


# ─── helpers ───

def _run(coro):
    """同步运行异步协程。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_note_table(
    headers=None, rows=None, account_name="应收账款", section_title="应收账款附注",
):
    return NoteTable(
        id=str(uuid.uuid4()),
        account_name=account_name,
        section_title=section_title,
        headers=headers or ["项目", "期初余额", "期末余额"],
        rows=rows or [
            ["客户A", 100.0, 200.0],
            ["客户B", 150.0, 250.0],
            ["合计", 250.0, 450.0],
        ],
    )


def _make_statement_item(account_name="应收账款", opening=250.0, closing=450.0):
    return StatementItem(
        id=str(uuid.uuid4()),
        account_name=account_name,
        statement_type=StatementType.BALANCE_SHEET,
        sheet_name="资产负债表",
        opening_balance=opening,
        closing_balance=closing,
        row_index=5,
    )


# ─── 规则识别测试 ───

class TestRuleBasedAnalysis:
    """测试基于关键词的规则识别（降级策略）。"""

    def test_simple_total_row(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()
        result = _run(analyzer.analyze_table_structure(nt))
        assert isinstance(result, TableStructure)
        assert result.structure_confidence == "low"
        assert 2 in result.total_row_indices  # "合计" 在第3行(index=2)
        analyzer.clear_cache()

    def test_subtotal_detection(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(rows=[
            ["项目A", 100, 200],
            ["小计", 100, 200],
            ["项目B", 50, 80],
            ["合计", 150, 280],
        ])
        result = _run(analyzer.analyze_table_structure(nt))
        assert 1 in result.subtotal_row_indices
        assert 3 in result.total_row_indices
        analyzer.clear_cache()

    def test_sub_item_detection(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(rows=[
            ["应收账款", 100, 200],
            ["其中：客户A", 60, 120],
            ["其中：客户B", 40, 80],
            ["合计", 100, 200],
        ])
        result = _run(analyzer.analyze_table_structure(nt))
        sub_items = [r for r in result.rows if r.role == "sub_item"]
        assert len(sub_items) == 2
        assert sub_items[0].parent_row_index == 0
        assert sub_items[0].indent_level == 1
        analyzer.clear_cache()

    def test_column_semantic_identification(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额"])
        result = _run(analyzer.analyze_table_structure(nt))
        semantics = {c.semantic for c in result.columns}
        assert "label" in semantics
        assert "opening_balance" in semantics
        assert "closing_balance" in semantics
        assert "current_increase" in semantics
        assert "current_decrease" in semantics
        analyzer.clear_cache()

    def test_balance_formula_detection(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
            rows=[["固定资产", 1000, 200, 50, 1150], ["合计", 1000, 200, 50, 1150]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        assert result.has_balance_formula is True
        analyzer.clear_cache()

    def test_no_balance_formula(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "本期金额", "上期金额"],
            rows=[["收入", 500, 400], ["合计", 500, 400]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        assert result.has_balance_formula is False
        analyzer.clear_cache()

    def test_closing_opening_cell_location(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期初余额", "期末余额"],
            rows=[["A", 100, 200], ["合计", 100, 200]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        assert result.closing_balance_cell is not None
        assert result.opening_balance_cell is not None
        assert "R1" in result.closing_balance_cell  # total row index=1
        analyzer.clear_cache()

    def test_complex_table_irregular_total_names(self):
        """测试不规则合计行命名。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(rows=[
            ["项目A", 100, 200],
            ["项目B", 50, 80],
            ["合 计", 150, 280],  # 带空格的合计
        ])
        result = _run(analyzer.analyze_table_structure(nt))
        assert 2 in result.total_row_indices
        analyzer.clear_cache()


# ─── LLM 分析测试 ───

class TestLLMAnalysis:
    """测试 LLM 分析路径。"""

    def test_llm_success(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()

        llm_response = json.dumps({
            "rows": [
                {"row_index": 0, "role": "data", "label": "客户A"},
                {"row_index": 1, "role": "data", "label": "客户B"},
                {"row_index": 2, "role": "total", "label": "合计"},
            ],
            "columns": [
                {"col_index": 0, "semantic": "label"},
                {"col_index": 1, "semantic": "opening_balance"},
                {"col_index": 2, "semantic": "closing_balance"},
            ],
            "has_balance_formula": False,
            "total_row_indices": [2],
            "subtotal_row_indices": [],
            "closing_balance_cell": "R2C2",
            "opening_balance_cell": "R2C1",
        })

        mock_service = MagicMock()

        async def mock_stream(messages):
            yield llm_response

        mock_service.stream_chat_completion = mock_stream

        result = _run(analyzer.analyze_table_structure(nt, openai_service=mock_service))
        assert result.structure_confidence == "high"
        assert 2 in result.total_row_indices
        assert result.closing_balance_cell == "R2C2"
        analyzer.clear_cache()

    def test_llm_failure_fallback_to_rules(self):
        """LLM 调用失败时回退到规则识别。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()

        mock_service = MagicMock()

        async def mock_stream(messages):
            raise Exception("LLM API error")
            yield  # make it a generator

        mock_service.stream_chat_completion = mock_stream

        result = _run(analyzer.analyze_table_structure(nt, openai_service=mock_service))
        assert result.structure_confidence == "low"
        assert 2 in result.total_row_indices
        analyzer.clear_cache()

    def test_llm_invalid_json_fallback(self):
        """LLM 返回无效 JSON 时回退到规则识别。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()

        mock_service = MagicMock()

        async def mock_stream(messages):
            yield "这不是有效的JSON响应"

        mock_service.stream_chat_completion = mock_stream

        result = _run(analyzer.analyze_table_structure(nt, openai_service=mock_service))
        assert result.structure_confidence == "low"
        analyzer.clear_cache()

    def test_llm_missing_required_fields_fallback(self):
        """LLM 返回缺少必要字段的 JSON 时回退。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()

        mock_service = MagicMock()

        async def mock_stream(messages):
            yield json.dumps({"some_field": "value"})  # missing rows/columns

        mock_service.stream_chat_completion = mock_stream

        result = _run(analyzer.analyze_table_structure(nt, openai_service=mock_service))
        assert result.structure_confidence == "low"
        analyzer.clear_cache()


# ─── 缓存测试 ───

class TestCache:
    def test_cache_hit(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()
        r1 = _run(analyzer.analyze_table_structure(nt))
        r2 = _run(analyzer.analyze_table_structure(nt))
        assert r1 is r2  # same object from cache
        analyzer.clear_cache()

    def test_cache_clear(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()
        _run(analyzer.analyze_table_structure(nt))
        analyzer.clear_cache()
        assert nt.id not in analyzer._cache


# ─── 匹配关系分析测试 ───

class TestMatchingRelationship:
    def test_exact_name_match(self):
        analyzer = TableStructureAnalyzer()
        item = _make_statement_item("应收账款")
        nt = _make_note_table(account_name="应收账款")
        result = analyzer.analyze_matching_relationship(item, nt)
        assert isinstance(result, MatchingAnalysis)
        assert result.confidence == 1.0

    def test_partial_name_match(self):
        analyzer = TableStructureAnalyzer()
        item = _make_statement_item("应收账款")
        nt = _make_note_table(account_name="应收账款——账龄分析")
        result = analyzer.analyze_matching_relationship(item, nt)
        assert result.confidence >= 0.7

    def test_with_table_structure(self):
        analyzer = TableStructureAnalyzer()
        item = _make_statement_item("应收账款")
        nt = _make_note_table(account_name="应收账款")
        ts = TableStructure(
            note_table_id=nt.id,
            closing_balance_cell="R2C2",
            opening_balance_cell="R2C1",
        )
        result = analyzer.analyze_matching_relationship(item, nt, ts)
        assert result.matched_cell_closing == "R2C2"
        assert result.matched_cell_opening == "R2C1"

    def test_fuzzy_match_low_confidence(self):
        analyzer = TableStructureAnalyzer()
        item = _make_statement_item("固定资产")
        nt = _make_note_table(account_name="无形资产")
        result = analyzer.analyze_matching_relationship(item, nt)
        assert result.confidence < 0.7


# ─── Prompt 构建测试 ───

class TestPromptBuilding:
    def test_prompt_contains_table_info(self):
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table()
        prompt = analyzer._build_llm_prompt(nt)
        assert "应收账款" in prompt
        assert "期初余额" in prompt or "期末余额" in prompt
        assert "JSON" in prompt
