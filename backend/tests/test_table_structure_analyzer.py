"""Table_Structure_Analyzer 单元测试（Task 3.7）。

覆盖：简单/复杂表格结构识别、余额变动结构、匹配关系分析、
LLM 失败回退、JSON 校验、confidence 标记、缓存。
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.audit_schemas import (
    MatchingAnalysis,
    NoteTable,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from app.services.table_structure_analyzer import TableStructureAnalyzer


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
        # 含合计行+语义列（期初余额、期末余额）→ high 置信度
        assert result.structure_confidence == "high"
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

    def test_subtraction_row_sign_detection(self):
        """规则识别：'减：'前缀行的 sign 应为 -1。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期末余额", "期初余额"],
            rows=[
                ["租赁付款额", 10000, 12000],
                ["减：未确认融资费用", 500, 600],
                ["减：重分类至一年内到期的非流动负债", 2000, 3000],
                ["租赁负债净额", 7500, 8400],
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        sign_map = {r.row_index: r.sign for r in result.rows}
        assert sign_map[0] == 1   # 租赁付款额
        assert sign_map[1] == -1  # 减：未确认融资费用
        assert sign_map[2] == -1  # 减：重分类至一年内到期的非流动负债
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
        # 规则识别对含合计行+语义列的表格应给出 high 置信度
        assert result.structure_confidence == "high"
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
        # 规则识别对含合计行+语义列的表格应给出 high 置信度
        assert result.structure_confidence == "high"
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
        # 规则识别对含合计行+语义列的表格应给出 high 置信度
        assert result.structure_confidence == "high"
        analyzer.clear_cache()

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


# ─── 列语义关键词回归测试（Task 6 修复） ───

class TestColumnKeywordRegression:
    """验证 COLUMN_KEYWORDS 修复后，常见表头格式都能正确识别。"""

    def test_short_increase_decrease_headers(self):
        """表头为"增加"/"减少"时应识别为 current_increase/current_decrease。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期初余额", "增加", "减少", "期末余额"],
            rows=[["固定资产", 1000, 200, 50, 1150], ["合计", 1000, 200, 50, 1150]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        col_map = {c.col_index: c.semantic for c in result.columns}
        assert col_map[2] == "current_increase", f"'增加'应为current_increase，实际{col_map[2]}"
        assert col_map[3] == "current_decrease", f"'减少'应为current_decrease，实际{col_map[3]}"
        analyzer.clear_cache()

    def test_full_increase_decrease_headers(self):
        """表头为"本期增加"/"本期减少"时应识别为 current_increase/current_decrease。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
            rows=[["固定资产", 1000, 200, 50, 1150], ["合计", 1000, 200, 50, 1150]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        col_map = {c.col_index: c.semantic for c in result.columns}
        assert col_map[2] == "current_increase", f"'本期增加'应为current_increase，实际{col_map[2]}"
        assert col_map[3] == "current_decrease", f"'本期减少'应为current_decrease，实际{col_map[3]}"
        analyzer.clear_cache()

    def test_current_period_prior_period(self):
        """表头为"本期发生额"/"上期发生额"时应识别为 current_period/prior_period。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "本期发生额", "上期发生额"],
            rows=[["收入", 500, 400], ["合计", 500, 400]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        col_map = {c.col_index: c.semantic for c in result.columns}
        assert col_map[1] == "current_period", f"'本期发生额'应为current_period，实际{col_map[1]}"
        assert col_map[2] == "prior_period", f"'上期发生额'应为prior_period，实际{col_map[2]}"
        analyzer.clear_cache()

    def test_current_amount_prior_amount(self):
        """表头为"本期金额"/"上期金额"时应识别为 current_period/prior_period。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "本期金额", "上期金额"],
            rows=[["费用", 300, 250], ["合计", 300, 250]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        col_map = {c.col_index: c.semantic for c in result.columns}
        assert col_map[1] == "current_period", f"'本期金额'应为current_period，实际{col_map[1]}"
        assert col_map[2] == "prior_period", f"'上期金额'应为prior_period，实际{col_map[2]}"
        analyzer.clear_cache()

    def test_percentage_column_excluded(self):
        """含"比例"的列应识别为 other，不参与金额校验。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期末余额", "比例(%)", "期初余额"],
            rows=[["A", 100, "50%", 80], ["合计", 100, "100%", 80]],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        col_map = {c.col_index: c.semantic for c in result.columns}
        assert col_map[2] == "other", f"'比例(%)'应为other，实际{col_map[2]}"
        analyzer.clear_cache()


# ─── 多分组表格（并列子表）───

class TestMultiGroupTable:
    """表格含并列分组（如跌价准备+合同履约成本减值准备）时，
    不应启用余额变动公式校验。"""

    def test_duplicate_opening_balance_disables_formula(self):
        """两个 opening_balance 列 → has_balance_formula 应为 False，
        opening_balance_cell 应为 None（无法确定哪个是总计）。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期初余额", "本期增加", "期初余额", "本期增加", "本期减少", "本期转回", "期末余额"],
            rows=[
                ["原材料", 4554.20, None, 1507335.68, None, None, None, 16140670.21],
                ["合计", 22285106.85, None, 11957176.87, None, 1664547.57, None, 28936716.40],
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        assert result.has_balance_formula is False, \
            "多分组表格不应启用余额变动公式校验"
        assert result.opening_balance_cell is None, \
            "多分组表格的 opening_balance_cell 应为 None"
        assert result.closing_balance_cell is not None, \
            "唯一的 closing_balance 列仍应正常定位"
        analyzer.clear_cache()

    def test_single_opening_balance_keeps_formula(self):
        """只有一个 opening_balance 列 → has_balance_formula 正常检测。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
            rows=[
                ["A", 100, 50, 20, 130],
                ["合计", 100, 50, 20, 130],
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        assert result.has_balance_formula is True, \
            "单分组表格应正常检测余额变动公式"
        analyzer.clear_cache()

class TestNumberedSubItemDetection:
    """短期薪酬等表格中，"其中：1. xxx"带编号的其中项，
    后续非编号行（如"住房公积金"）不应被误标为 sub_item。"""

    def test_numbered_sub_items_stop_at_non_numbered(self):
        """其中：1. 医疗保险费 后面的编号行是 sub_item，
        非编号行（住房公积金、工会经费）应为 data。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期末余额", "期初余额"],
            rows=[
                ["工资、奖金、津贴和补贴", 1000, 800],       # 0: data
                ["职工福利费", 200, 150],                     # 1: data
                ["社会保险费", 300, 250],                     # 2: data
                ["其中：1. 医疗保险费", 100, 80],             # 3: sub_item (parent=2)
                ["2. 工伤保险费", 50, 40],                    # 4: sub_item (parent=2)
                ["3. 生育保险费", 30, 20],                    # 5: sub_item (parent=2)
                ["4. 失业保险费", 20, 15],                    # 6: sub_item (parent=2)
                ["住房公积金", 400, 350],                     # 7: data (NOT sub_item!)
                ["工会经费", 50, 40],                         # 8: data (NOT sub_item!)
                ["合计", 2000, 1600],                         # 9: total
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        roles = {r.row_index: r.role for r in result.rows}
        parents = {r.row_index: r.parent_row_index for r in result.rows}

        # 编号行应为 sub_item
        assert roles[3] == "sub_item" and parents[3] == 2
        assert roles[4] == "sub_item" and parents[4] == 2
        assert roles[5] == "sub_item" and parents[5] == 2
        assert roles[6] == "sub_item" and parents[6] == 2

        # 非编号行应为 data
        assert roles[7] == "data", f"住房公积金应为data，实际{roles[7]}"
        assert roles[8] == "data", f"工会经费应为data，实际{roles[8]}"
        assert roles[9] == "total"
        analyzer.clear_cache()

    def test_non_numbered_sub_items_still_work(self):
        """不带编号的"其中："后续行仍正常标记为 sub_item。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期末余额"],
            rows=[
                ["按组合计提", 500],          # 0: data
                ["其中：", None],              # 1: sub_item_header
                ["账龄组合", 300],             # 2: sub_item (parent=0)
                ["关联方组合", 200],           # 3: sub_item (parent=0)
                ["合计", 500],                 # 4: total
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        roles = {r.row_index: r.role for r in result.rows}

        assert roles[2] == "sub_item"
        assert roles[3] == "sub_item"
        assert roles[4] == "total"
        analyzer.clear_cache()



class TestNumberedSubItemDetection:
    """短期薪酬等表格中，"其中：1. xxx"带编号的其中项，
    后续非编号行（如"住房公积金"）不应被误标为 sub_item。"""

    def test_numbered_sub_items_stop_at_non_numbered(self):
        """其中：1. 医疗保险费 后面的编号行是 sub_item，
        非编号行（住房公积金、工会经费）应为 data。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期末余额", "期初余额"],
            rows=[
                ["工资、奖金、津贴和补贴", 1000, 800],       # 0: data
                ["职工福利费", 200, 150],                     # 1: data
                ["社会保险费", 300, 250],                     # 2: data
                ["其中：1. 医疗保险费", 100, 80],             # 3: sub_item (parent=2)
                ["2. 工伤保险费", 50, 40],                    # 4: sub_item (parent=2)
                ["3. 生育保险费", 30, 20],                    # 5: sub_item (parent=2)
                ["4. 失业保险费", 20, 15],                    # 6: sub_item (parent=2)
                ["住房公积金", 400, 350],                     # 7: data (NOT sub_item!)
                ["工会经费", 50, 40],                         # 8: data (NOT sub_item!)
                ["合计", 2000, 1600],                         # 9: total
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        roles = {r.row_index: r.role for r in result.rows}
        parents = {r.row_index: r.parent_row_index for r in result.rows}

        # 编号行应为 sub_item
        assert roles[3] == "sub_item" and parents[3] == 2
        assert roles[4] == "sub_item" and parents[4] == 2
        assert roles[5] == "sub_item" and parents[5] == 2
        assert roles[6] == "sub_item" and parents[6] == 2

        # 非编号行应为 data
        assert roles[7] == "data", f"住房公积金应为data，实际{roles[7]}"
        assert roles[8] == "data", f"工会经费应为data，实际{roles[8]}"
        assert roles[9] == "total"
        analyzer.clear_cache()

    def test_non_numbered_sub_items_still_work(self):
        """不带编号的"其中："后续行仍正常标记为 sub_item。"""
        analyzer = TableStructureAnalyzer()
        nt = _make_note_table(
            headers=["项目", "期末余额"],
            rows=[
                ["按组合计提", 500],          # 0: data
                ["其中：", None],              # 1: sub_item_header
                ["账龄组合", 300],             # 2: sub_item (parent=0)
                ["关联方组合", 200],           # 3: sub_item (parent=0)
                ["合计", 500],                 # 4: total
            ],
        )
        result = _run(analyzer.analyze_table_structure(nt))
        roles = {r.row_index: r.role for r in result.rows}

        assert roles[2] == "sub_item"
        assert roles[3] == "sub_item"
        assert roles[4] == "total"
        analyzer.clear_cache()
