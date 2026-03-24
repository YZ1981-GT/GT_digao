"""针对 8 项改进的边缘场景测试。"""
import sys
sys.path.insert(0, ".")

from app.services.reconciliation_engine import (
    ReconciliationEngine, _safe_float, _amounts_equal, TOLERANCE, RATIO_TOLERANCE,
)
from app.models.audit_schemas import (
    NoteTable, TableStructure, TableStructureColumn, TableStructureRow,
    ReportReviewFinding, ReportReviewFindingCategory, RiskLevel,
    StatementItem, StatementType,
)


# ═══════════════════════════════════════════════════════════
# P0-5: check_book_value_formula multi-deduction
# ═══════════════════════════════════════════════════════════

class TestBookValueMultiDeduction:
    """测试纵向勾稽支持多扣减列。"""

    def _make_ts(self, cols, rows, note_id="test"):
        return TableStructure(
            note_table_id=note_id,
            columns=[TableStructureColumn(col_index=c[0], semantic=c[1]) for c in cols],
            rows=[TableStructureRow(row_index=r[0], role=r[1], label=r[2]) for r in rows],
            total_row_indices=[r[0] for r in rows if r[1] == "total"],
        )

    def test_single_deduction_still_works(self):
        """单扣减列（坏账准备）仍然正常工作。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="bv1", account_name="应收账款", section_title="应收账款",
            headers=["项目", "账面余额", "坏账准备", "账面价值"],
            rows=[
                ["客户A", 1000, 200, 800],
                ["合计", 5000, 1000, 4000],
            ],
        )
        ts = self._make_ts(
            [(0, "label"), (1, "other"), (2, "other"), (3, "other")],
            [(0, "data", "客户A"), (1, "total", "合计")],
        )
        findings = engine.check_book_value_formula(note, ts)
        assert len(findings) == 0, f"Expected 0 findings, got {len(findings)}"

    def test_single_deduction_error(self):
        """单扣减列有差异时报错。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="bv2", account_name="应收账款", section_title="应收账款",
            headers=["项目", "账面余额", "坏账准备", "账面价值"],
            rows=[
                ["客户A", 1000, 200, 850],  # 1000-200=800, not 850
            ],
        )
        ts = self._make_ts(
            [(0, "label"), (1, "other"), (2, "other"), (3, "other")],
            [(0, "data", "客户A")],
        )
        findings = engine.check_book_value_formula(note, ts)
        assert len(findings) == 1
        assert abs(findings[0].difference - 50) < 0.01

    def test_multi_deduction_correct(self):
        """多扣减列（累计折旧+减值准备）正确时无报错。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="bv3", account_name="固定资产", section_title="固定资产",
            headers=["项目", "期末账面余额", "期末累计折旧", "期末减值准备", "期末账面价值"],
            rows=[
                ["房屋", 10000, 3000, 500, 6500],  # 10000-3000-500=6500 ✓
                ["合计", 50000, 15000, 2000, 33000],  # 50000-15000-2000=33000 ✓
            ],
        )
        ts = self._make_ts(
            [(0, "label"), (1, "other"), (2, "other"), (3, "other"), (4, "other")],
            [(0, "data", "房屋"), (1, "total", "合计")],
        )
        findings = engine.check_book_value_formula(note, ts)
        assert len(findings) == 0, f"Expected 0, got {len(findings)}: {[f.description for f in findings]}"

    def test_multi_deduction_error(self):
        """多扣减列有差异时报错。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="bv4", account_name="固定资产", section_title="固定资产",
            headers=["项目", "期末账面余额", "期末累计折旧", "期末减值准备", "期末账面价值"],
            rows=[
                ["房屋", 10000, 3000, 500, 7000],  # 10000-3000-500=6500, not 7000
            ],
        )
        ts = self._make_ts(
            [(0, "label"), (1, "other"), (2, "other"), (3, "other"), (4, "other")],
            [(0, "data", "房屋")],
        )
        findings = engine.check_book_value_formula(note, ts)
        assert len(findings) == 1
        assert abs(findings[0].difference - 500) < 0.01
        assert "扣减项合计" in findings[0].description


# ═══════════════════════════════════════════════════════════
# P1-1: _safe_float percent support
# ═══════════════════════════════════════════════════════════

class TestSafeFloatPercent:
    def test_percent_ascii(self):
        assert _safe_float("12.5%") == 12.5

    def test_percent_fullwidth(self):
        assert _safe_float("12.5％") == 12.5

    def test_percent_with_spaces(self):
        assert _safe_float(" 12.5% ") == 12.5

    def test_percent_negative_parens(self):
        """括号负数+百分号。"""
        assert _safe_float("(12.5%)") == -12.5

    def test_percent_zero(self):
        assert _safe_float("0%") == 0.0

    def test_percent_100(self):
        assert _safe_float("100.00%") == 100.0

    def test_normal_float_unchanged(self):
        """普通数字不受影响。"""
        assert _safe_float(12.5) == 12.5
        assert _safe_float("12.5") == 12.5

    def test_comma_format_unchanged(self):
        assert _safe_float("1,234.56") == 1234.56


# ═══════════════════════════════════════════════════════════
# P1-2: _extract_provision_increase header-based total col
# ═══════════════════════════════════════════════════════════

class TestProvisionIncreaseHeaderCol:
    def test_prefers_total_column(self):
        """有合计列时优先取合计列。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="pi1", account_name="应收账款", section_title="坏账准备变动",
            headers=["项目", "第一阶段", "第二阶段", "第三阶段", "合计"],
            rows=[
                ["期初余额", 100, 200, 300, 600],
                ["本期计提", 10, 20, 30, 60],
                ["期末余额", 110, 220, 330, 660],
            ],
        )
        result = engine._extract_provision_increase(note)
        assert result is not None
        net, inc, rev = result
        assert net == 60, f"Expected net=60, got {net}"
        assert inc == 60
        assert rev == 0.0

    def test_fallback_last_value(self):
        """无合计列时取最后一个数值。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="pi2", account_name="存货", section_title="跌价准备变动",
            headers=["项目", "金额"],
            rows=[
                ["期初余额", 100],
                ["本期计提", 50],
                ["期末余额", 150],
            ],
        )
        result = engine._extract_provision_increase(note)
        assert result is not None
        net, inc, rev = result
        assert net == 50

    def test_total_col_empty_falls_back(self):
        """合计列为空时回退取最后一个数值。"""
        engine = ReconciliationEngine()
        note = NoteTable(
            id="pi3", account_name="应收账款", section_title="坏账准备变动",
            headers=["项目", "第一阶段", "第二阶段", "第三阶段", "合计"],
            rows=[
                ["期初余额", 100, 200, 300, 600],
                ["本期计提", 10, 20, 30, None],  # 合计列为空
                ["期末余额", 110, 220, 330, 660],
            ],
        )
        result = engine._extract_provision_increase(note)
        assert result is not None
        net, inc, rev = result
        assert net == 30, f"Expected net=30 (last non-null), got {net}"


# ═══════════════════════════════════════════════════════════
# P2-6: RATIO_TOLERANCE
# ═══════════════════════════════════════════════════════════

class TestRatioTolerance:
    def test_constant_value(self):
        assert RATIO_TOLERANCE == 0.15

    def test_tighter_than_amount_tolerance(self):
        assert RATIO_TOLERANCE < TOLERANCE


# ═══════════════════════════════════════════════════════════
# P3-13: _assess_risk constants
# ═══════════════════════════════════════════════════════════

class TestAssessRiskConstants:
    def test_high_ratio(self):
        result = ReconciliationEngine._assess_risk(600, 10000)  # 6%
        assert result == RiskLevel.HIGH

    def test_medium_ratio(self):
        result = ReconciliationEngine._assess_risk(200, 10000)  # 2%
        assert result == RiskLevel.MEDIUM

    def test_low_ratio(self):
        result = ReconciliationEngine._assess_risk(50, 10000)  # 0.5%
        assert result == RiskLevel.LOW

    def test_high_absolute(self):
        result = ReconciliationEngine._assess_risk(15000, None)
        assert result == RiskLevel.HIGH

    def test_medium_absolute(self):
        result = ReconciliationEngine._assess_risk(500, None)
        assert result == RiskLevel.MEDIUM

    def test_low_absolute(self):
        result = ReconciliationEngine._assess_risk(50, None)
        assert result == RiskLevel.LOW


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
