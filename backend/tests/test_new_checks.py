"""Tests for newly added check methods:
- check_equity_change_vs_notes (E-series)
- check_oci_vs_income_statement (X-14)
- check_ecl_three_stage_table (F8-8/8a, F14-4/4a)
- check_maturity_reclassification (X-10, X-11, X-12)
- check_surplus_reserve_consistency (X-7)
- check_impairment_loss_consistency (X-2, X-3)
- check_transfer_consistency (X-4, X-5)
- check_sub_item_detail (D-series)
"""
import uuid
from unittest.mock import MagicMock

import pytest

from app.models.audit_schemas import (
    NoteTable,
    ReportReviewFindingCategory,
    ReportSheetData,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from app.services.reconciliation_engine import ReconciliationEngine

engine = ReconciliationEngine()


def _note(name="应收账款", title=None, headers=None, rows=None):
    return NoteTable(
        id=str(uuid.uuid4()),
        account_name=name,
        section_title=title or f"{name}附注",
        headers=headers or ["项目", "期末余额", "期初余额"],
        rows=rows or [],
    )


def _ts(note_id, rows=None, columns=None, total_indices=None,
        closing_cell=None, opening_cell=None, has_balance=False):
    return TableStructure(
        note_table_id=note_id,
        rows=rows or [],
        columns=columns or [],
        total_row_indices=total_indices or [],
        closing_balance_cell=closing_cell,
        opening_balance_cell=opening_cell,
        has_balance_formula=has_balance,
    )


# ═══════════════════════════════════════════════════════════════
# E-series: check_equity_change_vs_notes
# ═══════════════════════════════════════════════════════════════

class TestCheckEquityChangeVsNotes:
    """E-series: 权益变动表各列 vs 附注期初/期末。"""

    def _make_equity_sheet(self, headers, raw_data):
        """构造一个权益变动表 ReportSheetData。"""
        return ReportSheetData(
            sheet_name="所有者权益变动表",
            statement_type=StatementType.EQUITY_CHANGE,
            headers=headers,
            raw_data=raw_data,
            row_count=len(raw_data),
        )

    def test_consistent_no_findings(self):
        """权益变动表与附注一致时不应产生 findings。"""
        headers = ["项目", "实收资本", "资本公积", "盈余公积", "未分配利润"]
        raw_data = [
            ["一、上年年末余额", 1000, 2000, 500, 3000],
            ["二、本期增减变动", 0, 100, 50, 800],
            ["四、期末余额", 1000, 2100, 550, 3800],
        ]
        sd = self._make_equity_sheet(headers, raw_data)
        sheet_data_map = {"file1": [sd]}

        notes = [
            _note("实收资本", "实收资本①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 1000, 1000]]),
            _note("资本公积", "资本公积①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 2100, 2000]]),
            _note("盈余公积", "盈余公积①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 550, 500]]),
            _note("未分配利润", "未分配利润①明细表", ["项目", "期末余额", "期初余额"],
                  [["调整后", None, 3000], ["合计", 3800, None]]),
        ]
        ts_map = {}
        findings = engine.check_equity_change_vs_notes(sheet_data_map, notes, ts_map)
        assert len(findings) == 0

    def test_mismatch_detected(self):
        """权益变动表与附注不一致时应产生 findings。"""
        headers = ["项目", "实收资本", "盈余公积"]
        raw_data = [
            ["一、上年年末余额", 1000, 500],
            ["四、期末余额", 1000, 600],
        ]
        sd = self._make_equity_sheet(headers, raw_data)
        sheet_data_map = {"file1": [sd]}

        notes = [
            _note("实收资本", "实收资本①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 1000, 1000]]),
            _note("盈余公积", "盈余公积①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 650, 500]]),  # 期末不一致: 600 vs 650
        ]
        ts_map = {}
        findings = engine.check_equity_change_vs_notes(sheet_data_map, notes, ts_map)
        assert len(findings) == 1
        assert "盈余公积" in findings[0].account_name
        assert "期末" in findings[0].location

    def test_no_equity_sheet(self):
        """没有权益变动表时应返回空列表。"""
        sheet_data_map = {"file1": []}
        findings = engine.check_equity_change_vs_notes(sheet_data_map, [], {})
        assert findings == []

    def test_listed_guben_column(self):
        """上市版使用'股本'而非'实收资本'。"""
        headers = ["项目", "股本", "资本公积"]
        raw_data = [
            ["一、上年年末余额", 5000, 2000],
            ["四、期末余额", 5000, 2500],
        ]
        sd = self._make_equity_sheet(headers, raw_data)
        sheet_data_map = {"file1": [sd]}

        notes = [
            _note("股本", "股本①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 5000, 5000]]),
            _note("资本公积", "资本公积①明细表", ["项目", "期末余额", "期初余额"],
                  [["合计", 2500, 2000]]),
        ]
        findings = engine.check_equity_change_vs_notes(sheet_data_map, notes, {})
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# X-14: check_oci_vs_income_statement
# ═══════════════════════════════════════════════════════════════

class TestCheckOciVsIncomeStatement:
    """X-14: 其他综合收益附注 vs 利润表。"""

    def _income_item(self, name, closing):
        return StatementItem(
            id=str(uuid.uuid4()), account_name=name,
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表", closing_balance=closing,
            opening_balance=None, row_index=1,
        )

    def test_consistent(self):
        items = [self._income_item("其他综合收益的税后净额", 150.0)]
        notes = [_note("其他综合收益", "利润表中归属于母公司的其他综合收益",
                       ["项目", "本期金额"],
                       [["利息收入", 50], ["汇兑差额", 100], ["合计", 150]])]
        findings = engine.check_oci_vs_income_statement(items, notes)
        assert len(findings) == 0

    def test_mismatch(self):
        items = [self._income_item("其他综合收益的税后净额", 150.0)]
        notes = [_note("其他综合收益", "利润表中归属于母公司的其他综合收益",
                       ["项目", "本期金额"],
                       [["合计", 200]])]
        findings = engine.check_oci_vs_income_statement(items, notes)
        assert len(findings) == 1
        assert findings[0].difference == -50.0

    def test_no_oci_in_income(self):
        """利润表中没有其他综合收益行时不校验。"""
        items = [self._income_item("营业收入", 10000)]
        notes = [_note("其他综合收益", "其他综合收益附注",
                       ["项目", "本期金额"], [["合计", 200]])]
        findings = engine.check_oci_vs_income_statement(items, notes)
        assert len(findings) == 0

    def test_no_oci_note(self):
        """没有其他综合收益附注时不校验。"""
        items = [self._income_item("其他综合收益的税后净额", 150.0)]
        notes = [_note("应收账款", "应收账款附注", ["项目", "金额"], [["合计", 100]])]
        findings = engine.check_oci_vs_income_statement(items, notes)
        assert len(findings) == 0

    def test_prefers_parent_company_row(self):
        """优先取'归属于母公司所有者的其他综合收益的税后净额'，而非合计行。"""
        items = [
            self._income_item("其他综合收益的税后净额", 0.0),
            self._income_item("归属于母公司所有者的其他综合收益的税后净额", -87984.89),
            self._income_item("（一）不能重分类进损益的其他综合收益", None),
            self._income_item("2. 权益法下不能转损益的其他综合收益", 0.0),
            self._income_item("（二）将重分类进损益的其他综合收益", -87984.89),
            self._income_item("归属于少数股东的其他综合收益的税后净额", 0.0),
        ]
        notes = [_note("其他综合收益", "利润表中归属于母公司的其他综合收益",
                       ["项目", "本期金额"],
                       [["合计", -87984.89]])]
        findings = engine.check_oci_vs_income_statement(items, notes)
        assert len(findings) == 0, (
            f"应取归属于母公司行(-87984.89)而非合计行(0.0): "
            f"{[(f.description,) for f in findings]}"
        )

    def test_fallback_to_total_when_no_parent_row(self):
        """没有'归属于母公司'行时，回退到'其他综合收益的税后净额'合计行。"""
        items = [
            self._income_item("其他综合收益的税后净额", -87984.89),
        ]
        notes = [_note("其他综合收益", "其他综合收益",
                       ["项目", "本期金额"],
                       [["合计", -87984.89]])]
        findings = engine.check_oci_vs_income_statement(items, notes)
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# ECL: check_ecl_three_stage_table
# ═══════════════════════════════════════════════════════════════

class TestCheckEclThreeStageTable:
    """三阶段ECL表横向/纵向校验。"""

    def _ecl_note(self, rows):
        return _note(
            "应收账款", "坏账准备计提情况",
            ["项目", "第一阶段", "第二阶段", "第三阶段", "合计"],
            rows,
        )

    def _dummy_ts(self, note_id):
        return _ts(note_id)

    def test_balanced_ecl_table(self):
        """横向和纵向都平衡的ECL表不应产生 findings。"""
        rows = [
            ["期初余额", 100, 50, 30, 180],
            ["本期计提", 20, 10, 5, 35],
            ["本期转回", 5, 3, 0, 8],
            ["期末余额", 115, 57, 35, 207],
        ]
        note = self._ecl_note(rows)
        ts = self._dummy_ts(note.id)
        findings = engine.check_ecl_three_stage_table(note, ts)
        assert len(findings) == 0

    def test_horizontal_mismatch(self):
        """横向不平衡：各阶段之和 ≠ 合计列。"""
        rows = [
            ["期初余额", 100, 50, 30, 200],  # 100+50+30=180 ≠ 200
            ["期末余额", 100, 50, 30, 180],
        ]
        note = self._ecl_note(rows)
        ts = self._dummy_ts(note.id)
        findings = engine.check_ecl_three_stage_table(note, ts)
        # 应有横向不平衡的 finding
        horizontal = [f for f in findings if "横向" in f.location]
        assert len(horizontal) >= 1

    def test_vertical_mismatch(self):
        """纵向不平衡：期初 + 变动 ≠ 期末。"""
        rows = [
            ["期初余额", 100, 50, 30, 180],
            ["本期计提", 20, 10, 5, 35],
            ["期末余额", 130, 60, 35, 225],  # 第一阶段: 100+20=120 ≠ 130
        ]
        note = self._ecl_note(rows)
        ts = self._dummy_ts(note.id)
        findings = engine.check_ecl_three_stage_table(note, ts)
        vertical = [f for f in findings if "纵向" in f.location]
        assert len(vertical) >= 1

    def test_non_ecl_table_skipped(self):
        """非ECL表应被跳过。"""
        note = _note("固定资产", "固定资产情况",
                     ["项目", "原值", "累计折旧", "账面价值"],
                     [["房屋", 1000, 200, 800]])
        ts = _ts(note.id)
        findings = engine.check_ecl_three_stage_table(note, ts)
        assert len(findings) == 0

    def test_ecl_with_only_two_stages(self):
        """只有两个阶段列也应能校验。"""
        note = _note(
            "债权投资", "减值准备变动情况",
            ["项目", "第一阶段", "第三阶段", "合计"],
            [
                ["期初余额", 100, 30, 130],
                ["本期计提", 10, 5, 15],
                ["期末余额", 110, 35, 145],
            ],
        )
        ts = _ts(note.id)
        findings = engine.check_ecl_three_stage_table(note, ts)
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# X-10/11/12: check_maturity_reclassification
# ═══════════════════════════════════════════════════════════════

class TestCheckMaturityReclassification:
    """X-10/11/12: 一年内到期 vs 各长期科目。"""

    def _bs_item(self, name, closing, opening=None):
        return StatementItem(
            id=str(uuid.uuid4()), account_name=name,
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表", closing_balance=closing,
            opening_balance=opening, row_index=1,
        )

    def test_x11_consistent(self):
        """X-11: 一年内到期的非流动资产汇总表 vs 长期应收款一致。"""
        items = [self._bs_item("货币资金", 10000)]
        notes = [
            _note("一年内到期的非流动资产", "一年内到期的非流动资产汇总表",
                  ["项目", "期末余额"],
                  [["长期应收款", 500], ["合计", 500]]),
            _note("长期应收款", "长期应收款①明细表",
                  ["项目", "期末余额", "期初余额"],
                  [["明细A", 2000, 1500],
                   ["减：一年内到期的长期应收款", 500, 300],
                   ["合计", 1500, 1200]]),
        ]
        ts_map = {}
        findings = engine.check_maturity_reclassification(items, notes, ts_map)
        # X-10 may or may not fire (depends on cash equiv data), but X-11 should be clean
        x11 = [f for f in findings if "X-11" in (f.analysis_reasoning or "")]
        assert len(x11) == 0

    def test_x11_mismatch(self):
        """X-11: 一年内到期 vs 长期应收款不一致。"""
        items = []
        notes = [
            _note("一年内到期的非流动资产", "一年内到期的非流动资产汇总表",
                  ["项目", "期末余额"],
                  [["长期应收款", 500], ["合计", 500]]),
            _note("长期应收款", "长期应收款①明细表",
                  ["项目", "期末余额"],
                  [["减：一年内到期的长期应收款", 600]]),  # 500 vs 600
        ]
        findings = engine.check_maturity_reclassification(items, notes, {})
        x11 = [f for f in findings if "X-11" in (f.analysis_reasoning or "")]
        assert len(x11) == 1


# ═══════════════════════════════════════════════════════════════
# X-7: check_surplus_reserve_consistency
# ═══════════════════════════════════════════════════════════════

class TestCheckSurplusReserveConsistency:
    """X-7: 盈余公积提取 vs 未分配利润。"""

    def test_consistent(self):
        notes = [
            _note("盈余公积", "盈余公积①明细表",
                  ["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
                  [["法定盈余公积", 100, 50, 0, 150],
                   ["任意盈余公积", 200, 30, 0, 230],
                   ["合计", 300, 80, 0, 380]]),
            _note("未分配利润", "未分配利润①明细表",
                  ["项目", "金额"],
                  [["期初未分配利润", 5000],
                   ["提取盈余公积", 80],
                   ["期末未分配利润", 4920]]),
        ]
        findings = engine.check_surplus_reserve_consistency(notes)
        assert len(findings) == 0

    def test_mismatch(self):
        notes = [
            _note("盈余公积", "盈余公积①明细表",
                  ["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
                  [["合计", 300, 80, 0, 380]]),
            _note("未分配利润", "未分配利润①明细表",
                  ["项目", "金额"],
                  [["提取盈余公积", 100]]),  # 80 vs 100
        ]
        findings = engine.check_surplus_reserve_consistency(notes)
        assert len(findings) == 1

    def test_no_surplus_note(self):
        """没有盈余公积附注时不校验。"""
        notes = [_note("应收账款", "应收账款附注")]
        findings = engine.check_surplus_reserve_consistency(notes)
        assert len(findings) == 0



# ═══════════════════════════════════════════════════════════════
# X-4/X-5: check_transfer_consistency
# ═══════════════════════════════════════════════════════════════

class TestCheckTransferConsistency:
    """X-4: 在建工程转固, X-5: 开发支出转无形资产。"""

    def test_x4_consistent(self):
        """在建工程转固金额一致。"""
        notes = [
            _note("在建工程", "在建工程①变动表",
                  ["项目", "工程A", "合计"],
                  [["期初余额", 1000, 1000],
                   ["本期增加", 500, 500],
                   ["转入固定资产", 800, 800],
                   ["期末余额", 700, 700]]),
            _note("固定资产", "固定资产①变动表",
                  ["项目", "房屋", "合计"],
                  [["期初余额", 5000, 5000],
                   ["在建工程转入", 800, 800],
                   ["期末余额", 5800, 5800]]),
        ]
        findings = engine.check_transfer_consistency(notes, {})
        x4 = [f for f in findings if "X-4" in (f.analysis_reasoning or "")]
        assert len(x4) == 0

    def test_x4_mismatch(self):
        """在建工程转固金额不一致。"""
        notes = [
            _note("在建工程", "在建工程①变动表",
                  ["项目", "工程A", "合计"],
                  [["期初余额", 1000, 1000],
                   ["转入固定资产", 800, 800],
                   ["期末余额", 200, 200]]),
            _note("固定资产", "固定资产①变动表",
                  ["项目", "房屋", "合计"],
                  [["期初余额", 5000, 5000],
                   ["在建工程转入", 900, 900],
                   ["期末余额", 5900, 5900]]),  # 800 vs 900
        ]
        findings = engine.check_transfer_consistency(notes, {})
        x4 = [f for f in findings if "X-4" in (f.analysis_reasoning or "")]
        assert len(x4) == 1

    def test_no_cip_table(self):
        """没有在建工程变动表时不校验。"""
        notes = [
            _note("固定资产", "固定资产①变动表",
                  ["项目", "期初余额", "在建工程转入", "期末余额"],
                  [["合计", 5000, 800, 5800]]),
        ]
        findings = engine.check_transfer_consistency(notes, {})
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# X-2/X-3: check_impairment_loss_consistency
# ═══════════════════════════════════════════════════════════════

class TestCheckImpairmentLossConsistency:
    """X-2: 信用减值损失, X-3: 资产减值损失。"""

    def _income_item(self, name, closing):
        return StatementItem(
            id=str(uuid.uuid4()), account_name=name,
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表", closing_balance=closing,
            opening_balance=None, row_index=1,
        )

    def test_x2_consistent(self):
        """信用减值损失与各科目坏账准备计提合计一致。"""
        items = [self._income_item("信用减值损失", -100)]
        notes = [
            _note("应收账款", "坏账准备变动情况",
                  ["项目", "金额"],
                  [["期初余额", 200], ["本期计提", 60], ["期末余额", 260]]),
            _note("其他应收款", "坏账准备变动情况",
                  ["项目", "金额"],
                  [["期初余额", 50], ["本期计提", 40], ["期末余额", 90]]),
        ]
        findings = engine.check_impairment_loss_consistency(items, notes, {})
        x2 = [f for f in findings if "信用减值损失" in f.account_name]
        assert len(x2) == 0

    def test_x2_mismatch(self):
        """信用减值损失与坏账准备计提不一致。"""
        items = [self._income_item("信用减值损失", -100)]
        notes = [
            _note("应收账款", "坏账准备变动情况",
                  ["项目", "金额"],
                  [["期初余额", 200], ["本期计提", 50], ["期末余额", 250]]),
            # 只有50，但利润表是100
        ]
        findings = engine.check_impairment_loss_consistency(items, notes, {})
        x2 = [f for f in findings if "信用减值损失" in f.account_name]
        assert len(x2) == 1

    def test_no_impairment_in_income(self):
        """利润表中没有减值损失行时不校验。"""
        items = [self._income_item("营业收入", 10000)]
        notes = [_note("应收账款", "坏账准备变动情况",
                       ["项目", "金额"], [["本期计提", 50]])]
        findings = engine.check_impairment_loss_consistency(items, notes, {})
        assert len(findings) == 0

    def test_x2_classification_table_excluded(self):
        """分类表（按坏账准备计提方法分类披露）不应被当作变动表。"""
        items = [self._income_item("信用减值损失", -100)]
        notes = [
            # 分类表：标题含"按坏账准备计提方法分类"，不是变动表
            _note("按坏账准备计提方法分类披露应收账款",
                  "（2）按坏账准备计提方法分类披露应收账款",
                  ["类别", "账面余额", "坏账准备", "账面价值"],
                  [["按单项计提坏账准备", 500, 100, 400],
                   ["按组合计提坏账准备", 1000, 50, 950],
                   ["合  计", 1500, 150, 1350]]),
            # 另一个分类表
            _note("采用其他组合方法计提坏账准备的应收账款",
                  "采用其他组合方法计提坏账准备的应收账款",
                  ["组合名称", "账面余额", "坏账准备"],
                  [["账龄组合", 1000, 50]]),
        ]
        findings = engine.check_impairment_loss_consistency(items, notes, {})
        # 没有找到真正的变动表，prov_count=0，不应报差异
        x2 = [f for f in findings if "信用减值损失" in f.account_name]
        assert len(x2) == 0, (
            f"分类表不应被当作变动表: {[(f.description,) for f in x2]}"
        )

    def test_x2_provision_movement_table_matched(self):
        """坏账准备计提情况表应被正确匹配。"""
        items = [self._income_item("信用减值损失", -27152.76)]
        notes = [
            # 正确的变动表
            _note("其他应收款项坏账准备计提情况",
                  "其他应收款项坏账准备计提情况",
                  ["坏账准备", "第一阶段", "第二阶段", "第三阶段", "合计"],
                  [["期初余额", 202491.71, None, 162837.88, 365329.59],
                   ["本期计提", 865.00, 26287.76, None, 27152.76],
                   ["期末余额", 865.00, 228779.47, 162837.88, 392482.35]]),
        ]
        findings = engine.check_impairment_loss_consistency(items, notes, {})
        x2 = [f for f in findings if "信用减值损失" in f.account_name]
        assert len(x2) == 0, (
            f"坏账准备计提情况表应被正确匹配: {[(f.description,) for f in x2]}"
        )


# ═══════════════════════════════════════════════════════════════
# D-series: check_sub_item_detail
# ═══════════════════════════════════════════════════════════════

class TestCheckSubItemDetail:
    """D-series: 报表二级明细 vs 附注明细行。"""

    def test_consistent_sub_item(self):
        """二级明细与附注一致。"""
        from app.models.audit_schemas import MatchingMap, MatchingEntry
        parent_id = str(uuid.uuid4())
        sub_id = str(uuid.uuid4())
        parent = StatementItem(
            id=parent_id, account_name="存货",
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表", closing_balance=1000,
            opening_balance=800, row_index=1,
        )
        sub = StatementItem(
            id=sub_id, account_name="其中：原材料",
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表", closing_balance=300,
            opening_balance=200, row_index=2,
            is_sub_item=True, parent_id=parent_id,
        )
        note = _note("存货", "存货①分类表",
                     ["项目", "期初余额", "期末余额"],
                     [["原材料", 200, 300], ["库存商品", 600, 700], ["合计", 800, 1000]])
        note_ts = _ts(note.id,
                      columns=[
                          TableStructureColumn(col_index=0, semantic="label"),
                          TableStructureColumn(col_index=1, semantic="opening_balance"),
                          TableStructureColumn(col_index=2, semantic="closing_balance"),
                      ])
        mm = MatchingMap(
            entries=[MatchingEntry(
                statement_item_id=parent_id,
                note_table_ids=[note.id],
                match_confidence=1.0,
            )],
        )
        findings = engine.check_sub_item_detail(mm, [parent, sub], [note], {note.id: note_ts})
        assert len(findings) == 0

    def test_mismatch_sub_item(self):
        """二级明细与附注不一致。"""
        from app.models.audit_schemas import MatchingMap, MatchingEntry
        parent_id = str(uuid.uuid4())
        sub_id = str(uuid.uuid4())
        parent = StatementItem(
            id=parent_id, account_name="存货",
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表", closing_balance=1000,
            opening_balance=800, row_index=1,
        )
        sub = StatementItem(
            id=sub_id, account_name="其中：原材料",
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表", closing_balance=350,  # 报表350 vs 附注300
            opening_balance=200, row_index=2,
            is_sub_item=True, parent_id=parent_id,
        )
        note = _note("存货", "存货①分类表",
                     ["项目", "期初余额", "期末余额"],
                     [["原材料", 200, 300], ["合计", 800, 1000]])
        note_ts = _ts(note.id,
                      columns=[
                          TableStructureColumn(col_index=0, semantic="label"),
                          TableStructureColumn(col_index=1, semantic="opening_balance"),
                          TableStructureColumn(col_index=2, semantic="closing_balance"),
                      ])
        mm = MatchingMap(
            entries=[MatchingEntry(
                statement_item_id=parent_id,
                note_table_ids=[note.id],
                match_confidence=1.0,
            )],
        )
        findings = engine.check_sub_item_detail(mm, [parent, sub], [note], {note.id: note_ts})
        assert len(findings) == 1
        assert "原材料" in findings[0].description
        assert findings[0].difference == 50.0
