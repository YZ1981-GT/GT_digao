# -*- coding: utf-8 -*-
"""Tests for gap check methods:
- check_income_tax_adjustment_process (F74-4~F74-6)
- check_oci_detail_structure (F75-3~F75-7)
- check_supplement_depreciation_cross (F83-3~F83-5a)
- check_text_reasonableness (LLM framework, async)
"""
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.audit_schemas import (
    NoteTable,
    ReportReviewFindingCategory,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
)
from app.services.reconciliation_engine import ReconciliationEngine

engine = ReconciliationEngine()


def _note(name="test", title=None, headers=None, rows=None):
    return NoteTable(
        id=str(uuid.uuid4()),
        account_name=name,
        section_title=title or f"{name}附注",
        headers=headers or ["项目", "金额"],
        rows=rows or [],
    )


def _item(name, closing, opening=None, st=StatementType.INCOME_STATEMENT):
    return StatementItem(
        id=str(uuid.uuid4()), account_name=name,
        statement_type=st, sheet_name="利润表",
        closing_balance=closing, opening_balance=opening, row_index=1,
    )


# ═══════════════════════════════════════════════════════════════
# F74-4~F74-6: check_income_tax_adjustment_process
# ═══════════════════════════════════════════════════════════════

class TestCheckIncomeTaxAdjustmentProcess:
    """F74-4~F74-6: 所得税费用调整过程表校验。"""

    def _adj_note(self, rows):
        return _note(
            "所得税费用", "会计利润与所得税费用调整过程",
            ["项目", "本期金额"],
            rows,
        )

    def _detail_note(self, rows):
        return _note(
            "所得税费用", "所得税费用明细",
            ["项目", "本期金额", "上期金额"],
            rows,
        )

    def test_f74_4_consistent(self):
        """F74-4: 利润总额×25% = 按适用税率计算的所得税费用。"""
        adj = self._adj_note([
            ["利润总额", 1000000],
            ["按25%的税率计算的所得税费用", 250000],
            ["不可抵扣的成本费用", 5000],
            ["合计", 255000],
        ])
        findings = engine.check_income_tax_adjustment_process([], [adj])
        f74_4 = [f for f in findings if "F74-4" in (f.analysis_reasoning or "")]
        assert len(f74_4) == 0

    def test_f74_4_mismatch(self):
        """F74-4: 利润总额×25% ≠ 按适用税率计算的所得税费用。"""
        adj = self._adj_note([
            ["利润总额", 1000000],
            ["按适用税率计算的所得税费用", 200000],  # should be 250000
            ["合计", 200000],
        ])
        findings = engine.check_income_tax_adjustment_process([], [adj])
        f74_4 = [f for f in findings if "F74-4" in (f.analysis_reasoning or "")]
        assert len(f74_4) == 1
        assert f74_4[0].difference == -50000.0

    def test_f74_5_consistent(self):
        """F74-5: 调整过程表合计 = 所得税费用明细表合计。"""
        adj = self._adj_note([
            ["利润总额", 1000000],
            ["按25%的税率计算的所得税费用", 250000],
            ["合计", 260000],
        ])
        detail = self._detail_note([
            ["当期所得税费用", 200000, 180000],
            ["递延所得税费用", 60000, 50000],
            ["合计", 260000, 230000],
        ])
        findings = engine.check_income_tax_adjustment_process([], [adj, detail])
        f74_5 = [f for f in findings if "F74-5" in (f.analysis_reasoning or "")]
        assert len(f74_5) == 0

    def test_f74_5_mismatch(self):
        """F74-5: 调整过程表合计 ≠ 所得税费用明细表合计。"""
        adj = self._adj_note([
            ["利润总额", 1000000],
            ["按25%的税率计算的所得税费用", 250000],
            ["合计", 260000],
        ])
        detail = self._detail_note([
            ["当期所得税费用", 200000, 180000],
            ["递延所得税费用", 70000, 50000],
            ["合计", 270000, 230000],  # 270000 ≠ 260000
        ])
        findings = engine.check_income_tax_adjustment_process([], [adj, detail])
        f74_5 = [f for f in findings if "F74-5" in (f.analysis_reasoning or "")]
        assert len(f74_5) == 1

    def test_f74_6_consistent(self):
        """F74-6: 按税率计算 + 各调整项 = 合计。"""
        adj = self._adj_note([
            ["利润总额", 1000000],
            ["按25%的税率计算的所得税费用", 250000],
            ["不可抵扣的成本费用", 5000],
            ["非应税收入的影响", -3000],
            ["合计", 252000],
        ])
        findings = engine.check_income_tax_adjustment_process([], [adj])
        f74_6 = [f for f in findings if "F74-6" in (f.analysis_reasoning or "")]
        assert len(f74_6) == 0

    def test_f74_6_mismatch(self):
        """F74-6: 按税率计算 + 各调整项 ≠ 合计。"""
        adj = self._adj_note([
            ["利润总额", 1000000],
            ["按25%的税率计算的所得税费用", 250000],
            ["不可抵扣的成本费用", 5000],
            ["合计", 260000],  # 250000+5000=255000 ≠ 260000
        ])
        findings = engine.check_income_tax_adjustment_process([], [adj])
        f74_6 = [f for f in findings if "F74-6" in (f.analysis_reasoning or "")]
        assert len(f74_6) == 1

    def test_no_adj_table(self):
        """没有调整过程表时不校验。"""
        detail = self._detail_note([["合计", 260000, 230000]])
        findings = engine.check_income_tax_adjustment_process([], [detail])
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# F75-3~F75-7: check_oci_detail_structure
# ═══════════════════════════════════════════════════════════════

class TestCheckOciDetailStructure:
    """F75-3~F75-7: 其他综合收益明细表结构校验。"""

    def _oci_note(self, rows):
        return _note(
            "其他综合收益", "其他综合收益明细表",
            ["项目", "本期税前金额", "本期所得税", "本期税后净额"],
            rows,
        )

    def test_f75_4_tax_formula_consistent(self):
        """F75-4: 税后 = 税前 - 所得税。"""
        note = self._oci_note([
            ["一、以后不能重分类进损益的其他综合收益", 100, 25, 75],
            ["重新计量设定受益计划变动额", 100, 25, 75],
            ["二、将重分类进损益的其他综合收益", 200, 50, 150],
            ["外币财务报表折算差额", 200, 50, 150],
            ["三、其他综合收益合计", 300, 75, 225],
        ])
        findings = engine.check_oci_detail_structure([note])
        f75_4 = [f for f in findings if "F75-4" in (f.analysis_reasoning or "")]
        assert len(f75_4) == 0

    def test_f75_4_tax_formula_mismatch(self):
        """F75-4: 税后 ≠ 税前 - 所得税。"""
        note = self._oci_note([
            ["一、以后不能重分类进损益的其他综合收益", 100, 25, 75],
            ["重新计量设定受益计划变动额", 100, 25, 80],  # 100-25=75 ≠ 80
            ["二、将重分类进损益的其他综合收益", 0, 0, 0],
            ["三、其他综合收益合计", 100, 25, 80],
        ])
        findings = engine.check_oci_detail_structure([note])
        f75_4 = [f for f in findings if "F75-4" in (f.analysis_reasoning or "")]
        assert len(f75_4) >= 1

    def test_f75_3_total_consistent(self):
        """F75-3: 三 = 一 + 二。"""
        note = self._oci_note([
            ["一、以后不能重分类进损益的其他综合收益", 100, 25, 75],
            ["二、将重分类进损益的其他综合收益", 200, 50, 150],
            ["三、其他综合收益合计", 300, 75, 225],
        ])
        findings = engine.check_oci_detail_structure([note])
        f75_3 = [f for f in findings if "F75-3" in (f.analysis_reasoning or "")]
        assert len(f75_3) == 0

    def test_f75_3_total_mismatch(self):
        """F75-3: 三 ≠ 一 + 二。"""
        note = self._oci_note([
            ["一、以后不能重分类进损益的其他综合收益", 100, 25, 75],
            ["二、将重分类进损益的其他综合收益", 200, 50, 150],
            ["三、其他综合收益合计", 350, 75, 225],  # 350 ≠ 100+200=300
        ])
        findings = engine.check_oci_detail_structure([note])
        f75_3 = [f for f in findings if "F75-3" in (f.analysis_reasoning or "")]
        assert len(f75_3) >= 1

    def test_f75_5_cat1_sub_items(self):
        """F75-5: 一类子项之和 = 一类合计。"""
        note = self._oci_note([
            ["一、以后不能重分类进损益的其他综合收益", 100, 25, 75],
            ["重新计量设定受益计划变动额", 60, 15, 45],
            ["权益法下不能转损益的其他综合收益", 40, 10, 30],
            ["二、将重分类进损益的其他综合收益", 0, 0, 0],
            ["三、其他综合收益合计", 100, 25, 75],
        ])
        findings = engine.check_oci_detail_structure([note])
        f75_5 = [f for f in findings if "F75-5" in (f.analysis_reasoning or "")]
        assert len(f75_5) == 0

    def test_no_oci_note(self):
        """没有其他综合收益明细表时不校验。"""
        note = _note("应收账款", "应收账款附注", ["项目", "金额"], [["合计", 100]])
        findings = engine.check_oci_detail_structure([note])
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# F83-3~F83-5a: check_supplement_depreciation_cross
# ═══════════════════════════════════════════════════════════════

class TestCheckSupplementDepreciationCross:
    """F83-3~F83-5a: 补充资料折旧/摊销精确交叉校验。"""

    def _supp_note(self, rows):
        return _note(
            "现金流量表", "将净利润调节为经营活动现金流量",
            ["项目", "本期金额"],
            rows,
        )

    def _fa_depr_note(self, provision_total):
        return _note(
            "固定资产", "固定资产①累计折旧",
            ["项目", "本期增加", "本期减少", "期末余额"],
            [
                ["房屋及建筑物", provision_total * 0.6, 0, 5000],
                ["机器设备", provision_total * 0.4, 0, 3000],
                ["合计", provision_total, 0, 8000],
            ],
        )

    def _ia_amort_note(self, provision_total):
        return _note(
            "无形资产", "无形资产①累计摊销",
            ["项目", "本期增加", "本期减少", "期末余额"],
            [["合计", provision_total, 0, 2000]],
        )

    def _lt_prepaid_note(self, amort_total):
        return _note(
            "长期待摊费用", "长期待摊费用①明细表",
            ["项目", "期初余额", "本期摊销", "期末余额"],
            [["装修费", 500, amort_total, 200], ["合计", 500, amort_total, 200]],
        )

    def test_f83_3_consistent(self):
        """F83-3: 补充资料固定资产折旧 = 固定资产累计折旧本期计提。"""
        supp = self._supp_note([
            ["净利润", 5000000],
            ["固定资产折旧、油气资产折耗、生产性生物资产折旧", 120000],
        ])
        fa = self._fa_depr_note(120000)
        findings = engine.check_supplement_depreciation_cross([], [supp, fa], {})
        f83_3 = [f for f in findings if "F83-3" in (f.analysis_reasoning or "")]
        assert len(f83_3) == 0

    def test_f83_3_mismatch(self):
        """F83-3: 补充资料固定资产折旧 ≠ 固定资产累计折旧本期计提。"""
        supp = self._supp_note([
            ["固定资产折旧、油气资产折耗、生产性生物资产折旧", 130000],
        ])
        fa = self._fa_depr_note(120000)  # 130000 vs 120000
        findings = engine.check_supplement_depreciation_cross([], [supp, fa], {})
        f83_3 = [f for f in findings if "F83-3" in (f.analysis_reasoning or "")]
        assert len(f83_3) == 1
        assert f83_3[0].difference == 10000.0

    def test_f83_4_consistent(self):
        """F83-4: 补充资料无形资产摊销 = 无形资产累计摊销本期计提。"""
        supp = self._supp_note([
            ["无形资产摊销", 50000],
        ])
        ia = self._ia_amort_note(50000)
        findings = engine.check_supplement_depreciation_cross([], [supp, ia], {})
        f83_4 = [f for f in findings if "F83-4" in (f.analysis_reasoning or "")]
        assert len(f83_4) == 0

    def test_f83_5_consistent(self):
        """F83-5: 补充资料长期待摊费用摊销 = 长期待摊费用本期摊销。"""
        supp = self._supp_note([
            ["长期待摊费用摊销", 300],
        ])
        lt = self._lt_prepaid_note(300)
        findings = engine.check_supplement_depreciation_cross([], [supp, lt], {})
        f83_5 = [f for f in findings if "F83-5" in (f.analysis_reasoning or "")]
        assert len(f83_5) == 0

    def test_f83_5_mismatch(self):
        """F83-5: 补充资料长期待摊费用摊销 ≠ 长期待摊费用本期摊销。"""
        supp = self._supp_note([
            ["长期待摊费用摊销", 400],
        ])
        lt = self._lt_prepaid_note(300)  # 400 vs 300
        findings = engine.check_supplement_depreciation_cross([], [supp, lt], {})
        f83_5 = [f for f in findings if "F83-5" in (f.analysis_reasoning or "")]
        assert len(f83_5) == 1

    def test_no_supplement_note(self):
        """没有补充资料表时不校验。"""
        fa = self._fa_depr_note(120000)
        findings = engine.check_supplement_depreciation_cross([], [fa], {})
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════
# LLM text reasonableness: check_text_reasonableness
# ═══════════════════════════════════════════════════════════════

class TestCheckTextReasonableness:
    """LLM文本合理性审核框架测试。"""

    def test_no_openai_service(self):
        """没有openai_service时返回空。"""
        result = asyncio.get_event_loop().run_until_complete(
            engine.check_text_reasonableness([], None)
        )
        assert result == []

    def test_no_matching_tables(self):
        """没有匹配的表格时返回空。"""
        note = _note("货币资金", "货币资金分类表", ["项目", "期末余额"], [["合计", 1000]])
        mock_oai = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(
            engine.check_text_reasonableness([note], mock_oai)
        )
        assert result == []

    def test_pattern_matching(self):
        """验证表格模式匹配逻辑。"""
        # 单项计提表应匹配
        note1 = _note("应收账款", "单项计提坏账准备",
                       ["项目", "账面余额", "坏账准备", "计提理由"],
                       [["公司A", 1000, 500, "经营困难"]])
        pattern = engine._match_text_check_pattern(note1)
        assert pattern is not None
        assert "单项计提" in pattern["table_keywords"][0]

        # 普通表格不匹配
        note2 = _note("货币资金", "货币资金分类表")
        pattern2 = engine._match_text_check_pattern(note2)
        assert pattern2 is None

    def test_llm_finds_issues(self):
        """LLM返回问题时应生成findings。"""
        note = _note("应收账款", "单项计提坏账准备",
                      ["项目", "账面余额", "坏账准备", "计提理由"],
                      [["某公司", 1000, 500, "经营困难"]])

        # Mock openai_service
        async def mock_stream(*args, **kwargs):
            yield '[{"index": 1, "ok": false, "issue": "公司名称不完整，应使用全称"}]'

        mock_oai = MagicMock()
        mock_oai.stream_chat_completion = mock_stream

        result = asyncio.get_event_loop().run_until_complete(
            engine.check_text_reasonableness([note], mock_oai)
        )
        assert len(result) >= 1
        assert "LLM审核" in result[0].description

    def test_llm_all_ok(self):
        """LLM返回全部ok时不应生成findings。"""
        note = _note("应收账款", "单项计提坏账准备",
                      ["项目", "账面余额", "坏账准备", "计提理由"],
                      [["北京某某有限公司", 1000, 500, "该公司已进入破产清算程序"]])

        async def mock_stream(*args, **kwargs):
            yield '[{"index": 1, "ok": true, "issue": ""}]'

        mock_oai = MagicMock()
        mock_oai.stream_chat_completion = mock_stream

        result = asyncio.get_event_loop().run_until_complete(
            engine.check_text_reasonableness([note], mock_oai)
        )
        assert len(result) == 0

    def test_skip_zero_amount_rows(self):
        """金额为0的行应跳过。"""
        note = _note("应收账款", "单项计提坏账准备",
                      ["项目", "账面余额", "坏账准备", "计提理由"],
                      [["某公司", 0, 0, "经营困难"]])

        mock_oai = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(
            engine.check_text_reasonableness([note], mock_oai)
        )
        assert len(result) == 0

    def test_skip_total_rows(self):
        """合计行应跳过。"""
        note = _note("应收账款", "单项计提坏账准备",
                      ["项目", "账面余额", "坏账准备", "计提理由"],
                      [["合计", 1000, 500, ""]])

        mock_oai = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(
            engine.check_text_reasonableness([note], mock_oai)
        )
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════
# Edge cases and regression tests
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """边界情况测试。"""

    def test_income_tax_custom_rate(self):
        """F74-4: 自定义税率（如15%高新技术企业）。"""
        adj = _note(
            "所得税费用", "会计利润与所得税费用调整过程",
            ["项目", "本期金额"],
            [
                ["利润总额", 1000000],
                ["按15%的税率计算的所得税费用", 150000],
                ["合计", 155000],
            ],
        )
        findings = engine.check_income_tax_adjustment_process([], [adj])
        f74_4 = [f for f in findings if "F74-4" in (f.analysis_reasoning or "")]
        # 应该不报错，因为 1000000 * 15% = 150000
        assert len(f74_4) == 0

    def test_oci_with_reclassification(self):
        """F75-6: 二类子项 - 前期转入 = 小计。"""
        note = _note(
            "其他综合收益", "其他综合收益明细表",
            ["项目", "本期税前金额", "本期所得税", "本期税后净额"],
            [
                ["一、以后不能重分类进损益的其他综合收益", 50, 10, 40],
                ["二、将重分类进损益的其他综合收益", 100, 20, 80],
                ["外币财务报表折算差额", 120, 30, 90],
                ["减：前期计入其他综合收益当期转入损益", 20, 10, 10],
                ["小计", 100, 20, 80],
                ["三、其他综合收益合计", 150, 30, 120],
            ],
        )
        findings = engine.check_oci_detail_structure([note])
        f75_6 = [f for f in findings if "F75-6" in (f.analysis_reasoning or "")]
        assert len(f75_6) == 0

    def test_supplement_depr_with_rou_asset(self):
        """F83-5a: 使用权资产折旧。"""
        supp = _note(
            "现金流量表", "将净利润调节为经营活动现金流量",
            ["项目", "本期金额"],
            [["使用权资产折旧", 80000]],
        )
        rou = _note(
            "使用权资产", "使用权资产①累计折旧",
            ["项目", "本期增加", "本期减少", "期末余额"],
            [["合计", 80000, 0, 200000]],
        )
        findings = engine.check_supplement_depreciation_cross([], [supp, rou], {})
        f83_5a = [f for f in findings if "F83-5a" in (f.analysis_reasoning or "")]
        assert len(f83_5a) == 0

    def test_text_check_multiple_patterns(self):
        """验证多个表格同时匹配不同模式。"""
        note1 = _note("应收账款", "单项计提坏账准备",
                       ["项目", "账面余额", "计提理由"],
                       [["公司A", 1000, "经营困难"]])
        note2 = _note("固定资产", "固定资产清理",
                       ["项目", "账面价值", "转入清理的原因"],
                       [["设备X", 5000, "已报废"]])

        p1 = engine._match_text_check_pattern(note1)
        p2 = engine._match_text_check_pattern(note2)
        assert p1 is not None
        assert p2 is not None
        assert p1 != p2

    def test_supplement_no_source_note(self):
        """补充资料有折旧行但找不到对应科目附注时不报错。"""
        supp = _note(
            "现金流量表", "将净利润调节为经营活动现金流量",
            ["项目", "本期金额"],
            [["固定资产折旧、油气资产折耗、生产性生物资产折旧", 120000]],
        )
        # 没有固定资产附注
        findings = engine.check_supplement_depreciation_cross([], [supp], {})
        assert len(findings) == 0
