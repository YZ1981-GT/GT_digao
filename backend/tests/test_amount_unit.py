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
    _item_in_yuan,
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
    def test_balances_kept_in_source_unit(self):
        """余额保持 Sheet 原单位（跨表规则与附注同单位比较），只记录倍率。"""
        sheet = _sheet("万元", 1e4)
        items = ReportParser().extract_statement_items(sheet)
        assert len(items) == 1
        assert items[0].closing_balance == 100.5
        assert items[0].opening_balance == 80
        assert items[0].source_unit_multiplier == 1e4
        assert any("万元" in w for w in items[0].parse_warnings)

    def test_item_in_yuan_copy(self):
        item = ReportParser().extract_statement_items(_sheet("万元", 1e4))[0]
        y = _item_in_yuan(item)
        assert y.closing_balance == 1005000.0 and y.opening_balance == 800000.0
        assert item.closing_balance == 100.5  # 原对象不被修改

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
        # 万元保留 2 位小数：四舍五入误差最多 0.005 万元 = 50 元
        assert _unit_tolerance(item_yuan, _note()) == TOLERANCE
        assert _unit_tolerance(item_wan, _note()) == 50.0
        assert _unit_tolerance(item_yuan, _note("万元", 1e4)) == 50.0
        assert _unit_tolerance(item_yuan, _note("千元", 1e3)) == 5.0

    def test_amounts_equal_with_custom_tolerance(self):
        assert not _amounts_equal(1005000.0, 1005030.0)
        assert _amounts_equal(1005000.0, 1005030.0, 50.0)
        assert not _amounts_equal(1005000.0, 1005060.0, 50.0)


# ─── 端到端：报表 vs 附注金额核对 ───

def _e2e(stmt_closing, stmt_mul, note_closing, note_label, note_mul):
    from app.models.audit_schemas import (
        MatchingEntry, MatchingMap, TableStructure, TableStructureColumn, TableStructureRow,
    )
    item = StatementItem(
        id="it", account_name="应收账款", statement_type=StatementType.BALANCE_SHEET,
        sheet_name="资产负债表", opening_balance=None, closing_balance=stmt_closing,
        row_index=1, source_unit_multiplier=stmt_mul,
    )
    note = NoteTable(
        id="nt", account_name="应收账款", section_title="应收账款附注",
        headers=["项目", "期末余额"], rows=[["A", note_closing], ["合计", note_closing]],
        unit_label=note_label, unit_multiplier=note_mul,
    )
    ts = TableStructure(
        note_table_id="nt",
        rows=[TableStructureRow(row_index=0, role="data", label="A"),
              TableStructureRow(row_index=1, role="total", label="合计")],
        columns=[TableStructureColumn(col_index=0, semantic="label"),
                 TableStructureColumn(col_index=1, semantic="closing_balance")],
        total_row_indices=[1], closing_balance_cell="R1C1", structure_confidence="high",
    )
    mm = MatchingMap(entries=[MatchingEntry(
        statement_item_id="it", note_table_ids=["nt"], match_confidence=1.0)])
    findings = ReconciliationEngine().check_amount_consistency(mm, [item], [note], {"nt": ts})
    return [f for f in findings if f.difference is not None]


class TestAmountConsistencyUnits:
    def test_both_wan_no_false_positive(self):
        assert _e2e(100.5, 1e4, 100.5, "万元", 1e4) == []

    def test_statement_wan_note_yuan_match(self):
        # 100.50 万元 vs 1,005,012.34 元：差 12.34 元 < 50 元，四舍五入范围内
        assert _e2e(100.5, 1e4, 1005012.34, "元", 1.0) == []

    def test_statement_wan_note_yuan_real_difference(self):
        # 差 1,000 元，超出万元口径的四舍五入误差，应报
        diffs = _e2e(100.5, 1e4, 1004000.0, "元", 1.0)
        assert len(diffs) == 1 and diffs[0].difference == 1000.0

    def test_both_yuan_strict(self):
        assert len(_e2e(200.0, 1.0, 201.0, "", 1.0)) == 1


class TestChangeThresholdUnits:
    def test_amount_threshold_scaled_by_unit(self):
        from app.services.report_review_engine import ReportReviewEngine
        eng = ReportReviewEngine.__new__(ReportReviewEngine)
        item = StatementItem(
            id="c1", account_name="存货", statement_type=StatementType.BALANCE_SHEET,
            sheet_name="s", opening_balance=10.0, closing_balance=20.0, row_index=0,
            source_unit_multiplier=1e4,
        )
        changes = eng.calculate_changes([item])
        # 变动 10 万元 = 100,000 元，阈值 50,000 元 → 应报
        assert len(eng.flag_abnormal_changes(changes, 0.3, 50000, {"c1": 1e4})) == 1
        # 阈值 200,000 元 → 不报
        changes = eng.calculate_changes([item])
        assert eng.flag_abnormal_changes(changes, 0.3, 200000, {"c1": 1e4}) == []


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


class TestUnitConsistencyNoise:
    def test_non_amount_tables_not_counted(self):
        people = NoteTable(
            id="p", account_name="员工", section_title="员工人数",
            headers=["项目", "人数", "比例"], rows=[["管理", 10, "5%"]],
        )
        assert ReconciliationEngine().check_unit_consistency([_sheet("万元", 1e4)], [people]) == []


class TestWordTableUnits:
    def _word(self, paragraphs, tables, after_idx):
        from app.models.audit_schemas import WordParseResult
        return WordParseResult(
            paragraphs=[{"text": t, "style": "", "level": None} for t in paragraphs],
            tables=tables, table_after_para_idx=after_idx,
        )

    def test_unit_not_borrowed_from_previous_table(self):
        tbl = [["项目", "期末余额"], ["合计", "1"]]
        word = self._word(
            ["1、货币资金", "单位：万元", "2、应收账款"],
            [tbl, tbl],
            [1, 2],  # 表1在「单位：万元」之后；表2在「2、应收账款」之后
        )
        notes = ReportParser().extract_note_tables(word)
        assert [n.unit_label for n in notes] == ["万元", ""]

    def test_doc_default_unit_fallback(self):
        tbl = [["项目", "期末余额"], ["合计", "1"]]
        word = self._word(
            ["除特别注明外，金额单位为人民币万元", "1、货币资金"],
            [tbl], [1],
        )
        notes = ReportParser().extract_note_tables(word)
        assert notes[0].unit_label == "万元" and notes[0].unit_multiplier == 1e4
