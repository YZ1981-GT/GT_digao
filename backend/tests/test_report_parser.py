"""Report_Parser 单元测试。

覆盖：多 Sheet Excel 解析、Sheet 类型自动识别、科目提取（含其中项）、
Word 附注表格提取、文件分类、错误文件处理、金额解析警告。
"""
import pytest
from unittest.mock import MagicMock

from app.models.audit_schemas import (
    CellData,
    ExcelParseResult,
    NoteTable,
    ReportFileType,
    ReportSheetData,
    SheetData,
    StatementType,
    WordParseResult,
)
from app.services.report_parser import ReportParser


@pytest.fixture
def parser():
    return ReportParser()


# ─── 文件分类测试 ───

class TestClassifyReportFile:
    def test_classify_notes(self, parser):
        result = parser.classify_report_file("附注.docx", "财务报表附注内容")
        assert result == ReportFileType.NOTES_TO_STATEMENTS

    def test_classify_audit_report_body(self, parser):
        result = parser.classify_report_file("审计报告.docx", "独立审计报告正文")
        assert result == ReportFileType.AUDIT_REPORT_BODY

    def test_classify_financial_statement_excel(self, parser):
        result = parser.classify_report_file("报表.xlsx", "一些数据内容")
        assert result == ReportFileType.FINANCIAL_STATEMENT

    def test_classify_default_word(self, parser):
        """Word 文件无明确关键词时默认归类为附注"""
        result = parser.classify_report_file("文件.docx", "一些普通内容")
        assert result == ReportFileType.NOTES_TO_STATEMENTS

    def test_classify_by_content(self, parser):
        result = parser.classify_report_file("file.docx", "本文件包含审计报告正文")
        assert result == ReportFileType.AUDIT_REPORT_BODY


# ─── Sheet 类型识别测试 ───

class TestIdentifyStatementType:
    def test_balance_sheet_by_name(self, parser):
        result = parser._identify_statement_type("资产负债表", [])
        assert result == StatementType.BALANCE_SHEET

    def test_income_statement_by_name(self, parser):
        result = parser._identify_statement_type("利润表", [])
        assert result == StatementType.INCOME_STATEMENT

    def test_cash_flow_by_name(self, parser):
        result = parser._identify_statement_type("现金流量表", [])
        assert result == StatementType.CASH_FLOW

    def test_equity_change_by_name(self, parser):
        result = parser._identify_statement_type("所有者权益变动表", [])
        assert result == StatementType.EQUITY_CHANGE

    def test_default_type(self, parser):
        result = parser._identify_statement_type("Sheet1", [])
        assert result is None  # 无法识别的 Sheet 应跳过

    def test_skip_auxiliary_sheet(self, parser):
        """辅助性 Sheet（横纵加、校验等）应返回 None。"""
        for name in ["横纵加", "校验表", "辅助计算", "勾稽"]:
            result = parser._identify_statement_type(name, [])
            assert result is None, f"Sheet '{name}' should be skipped"

    def test_skip_auxiliary_with_statement_keyword(self, parser):
        """名称同时含报表关键词和辅助关键词时，辅助优先跳过。"""
        # 国企版常见：利润及利润分配表增加额、资产负债表增加额
        for name in ["利润及利润分配表增加额", "资产负债表增加额", "现金流量表调整"]:
            result = parser._identify_statement_type(name, [])
            assert result is None, f"Sheet '{name}' should be skipped (auxiliary keyword takes priority)"

    def test_skip_unrecognized_sheet(self, parser):
        """名称不含报表关键词的 Sheet 一律跳过，不管内容。"""
        # 即使内容含"资产负债表"，名称不匹配也应跳过
        cells = [
            CellData(row=1, col=1, value="资产负债表"),
            CellData(row=2, col=1, value="货币资金"),
        ]
        for name in ["增加额", "Sheet1", "汇总", "数据"]:
            result = parser._identify_statement_type(name, cells)
            assert result is None, f"Sheet '{name}' should be skipped even with BS content"

    def test_formal_sheet_by_name(self, parser):
        """正式报表 Sheet 通过名称关键词识别。"""
        assert parser._identify_statement_type("1,2-资产负债表(企财01表)", []) == StatementType.BALANCE_SHEET
        assert parser._identify_statement_type("利润表(企财02表)", []) == StatementType.INCOME_STATEMENT
        assert parser._identify_statement_type("现金流量表", []) == StatementType.CASH_FLOW
        assert parser._identify_statement_type("所有者权益变动表", []) == StatementType.EQUITY_CHANGE

    def test_identify_by_content_ignored(self, parser):
        """内容检测已移除，名称不匹配时即使内容含关键词也应跳过。"""
        cells = [
            CellData(row=1, col=1, value="现金流量表"),
            CellData(row=2, col=1, value="经营活动"),
        ]
        result = parser._identify_statement_type("Sheet1", cells)
        assert result is None


# ─── Sheet 提取测试 ───

class TestExtractSheets:
    def test_multi_sheet_extraction(self, parser):
        excel_result = ExcelParseResult(
            sheets=[
                SheetData(
                    name="资产负债表",
                    cells=[
                        CellData(row=1, col=1, value="项目"),
                        CellData(row=1, col=2, value="期末余额"),
                        CellData(row=2, col=1, value="货币资金"),
                        CellData(row=2, col=2, value=1000000.0),
                    ],
                    merged_ranges=[],
                ),
                SheetData(
                    name="利润表",
                    cells=[
                        CellData(row=1, col=1, value="项目"),
                        CellData(row=1, col=2, value="本期金额"),
                        CellData(row=2, col=1, value="营业收入"),
                        CellData(row=2, col=2, value=5000000.0),
                    ],
                    merged_ranges=[],
                ),
            ],
            sheet_names=["资产负债表", "利润表"],
        )

        sheets = parser.extract_sheets(excel_result)
        assert len(sheets) == 2
        assert sheets[0].sheet_name == "资产负债表"
        assert sheets[0].statement_type == StatementType.BALANCE_SHEET
        assert sheets[1].sheet_name == "利润表"
        assert sheets[1].statement_type == StatementType.INCOME_STATEMENT

    def test_empty_sheet(self, parser):
        excel_result = ExcelParseResult(
            sheets=[SheetData(name="空表", cells=[], merged_ranges=[])],
            sheet_names=["空表"],
        )
        sheets = parser.extract_sheets(excel_result)
        assert len(sheets) == 0  # 无法识别类型的空表应被跳过

    def test_empty_sheet_with_known_name(self, parser):
        """名称可识别的空表仍应保留。"""
        excel_result = ExcelParseResult(
            sheets=[SheetData(name="资产负债表", cells=[], merged_ranges=[])],
            sheet_names=["资产负债表"],
        )
        sheets = parser.extract_sheets(excel_result)
        assert len(sheets) == 1
        assert sheets[0].row_count == 0


# ─── 科目提取测试 ───

class TestExtractStatementItems:
    def test_basic_extraction(self, parser):
        sheet = ReportSheetData(
            sheet_name="资产负债表",
            statement_type=StatementType.BALANCE_SHEET,
            row_count=2,
            headers=["项目", "期末余额", "期初余额"],
            raw_data=[
                ["货币资金", 1000000.0, 800000.0],
                ["应收账款", 500000.0, 400000.0],
            ],
        )
        items = parser.extract_statement_items(sheet)
        assert len(items) == 2
        assert items[0].account_name == "货币资金"
        assert items[0].sheet_name == "资产负债表"
        assert items[0].closing_balance == 1000000.0
        assert items[0].opening_balance == 800000.0
        assert items[0].is_sub_item is False

    def test_sub_item_extraction(self, parser):
        sheet = ReportSheetData(
            sheet_name="资产负债表",
            statement_type=StatementType.BALANCE_SHEET,
            row_count=3,
            headers=["项目", "期末余额", "期初余额"],
            raw_data=[
                ["应收账款", 500000.0, 400000.0],
                ["其中：关联方应收", 100000.0, 80000.0],
                ["其中：第三方应收", 400000.0, 320000.0],
            ],
        )
        items = parser.extract_statement_items(sheet)
        assert len(items) == 3
        assert items[0].is_sub_item is False
        assert items[1].is_sub_item is True
        assert items[1].parent_id == items[0].id
        assert items[1].account_name == "关联方应收"
        assert items[2].is_sub_item is True
        assert items[2].parent_id == items[0].id

    def test_skip_header_total_rows(self, parser):
        sheet = ReportSheetData(
            sheet_name="资产负债表",
            statement_type=StatementType.BALANCE_SHEET,
            row_count=3,
            headers=["项目", "期末余额", "期初余额"],
            raw_data=[
                ["货币资金", 1000000.0, 800000.0],
                ["合计", 1000000.0, 800000.0],
                ["资产总计", 1000000.0, 800000.0],
            ],
        )
        items = parser.extract_statement_items(sheet)
        assert len(items) == 1
        assert items[0].account_name == "货币资金"

    def test_parse_warnings_for_invalid_amounts(self, parser):
        sheet = ReportSheetData(
            sheet_name="资产负债表",
            statement_type=StatementType.BALANCE_SHEET,
            row_count=1,
            headers=["项目", "期末余额", "期初余额"],
            raw_data=[
                ["货币资金", "abc", 800000.0],
            ],
        )
        items = parser.extract_statement_items(sheet)
        assert len(items) == 1
        assert len(items[0].parse_warnings) > 0

    def test_empty_rows_skipped(self, parser):
        sheet = ReportSheetData(
            sheet_name="资产负债表",
            statement_type=StatementType.BALANCE_SHEET,
            row_count=2,
            headers=["项目", "期末余额"],
            raw_data=[
                [None, None],
                ["货币资金", 1000.0],
            ],
        )
        items = parser.extract_statement_items(sheet)
        assert len(items) == 1


# ─── 附注表格提取测试 ───

class TestExtractNoteTables:
    def test_basic_note_table_extraction(self, parser):
        word_result = WordParseResult(
            paragraphs=[
                {"text": "一、应收账款", "style": "Heading 1", "level": 1},
                {"text": "应收账款明细如下：", "style": "Normal"},
            ],
            tables=[
                [
                    ["项目", "期末余额", "期初余额"],
                    ["客户A", "100,000", "80,000"],
                    ["客户B", "200,000", "150,000"],
                ]
            ],
            headings=[{"text": "一、应收账款", "level": 1}],
            comments=[],
            table_contexts=["1、应收账款"],
        )
        tables = parser.extract_note_tables(word_result)
        assert len(tables) == 1
        assert "应收账款" in tables[0].account_name
        assert len(tables[0].headers) == 3
        assert len(tables[0].rows) == 2

    def test_skip_single_row_tables(self, parser):
        word_result = WordParseResult(
            paragraphs=[{"text": "标题", "style": "Heading 1", "level": 1}],
            tables=[
                [["只有一行"]],
            ],
            headings=[{"text": "标题", "level": 1}],
            comments=[],
        )
        tables = parser.extract_note_tables(word_result)
        assert len(tables) == 0

    def test_empty_tables(self, parser):
        word_result = WordParseResult(
            paragraphs=[],
            tables=[],
            headings=[],
            comments=[],
        )
        tables = parser.extract_note_tables(word_result)
        assert len(tables) == 0


# ─── 金额解析测试 ───

class TestParseAmounts:
    def test_numeric_values(self, parser):
        opening, closing, warnings = parser._parse_amounts(
            ["货币资金", 1000000.0, 800000.0], StatementType.BALANCE_SHEET
        )
        assert closing == 1000000.0
        assert opening == 800000.0
        assert len(warnings) == 0

    def test_string_numbers_with_commas(self, parser):
        opening, closing, warnings = parser._parse_amounts(
            ["货币资金", "1,000,000.00", "800,000.00"], StatementType.BALANCE_SHEET
        )
        assert closing == 1000000.0
        assert opening == 800000.0

    def test_dash_as_none(self, parser):
        """"-" 是报表中常见的无数据标记，不产生警告"""
        opening, closing, warnings = parser._parse_amounts(
            ["货币资金", "-", 100.0], StatementType.BALANCE_SHEET
        )
        # "-" 被跳过，100.0 是唯一数值，作为 closing
        assert closing == 100.0
        assert opening is None
        assert len(warnings) == 0

    def test_unparseable_amount_warning(self, parser):
        opening, closing, warnings = parser._parse_amounts(
            ["货币资金", "abc", 100.0], StatementType.BALANCE_SHEET
        )
        assert len(warnings) > 0


# ─── 辅助方法测试 ───

class TestHelpers:
    def test_extract_account_from_heading(self):
        assert ReportParser._extract_account_from_heading("（一）应收账款") == "应收账款"
        assert ReportParser._extract_account_from_heading("1、货币资金") == "货币资金"
        assert ReportParser._extract_account_from_heading("") == ""

    def test_clean_sub_item_name(self):
        parser = ReportParser()
        assert parser._clean_sub_item_name("其中：关联方") == "关联方"
        assert parser._clean_sub_item_name("其中:第三方") == "第三方"

    def test_is_sub_item(self):
        parser = ReportParser()
        assert parser._is_sub_item("其中：关联方") is True
        assert parser._is_sub_item("货币资金") is False

    def test_try_parse_number(self):
        assert ReportParser._try_parse_number(100.0) == 100.0
        assert ReportParser._try_parse_number("1,000") == 1000.0
        assert ReportParser._try_parse_number("-") is None
        assert ReportParser._try_parse_number(None) is None
        assert ReportParser._try_parse_number("abc") is None


# ─── 错误处理测试 ───

class TestErrorHandling:
    def test_unsupported_format(self, parser):
        import asyncio
        with pytest.raises(ValueError, match="不支持的文件格式"):
            asyncio.run(
                parser.parse_report_files(
                    [("test.txt", "test.txt")],
                    template_type="soe",
                )
            )

    def test_file_not_found(self, parser):
        import asyncio
        with pytest.raises(FileNotFoundError):
            asyncio.run(
                parser.parse_report_files(
                    [("/nonexistent/file.xlsx", "file.xlsx")],
                    template_type="soe",
                )
            )
