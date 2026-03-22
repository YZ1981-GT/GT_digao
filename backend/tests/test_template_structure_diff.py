# -*- coding: utf-8 -*-
"""Tests for template structure comparison feature."""
import sys
sys.path.insert(0, ".")

from app.services.report_review_engine import ReportReviewEngine
from app.models.audit_schemas import NoteTable


class TestExtractTemplateTables:
    """测试从模板 markdown 中提取表格 headers."""

    def test_simple_table(self):
        content = """
| 项目 | 期末余额 | 期初余额 |
| --- | --- | --- |
| 库存现金 |  |  |
| 银行存款 |  |  |
"""
        tables = ReportReviewEngine._extract_template_tables(content)
        assert len(tables) == 1
        assert tables[0] == ["项目", "期末余额", "期初余额"]

    def test_multiple_tables(self):
        content = """
### 货币资金

| 项目 | 期末余额 | 期初余额 |
| --- | --- | --- |
| 库存现金 |  |  |

### 受限制的货币资金

| 项目 | 期末余额 | 期初余额 |
| --- | --- | --- |
| 保证金 |  |  |
"""
        tables = ReportReviewEngine._extract_template_tables(content)
        assert len(tables) == 2

    def test_complex_headers_with_html(self):
        content = """
| 项  目 | 期初余额 | 本期<br/>增加 | 本期减少 | 期末余额 |
| --- | --- | --- | --- | --- |
| 合计 |  |  |  |  |
"""
        tables = ReportReviewEngine._extract_template_tables(content)
        assert len(tables) == 1
        assert "本期增加" in tables[0][2] or "本期" in tables[0][2]

    def test_no_tables(self):
        content = "这是一段纯文本，没有表格。"
        tables = ReportReviewEngine._extract_template_tables(content)
        assert len(tables) == 0

    def test_wide_table(self):
        content = """
| 项  目 | 期末数 |  |  | 期初数 |  |  |
| --- | --- | --- | --- | --- | --- | --- |
| 项  目 | 账面余额 | 坏账准备 | 账面价值 | 账面余额 | 坏账准备 | 账面价值 |
| 合计 |  |  |  |  |  |  |
"""
        tables = ReportReviewEngine._extract_template_tables(content)
        assert len(tables) >= 1


class TestCompareTableHeaders:
    """测试表格 headers 对比."""

    def test_exact_match_no_diff(self):
        note = NoteTable(
            id="t1", account_name="货币资金", section_title="货币资金",
            headers=["项目", "期末余额", "期初余额"],
            rows=[["库存现金", 100, 80]],
        )
        template_tables = [["项目", "期末余额", "期初余额"]]
        diff = ReportReviewEngine._compare_table_headers("货币资金", note, template_tables)
        assert diff is None

    def test_missing_column(self):
        note = NoteTable(
            id="t2", account_name="存货", section_title="存货分类",
            headers=["项目", "账面余额", "账面价值"],
            rows=[["原材料", 100, 90]],
        )
        template_tables = [["项目", "账面余额", "跌价准备", "账面价值"]]
        diff = ReportReviewEngine._compare_table_headers("存货", note, template_tables)
        # 3 actual vs 4 template, overlap = 3/4 = 0.75 < 0.8, should report diff
        assert diff is not None
        assert "跌价准备" in diff["missing_cols"]

    def test_extra_column(self):
        note = NoteTable(
            id="t3", account_name="固定资产", section_title="固定资产情况",
            headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额", "备注"],
            rows=[["房屋", 100, 20, 5, 115, ""]],
        )
        template_tables = [["项目", "期初余额", "本期增加", "本期减少", "期末余额"]]
        diff = ReportReviewEngine._compare_table_headers("固定资产", note, template_tables)
        assert diff is not None
        assert "备注" in diff["extra_cols"]

    def test_no_template_match(self):
        note = NoteTable(
            id="t4", account_name="特殊科目", section_title="特殊科目",
            headers=["A", "B", "C"],
            rows=[["x", 1, 2]],
        )
        template_tables = [["项目", "期末余额", "期初余额"]]
        diff = ReportReviewEngine._compare_table_headers("特殊科目", note, template_tables)
        # Very low overlap, should return None
        assert diff is None

    def test_fuzzy_match_headers(self):
        """模糊匹配：实际表头包含模板表头关键词."""
        note = NoteTable(
            id="t5", account_name="应收账款", section_title="应收账款",
            headers=["项  目", "期末余额", "期初余额"],
            rows=[["客户A", 100, 80]],
        )
        template_tables = [["项目", "期末余额", "期初余额"]]
        diff = ReportReviewEngine._compare_table_headers("应收账款", note, template_tables)
        # Should match despite extra spaces in "项  目"
        assert diff is None

    def test_best_match_selection(self):
        """多个模板表格时选择最匹配的."""
        note = NoteTable(
            id="t6", account_name="应收账款", section_title="坏账准备变动",
            headers=["类别", "期初数", "计提", "收回或转回", "核销", "期末数"],
            rows=[["单项", 100, 20, 5, 0, 115]],
        )
        template_tables = [
            ["项目", "期末余额", "期初余额"],  # 不匹配
            ["类别", "期初数", "计提", "收回或转回", "转销或核销", "期末数"],  # 匹配
        ]
        diff = ReportReviewEngine._compare_table_headers("应收账款", note, template_tables)
        # Should match the second template (high overlap)
        assert diff is None

    def test_too_few_headers_skipped(self):
        """表头少于2列时跳过."""
        note = NoteTable(
            id="t7", account_name="测试", section_title="测试",
            headers=["项目"],
            rows=[["x"]],
        )
        template_tables = [["项目", "金额"]]
        diff = ReportReviewEngine._compare_table_headers("测试", note, template_tables)
        assert diff is None

    def test_diff_output_structure(self):
        """验证差异输出的数据结构."""
        note = NoteTable(
            id="t8", account_name="在建工程", section_title="在建工程变动",
            headers=["项目", "期初余额", "本期增加", "期末余额"],
            rows=[["工程A", 100, 50, 150]],
        )
        template_tables = [["项目", "期初余额", "本期增加", "本期减少", "期末余额"]]
        diff = ReportReviewEngine._compare_table_headers("在建工程", note, template_tables)
        assert diff is not None
        assert diff["account_name"] == "在建工程"
        assert diff["note_id"] == "t8"
        assert "actual_col_count" in diff
        assert "template_col_count" in diff
        assert "missing_cols" in diff
        assert "extra_cols" in diff
        assert "description" in diff
        assert "本期减少" in diff["missing_cols"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
