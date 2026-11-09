"""金额单位识别、折算与单位一致性提示的回归测试。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.audit_schemas import (
    NoteTable,
    ReportSheetData,
    StatementItem,
    StatementType,
)
from app.services.reconciliation_engine import (
    TOLERANCE,
    ReconciliationEngine,
    _amounts_equal,
    _scale_note,
    _unit_tolerance,
)
from app.services.report_parser import ReportParser, detect_amount_unit


def _sheet(unit_label="", unit_multiplier=1.0):
    return ReportSheetData(
        sheet_name="资产负债表",
        statement_type=list(StatementType)[0],
        headers=["项目", "附注", "期末余额", "上年年末余额"],
        raw_data=[["货币资金", "", 100.5, 80]],
        unit_label=unit_label,
        unit_multiplier=unit_multiplier,
    )


def _note(unit_label="", unit_multiplier=1.0, title="货币资金"):
    return NoteTable(
        id=f"n-{title}-{unit_label}", account_name=title, section_title=title,
        headers=["项目", "期末余额"], rows=[["合计", 1]],
        unit_label=unit_label, unit_multiplier=unit_multiplier,
    )


class TestDetectAmountUnit:
    def test_common_declarations(self):
        assert detect_amount_unit(["编制单位：甲公司    单位：万元"]) == ("万元", 1e4)
        assert detect_amount_unit(["金额单位：人民币元"]) == ("元", 1.0)
        assert detect_amount_unit(["单位：百万元"]) == ("百万元", 1e6)
        assert detect_amount_unit(["金额单位为人民币千元"]) == ("千元", 1e3)

    def test_unrelated_text_not_matched(self):
        assert detect_amount_unit(["本年新增投资约5000万元"]) == ("", 1.0)
        assert detect_amount_unit([]) == ("", 1.0)

    def test_entity_name_starting_with_yuan_not_misread(self):
        # 编制单位后面的公司名以「元」开头，不是单位声明
        assert detect_amount_unit(["编制单位：元泰科技有限公司"]) == ("", 1.0)

    def test_nearest_text_wins(self):
        assert detect_amount_unit(["单位：万元", "单位：元"]) == ("万元", 1e4)


class TestStatementScaling:
    def test_balances_scaled_and_raw_data_untouched(self):
        sheet = _sheet("万元", 1e4)
        items = ReportParser().extract_statement_items(sheet)
        assert len(items) == 1
        assert items[0].closing_balance == 1005000.0
        assert items[0].opening_balance == 800000.0
        assert items[0].source_unit_multiplier == 1e4
        assert sheet.raw_data[0][2] == 100.5  # 原值不变
        assert any("万元" in w for w in items[0].parse_warnings)

    def test_default_unit_is_yuan(self):
        items = ReportParser().extract_statement_items(_sheet())
        assert items[0].closing_balance == 100.5
        assert items[0].source_unit_multiplier == 1.0


class TestToleranceAndScale:
    def test_scale_note(self):
        assert _scale_note(_note("万元", 1e4), 2.5) == 25000.0
        assert _scale_note(_note(), 2.5) == 2.5
        assert _scale_note(_note("万元", 1e4), None) is None

    def test_tolerance_follows_coarser_unit(self):
        item_yuan = StatementItem(
            id="i", account_name="x", statement_type=list(StatementType)[0],
            sheet_name="s", row_index=0,
        )
        item_wan = item_yuan.model_copy(update={"source_unit_multiplier": 1e4})
        assert _unit_tolerance(item_yuan, _note()) == TOLERANCE
        assert _unit_tolerance(item_wan, _note()) == TOLERANCE * 1e4
        assert _unit_tolerance(item_yuan, _note("万元", 1e4)) == TOLERANCE * 1e4

    def test_amounts_equal_with_custom_tolerance(self):
        assert not _amounts_equal(1005000.0, 1005030.0)
        assert _amounts_equal(1005000.0, 1005030.0, TOLERANCE * 1e4)


class TestUnitConsistency:
    engine = ReconciliationEngine()

    def test_mismatch_between_statement_and_notes(self):
        f = self.engine.check_unit_consistency([_sheet("万元", 1e4)], [_note("元", 1.0)])
        assert len(f) == 1 and "不一致" in f[0].description

    def test_notes_without_declaration_when_statement_not_yuan(self):
        f = self.engine.check_unit_consistency([_sheet("万元", 1e4)], [_note()])
        assert len(f) == 1 and "未识别到单位声明" in f[0].description

    def test_statement_undeclared_when_notes_not_yuan(self):
        f = self.engine.check_unit_consistency([_sheet()], [_note("万元", 1e4)])
        assert len(f) == 1 and "报表未识别到单位声明" in f[0].description

    def test_consistent_units_no_finding(self):
        assert self.engine.check_unit_consistency([_sheet("万元", 1e4)], [_note("万元", 1e4)]) == []
        assert self.engine.check_unit_consistency([_sheet()], [_note()]) == []


class TestPdfTableUnits:
    def test_unit_near_marker_and_default_fallback(self):
        text = "\n".join([
            "除特别注明外，金额单位为人民币元",
            "1、货币资金",
            "单位：万元",
            "[表格 1]",
            "项目|期末",
            "[表格结束]",
            "2、应收账款",
            "[表格 2]",
            "项目|期末",
            "[表格结束]",
        ])
        units = ReportParser._extract_pdf_table_units(text)
        assert units == [("万元", 1e4), ("元", 1.0)]
