# -*- coding: utf-8 -*-
"""Tests for preset-based template structure comparison feature.

验证 ReportReviewEngine._compare_preset_columns() 方法：
将实际附注表格 headers 与预设公式的 template_columns 对比，
仅检查公式关键列（opening/movement/closing），skip/label 列不报差异。
"""
import sys
sys.path.insert(0, ".")

from app.services.report_review_engine import ReportReviewEngine
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.models.audit_schemas import NoteTable


def _note(id="t1", name="", title="", headers=None, rows=None):
    return NoteTable(
        id=id,
        account_name=name,
        section_title=title,
        headers=headers or [],
        rows=rows or [],
    )


# ─── _find_preset_for_note 集成测试 ───

class TestPresetMatching:
    """验证 _find_preset_for_note 能正确匹配预设。"""

    def test_long_term_equity_detail(self):
        note = _note(name="长期股权投资", title="长期股权投资明细")
        preset = TableStructureAnalyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "长期股权投资明细"

    def test_construction_in_progress(self):
        note = _note(name="在建工程", title="重要在建工程项目变动情况")
        preset = TableStructureAnalyzer._find_preset_for_note(note)
        assert preset is not None

    def test_no_preset_for_cash(self):
        note = _note(name="货币资金", title="货币资金")
        preset = TableStructureAnalyzer._find_preset_for_note(note)
        assert preset is None


# ─── _compare_preset_columns 核心测试 ───

class TestComparePresetColumns:
    """测试预设公式列与实际表头的对比。"""

    def _get_preset(self, name, title):
        note = _note(name=name, title=title)
        return TableStructureAnalyzer._find_preset_for_note(note)

    def test_exact_match_no_diff(self):
        """实际表头完全匹配预设公式列，无差异。"""
        preset = self._get_preset("长期待摊费用", "长期待摊费用")
        assert preset is not None
        note = _note(
            id="t1", name="长期待摊费用", title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加", "本期摊销", "其他减少", "期末余额"],
            rows=[["装修费", 100, 20, 10, 0, 110]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is None

    def test_missing_movement_column(self):
        """实际表头缺少预设中的变动列。"""
        preset = self._get_preset("长期待摊费用", "长期待摊费用")
        assert preset is not None
        # 缺少"本期摊销"和"其他减少"
        note = _note(
            id="t2", name="长期待摊费用", title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加", "期末余额"],
            rows=[["装修费", 100, 20, 120]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is not None
        assert len(diff["missing_cols"]) >= 1
        # 应该报告缺少摊销列
        missing_text = " ".join(diff["missing_cols"])
        assert "摊销" in missing_text

    def test_missing_opening_column(self):
        """实际表头缺少期初列。"""
        preset = self._get_preset("长期待摊费用", "长期待摊费用")
        assert preset is not None
        note = _note(
            id="t3", name="长期待摊费用", title="长期待摊费用",
            headers=["项目", "本期增加", "本期摊销", "其他减少", "期末余额"],
            rows=[["装修费", 20, 10, 0, 110]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is not None
        missing_text = " ".join(diff["missing_cols"])
        assert "期初" in missing_text

    def test_extra_column_detected(self):
        """实际表头有预设未定义的额外列。"""
        preset = self._get_preset("长期待摊费用", "长期待摊费用")
        assert preset is not None
        note = _note(
            id="t4", name="长期待摊费用", title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加", "本期摊销", "其他减少", "期末余额", "备注说明"],
            rows=[["装修费", 100, 20, 10, 0, 110, ""]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is not None
        assert "备注说明" in diff["extra_cols"]

    def test_skip_columns_ignored(self):
        """预设中 skip 列缺失不报差异。"""
        preset = self._get_preset("长期股权投资", "长期股权投资明细")
        assert preset is not None
        # 包含所有公式关键列，但缺少 skip 列（减值准备期初/期末余额）
        note = _note(
            id="t5", name="长期股权投资", title="长期股权投资明细",
            headers=[
                "被投资单位", "期初余额(账面价值)",
                "追加投资", "减少投资", "权益法下确认的投资损益",
                "其他综合收益调整", "其他权益变动", "宣告发放现金股利或利润",
                "计提减值准备", "其他",
                "期末余额(账面价值)",
            ],
            rows=[["子公司A", 1000, 200, 0, 50, 10, 5, 20, 0, 0, 1245]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is None

    def test_fuzzy_header_match(self):
        """模糊匹配：实际表头用不同措辞但含相同关键词。"""
        preset = self._get_preset("存货", "存货跌价准备")
        assert preset is not None
        note = _note(
            id="t6", name="存货", title="存货跌价准备变动",
            headers=["项目", "年初余额", "本期计提", "本期其他增加", "本期转回或转销", "本期其他减少", "年末余额"],
            rows=[["原材料", 100, 20, 5, 10, 0, 115]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        # 年初/年末 应匹配 期初/期末，计提/转回 应匹配
        assert diff is None

    def test_too_few_headers_skipped(self):
        """表头少于3列时跳过。"""
        preset = {"template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初"},
            {"role": "closing", "sign": "=", "name": "期末"},
        ]}
        note = _note(id="t7", name="测试", title="测试", headers=["项目", "金额"])
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is None

    def test_diff_output_structure(self):
        """验证差异输出的数据结构。"""
        preset = self._get_preset("在建工程", "重要在建工程项目变动")
        assert preset is not None
        # 缺少"其他减少"列
        note = _note(
            id="t8", name="在建工程", title="在建工程变动",
            headers=["工程名称", "预算数", "期初余额", "本期增加", "转入固定资产", "期末余额"],
            rows=[["工程A", 500, 100, 50, 30, 120]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is not None
        assert diff["account_name"] == "在建工程"
        assert diff["note_id"] == "t8"
        assert "preset_name" in diff
        assert "formula" in diff
        assert "actual_col_count" in diff
        assert "preset_formula_col_count" in diff
        assert "matched_formula_col_count" in diff
        assert "missing_cols" in diff
        assert "extra_cols" in diff
        assert "description" in diff
        # 应该报告缺少"其他减少"
        missing_text = " ".join(diff["missing_cols"])
        assert "其他减少" in missing_text

    def test_no_preset_returns_none(self):
        """没有匹配预设的表格，传入空预设不报差异。"""
        note = _note(
            id="t9", name="货币资金", title="货币资金",
            headers=["项目", "期末余额", "期初余额"],
            rows=[["库存现金", 100, 80]],
        )
        # 直接传一个无 formula_cols 的预设
        preset = {"template_columns": [{"role": "label", "name": "项目"}]}
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is None

    def test_construction_with_all_formula_cols(self):
        """在建工程包含所有公式列，无差异。"""
        preset = self._get_preset("在建工程", "重要在建工程项目变动")
        assert preset is not None
        note = _note(
            id="t10", name="在建工程", title="在建工程变动",
            headers=["工程名称", "预算数", "期初余额", "本期增加", "转入固定资产", "其他减少", "期末余额",
                     "工程累计投入占预算比例", "工程进度"],
            rows=[["工程A", 500, 100, 50, 30, 0, 120, "80%", "90%"]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is None

    def test_development_expenditure_missing_cols(self):
        """开发支出缺少多个变动列。"""
        preset = self._get_preset("开发支出", "开发支出")
        assert preset is not None
        note = _note(
            id="t11", name="开发支出", title="开发支出",
            headers=["项目", "期初余额", "期末余额"],
            rows=[["项目A", 100, 120]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is not None
        # 应该缺少多个变动列
        assert len(diff["missing_cols"]) >= 2

    def test_goodwill_impairment_provision(self):
        """商誉减值准备完全匹配。"""
        preset = self._get_preset("商誉", "商誉减值准备")
        assert preset is not None
        note = _note(
            id="t12", name="商誉", title="商誉减值准备变动",
            headers=["被投资单位", "期初余额", "计提", "其他增加", "处置", "其他减少", "期末余额"],
            rows=[["子公司B", 50, 10, 0, 0, 0, 60]],
        )
        diff = ReportReviewEngine._compare_preset_columns(note, preset)
        assert diff is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
