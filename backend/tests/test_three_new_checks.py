# -*- coding: utf-8 -*-
"""Tests for 3 new check methods:
- check_financial_expense_detail (F64-3)
- check_benefit_plan_movement (F49-5~10a)
- check_equity_subtotal_detail (F53-3a)
"""
import sys
sys.path.insert(0, ".")

from app.services.reconciliation_engine import (
    ReconciliationEngine, _safe_float, _amounts_equal, TOLERANCE,
)
from app.models.audit_schemas import (
    NoteTable, TableStructure, TableStructureColumn, TableStructureRow,
    ReportReviewFinding, ReportReviewFindingCategory, RiskLevel,
)


def _make_ts(note_id="test"):
    """Minimal TableStructure for per-table checks."""
    return TableStructure(
        note_table_id=note_id,
        columns=[TableStructureColumn(col_index=0, semantic="label")],
        rows=[],
        total_row_indices=[],
    )


# ═══════════════════════════════════════════════════════════
# F64-3: check_financial_expense_detail
# ═══════════════════════════════════════════════════════════

class TestFinancialExpenseDetail:
    """财务费用纵向: 利息费用总额 - 利息资本化 = 利息费用净额."""

    def test_correct_no_findings(self):
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe1", account_name="财务费用", section_title="财务费用",
            headers=["项目", "本期发生额", "上期发生额"],
            rows=[
                ["利息费用总额", 1000, 800],
                ["减：利息资本化", 200, 100],
                ["利息费用净额", 800, 700],
                ["减：利息收入", 50, 40],
                ["合计", 750, 660],
            ],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe1"))
        assert len(findings) == 0

    def test_error_detected(self):
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe2", account_name="财务费用", section_title="财务费用",
            headers=["项目", "本期发生额", "上期发生额"],
            rows=[
                ["利息费用总额", 1000, 800],
                ["减：利息资本化", 200, 100],
                ["利息费用净额", 850, 700],  # 1000-200=800, not 850
                ["减：利息收入", 50, 40],
                ["合计", 800, 660],
            ],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe2"))
        assert len(findings) == 1
        assert abs(findings[0].difference - 50) < 0.01
        assert "F64-3" in findings[0].analysis_reasoning

    def test_no_capitalization_row(self):
        """无利息资本化行时，净额应等于总额."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe3", account_name="财务费用", section_title="财务费用",
            headers=["项目", "本期发生额"],
            rows=[
                ["利息费用总额", 500],
                ["利息费用净额", 500],
                ["减：利息收入", 30],
                ["合计", 470],
            ],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe3"))
        assert len(findings) == 0

    def test_no_capitalization_row_error(self):
        """无利息资本化行，净额不等于总额."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe4", account_name="财务费用", section_title="财务费用",
            headers=["项目", "本期发生额"],
            rows=[
                ["利息费用总额", 500],
                ["利息费用净额", 480],
                ["减：利息收入", 30],
                ["合计", 450],
            ],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe4"))
        assert len(findings) == 1
        assert abs(findings[0].difference - (-20)) < 0.01

    def test_non_financial_expense_skipped(self):
        """非财务费用表应跳过."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe5", account_name="管理费用", section_title="管理费用",
            headers=["项目", "本期发生额"],
            rows=[["利息费用总额", 100], ["利息费用净额", 90]],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe5"))
        assert len(findings) == 0

    def test_multi_column_independent(self):
        """本期/上期各列独立校验."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe6", account_name="财务费用", section_title="财务费用",
            headers=["项目", "本期发生额", "上期发生额"],
            rows=[
                ["利息费用总额", 1000, 800],
                ["减：利息资本化", 200, 100],
                ["利息费用净额", 800, 750],  # col1 OK, col2: 800-100=700 != 750
            ],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe6"))
        assert len(findings) == 1
        assert "第3列" in findings[0].location

    def test_alternative_label_lxzc(self):
        """利息支出净额 as alternative label."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="fe7", account_name="财务费用", section_title="财务费用明细",
            headers=["项目", "本期发生额"],
            rows=[
                ["利息费用", 500],
                ["减：利息资本化", 100],
                ["利息支出净额", 400],
            ],
        )
        findings = engine.check_financial_expense_detail(note, _make_ts("fe7"))
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════
# F49-5~10a: check_benefit_plan_movement
# ═══════════════════════════════════════════════════════════

class TestBenefitPlanMovement:
    """设定受益计划变动表校验."""

    def _make_note(self, note_id, rows, title="设定受益计划义务现值"):
        return NoteTable(
            id=note_id, account_name="长期应付职工薪酬",
            section_title=title,
            headers=["项目", "本期金额", "上期金额"],
            rows=rows,
        )

    def test_vertical_correct(self):
        engine = ReconciliationEngine()
        note = self._make_note("bp1", [
            ["一、期初余额", 1000, 900],
            ["二、计入当期损益", 200, 150],
            ["1.当期服务成本", 120, 90],
            ["2.利息净额", 80, 60],
            ["三、计入其他综合收益", 50, 30],
            ["1.精算利得", 50, 30],
            ["四、其他变动", -100, -80],
            ["1.已支付的福利", -100, -80],
            ["五、期末余额", 1150, 1000],
        ])
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp1"))
        assert len(findings) == 0

    def test_vertical_error(self):
        engine = ReconciliationEngine()
        note = self._make_note("bp2", [
            ["一、期初余额", 1000, 900],
            ["二、计入当期损益", 200, 150],
            ["三、计入其他综合收益", 50, 30],
            ["四、其他变动", -100, -80],
            ["五、期末余额", 1200, 1000],  # 1000+200+50-100=1150, not 1200
        ])
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp2"))
        vertical_findings = [f for f in findings if "期末余额" in f.description]
        assert len(vertical_findings) == 1
        assert abs(vertical_findings[0].difference - 50) < 0.01

    def test_sub_item_error(self):
        """子项之和不等于主段."""
        engine = ReconciliationEngine()
        note = self._make_note("bp3", [
            ["一、期初余额", 1000, 900],
            ["二、计入当期损益", 200, 150],
            ["1.当期服务成本", 120, 90],
            ["2.利息净额", 90, 60],  # 120+90=210 != 200
            ["三、计入其他综合收益", 50, 30],
            ["四、其他变动", -100, -80],
            ["五、期末余额", 1150, 1000],
        ])
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp3"))
        sub_findings = [f for f in findings if "子项" in f.description]
        assert len(sub_findings) >= 1
        assert "计入当期损益" in sub_findings[0].description

    def test_non_benefit_plan_skipped(self):
        engine = ReconciliationEngine()
        note = NoteTable(
            id="bp4", account_name="固定资产", section_title="固定资产变动",
            headers=["项目", "金额"],
            rows=[["一、期初余额", 100], ["五、期末余额", 200]],
        )
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp4"))
        assert len(findings) == 0

    def test_missing_sections_skipped(self):
        """缺少一/五段时跳过."""
        engine = ReconciliationEngine()
        note = self._make_note("bp5", [
            ["二、计入当期损益", 200, 150],
            ["三、计入其他综合收益", 50, 30],
        ])
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp5"))
        assert len(findings) == 0

    def test_plan_asset_table(self):
        """计划资产表也适用."""
        engine = ReconciliationEngine()
        note = self._make_note("bp6", [
            ["一、期初余额", 500, 400],
            ["二、计入当期损益", 30, 25],
            ["三、计入其他综合收益", 10, 8],
            ["四、其他变动", -20, -15],
            ["五、期末余额", 520, 418],
        ], title="设定受益计划-计划资产")
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp6"))
        assert len(findings) == 0

    def test_net_liability_table(self):
        """净负债表也适用."""
        engine = ReconciliationEngine()
        note = self._make_note("bp7", [
            ["一、期初余额", 500, 500],
            ["二、计入当期损益", 170, 125],
            ["三、计入其他综合收益", 40, 22],
            ["四、其他变动", -80, -65],
            ["五、期末余额", 630, 582],
        ], title="设定受益计划净负债（净资产）")
        findings = engine.check_benefit_plan_movement(note, _make_ts("bp7"))
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════
# F53-3a: check_equity_subtotal_detail
# ═══════════════════════════════════════════════════════════

class TestEquitySubtotalDetail:
    """股本/实收资本明细表小计列校验."""

    def test_correct_no_findings(self):
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq1", account_name="股本", section_title="股本",
            headers=["投资者", "期初余额", "发行新股", "送股", "公积金转股", "其他", "小计", "期末余额"],
            rows=[
                ["股东A", 1000, 200, 50, 30, 20, 300, 1300],
                ["股东B", 500, 100, 0, 0, 0, 100, 600],
                ["合计", 1500, 300, 50, 30, 20, 400, 1900],
            ],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq1"))
        assert len(findings) == 0

    def test_error_detected(self):
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq2", account_name="股本", section_title="股本",
            headers=["投资者", "期初余额", "发行新股", "送股", "公积金转股", "其他", "小计", "期末余额"],
            rows=[
                ["股东A", 1000, 200, 50, 30, 20, 350, 1350],  # 200+50+30+20=300, not 350
                ["合计", 1000, 200, 50, 30, 20, 350, 1350],
            ],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq2"))
        assert len(findings) == 2
        assert abs(findings[0].difference - (-50)) < 0.01
        assert "F53-3a" in findings[0].analysis_reasoning

    def test_ssrb_also_works(self):
        """实收资本 also triggers the check."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq3", account_name="实收资本", section_title="实收资本",
            headers=["投资者", "期初余额", "增资", "减资", "小计", "期末余额"],
            rows=[
                ["投资者A", 1000, 200, -50, 150, 1150],
            ],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq3"))
        assert len(findings) == 0

    def test_non_equity_skipped(self):
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq4", account_name="资本公积", section_title="资本公积",
            headers=["项目", "期初余额", "增加", "减少", "小计", "期末余额"],
            rows=[["溢价", 100, 20, 5, 15, 115]],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq4"))
        assert len(findings) == 0

    def test_no_subtotal_col_skipped(self):
        """无小计列时跳过."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq5", account_name="股本", section_title="股本",
            headers=["投资者", "期初余额", "本期增加", "本期减少", "期末余额"],
            rows=[["股东A", 1000, 200, 50, 1150]],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq5"))
        assert len(findings) == 0

    def test_ratio_columns_skipped(self):
        """比例列应被跳过不参与计算."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq6", account_name="股本", section_title="股本",
            headers=["投资者", "期初余额", "比例%", "发行新股", "送股", "小计", "期末余额", "比例%"],
            rows=[
                ["股东A", 1000, "50%", 200, 100, 300, 1300, "52%"],
            ],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq6"))
        assert len(findings) == 0

    def test_bqzj_as_subtotal(self):
        """本期增减 as subtotal column name."""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="eq7", account_name="实收资本", section_title="实收资本",
            headers=["投资者", "期初余额", "增资", "减资", "本期增减", "期末余额"],
            rows=[
                ["投资者A", 1000, 300, -100, 200, 1200],
            ],
        )
        findings = engine.check_equity_subtotal_detail(note, _make_ts("eq7"))
        assert len(findings) == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
