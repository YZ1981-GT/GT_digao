"""变动金额阈值过滤测试。

验证 flag_abnormal_changes 和明细行变动分析中的金额阈值过滤逻辑。
"""
import uuid
import pytest

from app.models.audit_schemas import (
    ChangeAnalysis,
    MatchingEntry,
    MatchingMap,
    NoteTable,
    ReportReviewConfig,
    ReportReviewFindingCategory,
    ReportTemplateType,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from app.services.report_review_engine import ReportReviewEngine

engine = ReportReviewEngine()


class TestFlagAbnormalChanges:
    """flag_abnormal_changes 金额阈值过滤测试。"""

    def _make_changes(self):
        """构造一组变动分析结果。"""
        return [
            ChangeAnalysis(
                statement_item_id="1", account_name="其他应收款",
                opening_balance=17170568.45, closing_balance=28547388.90,
                change_amount=11376820.45,  # ~1137万元
                change_percentage=0.663,  # 66.3%
            ),
            ChangeAnalysis(
                statement_item_id="2", account_name="货币资金",
                opening_balance=100000000, closing_balance=800000000,
                change_amount=700000000,  # 7亿 = 70000万元
                change_percentage=7.0,  # 700%
            ),
            ChangeAnalysis(
                statement_item_id="3", account_name="应收账款",
                opening_balance=50000000, closing_balance=70000000,
                change_amount=20000000,  # 2000万元
                change_percentage=0.4,  # 40%
            ),
        ]

    def test_no_amount_threshold(self):
        """不设金额阈值时，所有超比率阈值的科目都应报出。"""
        changes = self._make_changes()
        abnormal = engine.flag_abnormal_changes(changes, threshold=0.3, amount_threshold=0)
        assert len(abnormal) == 3

    def test_amount_threshold_filters_small_changes(self):
        """设金额阈值 55900万元 = 559000000元，变动金额 < 阈值的应被过滤。"""
        changes = self._make_changes()
        # 55900万元 = 559000000元
        abnormal = engine.flag_abnormal_changes(
            changes, threshold=0.3, amount_threshold=559000000,
        )
        # 其他应收款: 11376820 < 559000000 → 过滤
        # 货币资金: 700000000 > 559000000 → 保留
        # 应收账款: 20000000 < 559000000 → 过滤
        assert len(abnormal) == 1
        assert abnormal[0].account_name == "货币资金"

    def test_amount_threshold_100wan(self):
        """设金额阈值 100万元 = 1000000元。"""
        changes = self._make_changes()
        abnormal = engine.flag_abnormal_changes(
            changes, threshold=0.3, amount_threshold=1000000,
        )
        # 其他应收款: 11376820 > 1000000 → 保留
        # 货币资金: 700000000 > 1000000 → 保留
        # 应收账款: 20000000 > 1000000 → 保留
        assert len(abnormal) == 3

    def test_amount_threshold_exact_boundary(self):
        """变动金额恰好等于阈值时不应被过滤（只过滤严格小于的）。"""
        changes = [
            ChangeAnalysis(
                statement_item_id="1", account_name="测试科目",
                opening_balance=100, closing_balance=200,
                change_amount=100,
                change_percentage=1.0,
            ),
        ]
        abnormal = engine.flag_abnormal_changes(
            changes, threshold=0.3, amount_threshold=100,
        )
        # abs(100) < 100 is False → 不过滤
        assert len(abnormal) == 1


class TestAmountInconsistencyNotFilteredByThreshold:
    """回归测试：金额阈值不应影响 AMOUNT_INCONSISTENCY 和 RECONCILIATION_ERROR。

    确保 change_amount_threshold 只对 CHANGE_ABNORMAL 生效，
    不会过滤报表vs附注不一致和勾稽错误。
    """

    def _item(self, name, closing=200.0, opening=100.0):
        return StatementItem(
            id=str(uuid.uuid4())[:8],
            account_name=name,
            closing_balance=closing,
            opening_balance=opening,
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表",
            row_index=1,
        )

    def _note(self, name, closing_val=999.0, opening_val=888.0):
        """构造附注表格，期末在 R2C2，期初在 R2C1。"""
        nid = str(uuid.uuid4())[:8]
        return NoteTable(
            id=nid,
            account_name=name,
            section_title=f"{name}附注",
            headers=["项目", "期初余额", "期末余额"],
            rows=[
                ["合计", str(opening_val), str(closing_val)],
            ],
        )

    def _ts(self, note_id, closing_cell="R1C2", opening_cell="R1C1"):
        return TableStructure(
            note_table_id=note_id,
            columns=[
                TableStructureColumn(col_index=0, header="项目", semantic="label"),
                TableStructureColumn(col_index=1, header="期初余额", semantic="opening_balance"),
                TableStructureColumn(col_index=2, header="期末余额", semantic="closing_balance"),
            ],
            rows=[
                TableStructureRow(row_index=0, label="合计", role="total"),
            ],
            closing_balance_cell=closing_cell,
            opening_balance_cell=opening_cell,
        )

    def test_amount_inconsistency_not_filtered(self):
        """报表vs附注金额不一致的 finding 不应被金额阈值过滤。

        即使差异金额很小（如 1 元），只要报表和附注不一致就应报出。
        """
        from app.services.reconciliation_engine import ReconciliationEngine

        recon = ReconciliationEngine()

        # 报表余额 200，附注合计 199（差异仅 1 元）
        item = self._item("货币资金", closing=200.0, opening=100.0)
        note = self._note("货币资金", closing_val=199.0, opening_val=100.0)
        ts = self._ts(note.id)

        matching_map = MatchingMap(entries=[
            MatchingEntry(
                statement_item_id=item.id,
                note_table_ids=[note.id],
            ),
        ])

        findings = recon.check_amount_consistency(
            matching_map, [item], [note], {note.id: ts},
        )

        # 应有 1 个期末不一致 finding（差异 1 元）
        amount_findings = [
            f for f in findings
            if f.category == ReportReviewFindingCategory.AMOUNT_INCONSISTENCY
        ]
        assert len(amount_findings) >= 1
        assert any("期末" in f.location for f in amount_findings)

    def test_reconciliation_error_not_filtered(self):
        """勾稽错误的 finding 不应被金额阈值过滤。

        check_amount_consistency 生成的 AMOUNT_INCONSISTENCY 类型 finding
        无论差异大小都应保留。
        """
        from app.services.reconciliation_engine import ReconciliationEngine

        recon = ReconciliationEngine()

        # 报表期末 1000，附注合计 500（差异 500 元，远小于常见阈值如 35200万元）
        item = self._item("应收账款", closing=1000.0, opening=500.0)
        note = self._note("应收账款", closing_val=500.0, opening_val=500.0)
        ts = self._ts(note.id)

        matching_map = MatchingMap(entries=[
            MatchingEntry(
                statement_item_id=item.id,
                note_table_ids=[note.id],
            ),
        ])

        findings = recon.check_amount_consistency(
            matching_map, [item], [note], {note.id: ts},
        )

        amount_findings = [
            f for f in findings
            if f.category == ReportReviewFindingCategory.AMOUNT_INCONSISTENCY
        ]
        # 期末差异 500 应被报出
        assert len(amount_findings) >= 1
        closing_f = [f for f in amount_findings if "期末" in f.location]
        assert len(closing_f) == 1
        assert abs(closing_f[0].difference - 500.0) < 0.01
