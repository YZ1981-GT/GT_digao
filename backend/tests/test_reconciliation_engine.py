"""Reconciliation_Engine 单元测试（Task 4.8）。

覆盖：科目匹配、金额一致性、附注内部勾稽、余额公式、其中项、浮点精度、统计汇总。
"""
import uuid

import pytest

from backend.app.models.audit_schemas import (
    FindingConfirmationStatus,
    MatchingEntry,
    MatchingMap,
    NoteTable,
    ReportReviewFindingCategory,
    RiskLevel,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from backend.app.services.reconciliation_engine import ReconciliationEngine


# ─── helpers ───

def _item(name="应收账款", opening=100.0, closing=200.0, sheet="资产负债表"):
    return StatementItem(
        id=str(uuid.uuid4()), account_name=name,
        statement_type=StatementType.BALANCE_SHEET,
        sheet_name=sheet, opening_balance=opening,
        closing_balance=closing, row_index=1,
    )


def _note(name="应收账款", title="应收账款附注", headers=None, rows=None):
    return NoteTable(
        id=str(uuid.uuid4()), account_name=name,
        section_title=title,
        headers=headers or ["项目", "期初余额", "期末余额"],
        rows=rows or [["A", 50, 100], ["B", 50, 100], ["合计", 100, 200]],
    )


def _ts(note_id, rows=None, columns=None, total_indices=None,
        closing_cell="R2C2", opening_cell="R2C1",
        has_balance=False, subtotal_indices=None):
    return TableStructure(
        note_table_id=note_id,
        rows=rows or [
            TableStructureRow(row_index=0, role="data", label="A"),
            TableStructureRow(row_index=1, role="data", label="B"),
            TableStructureRow(row_index=2, role="total", label="合计"),
        ],
        columns=columns or [
            TableStructureColumn(col_index=0, semantic="label"),
            TableStructureColumn(col_index=1, semantic="opening_balance"),
            TableStructureColumn(col_index=2, semantic="closing_balance"),
        ],
        total_row_indices=total_indices or [2],
        subtotal_row_indices=subtotal_indices or [],
        closing_balance_cell=closing_cell,
        opening_balance_cell=opening_cell,
        has_balance_formula=has_balance,
        structure_confidence="high",
    )


engine = ReconciliationEngine()


# ─── 科目匹配测试 ───

class TestBuildMatchingMap:
    def test_exact_match(self):
        items = [_item("应收账款")]
        notes = [_note("应收账款")]
        mm = engine.build_matching_map(items, notes)
        assert len(mm.entries) == 1
        assert mm.entries[0].match_confidence >= 0.9
        assert len(mm.unmatched_items) == 0

    def test_partial_match(self):
        items = [_item("应收账款")]
        notes = [_note("应收账款——账龄")]
        mm = engine.build_matching_map(items, notes)
        assert len(mm.entries) == 1
        assert mm.entries[0].match_confidence >= 0.5

    def test_no_match(self):
        items = [_item("固定资产")]
        notes = [_note("应收账款")]
        mm = engine.build_matching_map(items, notes)
        assert len(mm.unmatched_items) == 1
        assert mm.unmatched_items[0] == items[0].id

    def test_unmatched_notes(self):
        items = [_item("应收账款")]
        notes = [_note("应收账款"), _note("无形资产")]
        mm = engine.build_matching_map(items, notes)
        assert len(mm.unmatched_notes) == 1

    def test_cross_sheet_matching(self):
        items = [_item("应收账款", sheet="资产负债表"), _item("营业收入", sheet="利润表")]
        notes = [_note("应收账款"), _note("营业收入")]
        mm = engine.build_matching_map(items, notes)
        assert len(mm.entries) == 2


# ─── 金额一致性校验 ───

class TestAmountConsistency:
    def test_consistent_amounts(self):
        item = _item("应收账款", opening=100, closing=200)
        note = _note("应收账款", rows=[["A", 50, 100], ["B", 50, 100], ["合计", 100, 200]])
        ts = _ts(note.id)
        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id, note_table_ids=[note.id], match_confidence=1.0,
        )])
        findings = engine.check_amount_consistency(mm, [item], [note], {note.id: ts})
        assert len(findings) == 0

    def test_inconsistent_closing(self):
        item = _item("应收账款", opening=100, closing=250)
        note = _note("应收账款", rows=[["A", 50, 100], ["B", 50, 100], ["合计", 100, 200]])
        ts = _ts(note.id)
        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id, note_table_ids=[note.id], match_confidence=1.0,
        )])
        findings = engine.check_amount_consistency(mm, [item], [note], {note.id: ts})
        assert len(findings) >= 1
        f = findings[0]
        assert f.category == ReportReviewFindingCategory.AMOUNT_INCONSISTENCY
        assert f.difference == 50.0
        assert f.confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION

    def test_float_tolerance(self):
        """浮点容差 < 0.01 视为一致。"""
        item = _item("应收账款", opening=100.005, closing=200.003)
        note = _note("应收账款", rows=[["A", 50, 100], ["B", 50, 100], ["合计", 100.001, 200.001]])
        ts = _ts(note.id)
        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id, note_table_ids=[note.id], match_confidence=1.0,
        )])
        findings = engine.check_amount_consistency(mm, [item], [note], {note.id: ts})
        assert len(findings) == 0


# ─── 附注内部勾稽 ───

class TestNoteTableIntegrity:
    def test_correct_totals(self):
        note = _note(rows=[["A", 50, 100], ["B", 50, 100], ["合计", 100, 200]])
        ts = _ts(note.id)
        findings = engine.check_note_table_integrity(note, ts)
        assert len(findings) == 0

    def test_incorrect_total(self):
        note = _note(rows=[["A", 50, 100], ["B", 50, 100], ["合计", 90, 200]])
        ts = _ts(note.id)
        findings = engine.check_note_table_integrity(note, ts)
        assert len(findings) >= 1
        assert findings[0].category == ReportReviewFindingCategory.RECONCILIATION_ERROR


# ─── 余额变动公式 ───

class TestBalanceFormula:
    def test_correct_formula(self):
        note = _note(
            headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
            rows=[["固定资产", 1000, 200, 50, 1150], ["合计", 1000, 200, 50, 1150]],
        )
        ts = _ts(note.id, rows=[
            TableStructureRow(row_index=0, role="data", label="固定资产"),
            TableStructureRow(row_index=1, role="total", label="合计"),
        ], columns=[
            TableStructureColumn(col_index=0, semantic="label"),
            TableStructureColumn(col_index=1, semantic="opening_balance"),
            TableStructureColumn(col_index=2, semantic="current_increase"),
            TableStructureColumn(col_index=3, semantic="current_decrease"),
            TableStructureColumn(col_index=4, semantic="closing_balance"),
        ], has_balance=True)
        findings = engine.check_balance_formula(note, ts)
        assert len(findings) == 0

    def test_incorrect_formula(self):
        note = _note(
            headers=["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
            rows=[["固定资产", 1000, 200, 50, 1200]],  # 1000+200-50=1150≠1200
        )
        ts = _ts(note.id, rows=[
            TableStructureRow(row_index=0, role="data", label="固定资产"),
        ], columns=[
            TableStructureColumn(col_index=0, semantic="label"),
            TableStructureColumn(col_index=1, semantic="opening_balance"),
            TableStructureColumn(col_index=2, semantic="current_increase"),
            TableStructureColumn(col_index=3, semantic="current_decrease"),
            TableStructureColumn(col_index=4, semantic="closing_balance"),
        ], has_balance=True)
        findings = engine.check_balance_formula(note, ts)
        assert len(findings) == 1
        assert "余额变动公式不平" in findings[0].description

    def test_no_balance_formula_skips(self):
        note = _note()
        ts = _ts(note.id, has_balance=False)
        findings = engine.check_balance_formula(note, ts)
        assert len(findings) == 0


# ─── 其中项校验 ───

class TestSubItems:
    def test_sub_items_within_parent(self):
        note = _note(rows=[
            ["应收账款", 0, 100],
            ["其中：A", 0, 60],
            ["其中：B", 0, 30],
            ["合计", 0, 100],
        ])
        ts = _ts(note.id, rows=[
            TableStructureRow(row_index=0, role="data", label="应收账款"),
            TableStructureRow(row_index=1, role="sub_item", label="其中：A", parent_row_index=0, indent_level=1),
            TableStructureRow(row_index=2, role="sub_item", label="其中：B", parent_row_index=0, indent_level=1),
            TableStructureRow(row_index=3, role="total", label="合计"),
        ])
        findings = engine.check_sub_items(note, ts)
        assert len(findings) == 0  # 60+30=90 ≤ 100

    def test_sub_items_exceed_parent(self):
        note = _note(rows=[
            ["应收账款", 0, 100],
            ["其中：A", 0, 70],
            ["其中：B", 0, 50],
            ["合计", 0, 100],
        ])
        ts = _ts(note.id, rows=[
            TableStructureRow(row_index=0, role="data", label="应收账款"),
            TableStructureRow(row_index=1, role="sub_item", label="其中：A", parent_row_index=0, indent_level=1),
            TableStructureRow(row_index=2, role="sub_item", label="其中：B", parent_row_index=0, indent_level=1),
            TableStructureRow(row_index=3, role="total", label="合计"),
        ])
        findings = engine.check_sub_items(note, ts)
        assert len(findings) >= 1  # 70+50=120 > 100


# ─── 统计汇总 ───

class TestReconciliationSummary:
    def test_summary(self):
        from backend.app.models.audit_schemas import ReportReviewFinding, FindingStatus
        findings = [
            ReportReviewFinding(
                id="1", category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                risk_level=RiskLevel.HIGH, account_name="A", location="L",
                description="D", difference=50.0,
                confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                status=FindingStatus.OPEN,
            ),
            ReportReviewFinding(
                id="2", category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                risk_level=RiskLevel.MEDIUM, account_name="B", location="L",
                description="D", difference=0.001,
                confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                status=FindingStatus.OPEN,
            ),
        ]
        summary = engine.get_reconciliation_summary(findings)
        assert summary["mismatched"] == 1
        assert summary["matched"] == 1


# ─── 纯函数性 ───

class TestPureFunction:
    def test_same_input_same_output(self):
        """check_amount_consistency 为纯函数。"""
        item = _item("应收账款", opening=100, closing=250)
        note = _note("应收账款", rows=[["A", 50, 100], ["B", 50, 100], ["合计", 100, 200]])
        ts = _ts(note.id)
        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id, note_table_ids=[note.id], match_confidence=1.0,
        )])
        r1 = engine.check_amount_consistency(mm, [item], [note], {note.id: ts})
        r2 = engine.check_amount_consistency(mm, [item], [note], {note.id: ts})
        assert len(r1) == len(r2)
        for f1, f2 in zip(r1, r2):
            assert f1.difference == f2.difference
            assert f1.description == f2.description
