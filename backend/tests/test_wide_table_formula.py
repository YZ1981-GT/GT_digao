"""宽表横向公式校验 + 权益法投资损益跨科目核对 测试。

覆盖：
- is_wide_table_candidate 候选检测
- _find_preset_for_note 预设匹配
- check_wide_table_formula 本地数值验证
- check_equity_method_income_consistency 三方交叉核对
"""
import uuid

import pytest

from app.models.audit_schemas import (
    NoteTable,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from app.services.reconciliation_engine import ReconciliationEngine
from app.services.table_structure_analyzer import TableStructureAnalyzer


engine = ReconciliationEngine()
analyzer = TableStructureAnalyzer()


# ─── helpers ───

def _note(name="长期股权投资", title=None, headers=None, rows=None):
    return NoteTable(
        id=str(uuid.uuid4()),
        account_name=name,
        section_title=title or f"{name}明细",
        headers=headers or [],
        rows=rows or [],
    )


def _item(name, closing=None, opening=None, stmt_type=StatementType.INCOME_STATEMENT):
    return StatementItem(
        id=str(uuid.uuid4()),
        account_name=name,
        statement_type=stmt_type,
        sheet_name="利润表",
        closing_balance=closing,
        opening_balance=opening,
        row_index=1,
    )


def _ts_simple(note_id, num_cols=3, has_balance=False):
    return TableStructure(
        note_table_id=note_id,
        rows=[TableStructureRow(row_index=0, role="data", label="A")],
        columns=[TableStructureColumn(col_index=i, semantic="other") for i in range(num_cols)],
        total_row_indices=[],
        subtotal_row_indices=[],
        has_balance_formula=has_balance,
        structure_confidence="high",
    )


# ─── is_wide_table_candidate 测试 ───

class TestIsWideTableCandidate:
    def test_too_few_columns(self):
        """列数 < 5 不是宽表候选"""
        note = _note(headers=["项目", "期初", "期末"])
        assert not analyzer.is_wide_table_candidate(note)

    def test_5_cols_with_keyword(self):
        """5列且科目匹配关键词 → 是宽表候选"""
        note = _note(
            name="长期待摊费用",
            title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加额", "本期摊销额", "期末余额"],
        )
        assert analyzer.is_wide_table_candidate(note)

    def test_matching_keyword_6_cols(self):
        """科目匹配关键词且列数 ≥ 6"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初", "追加", "减少", "损益", "期末"],
        )
        assert analyzer.is_wide_table_candidate(note)

    def test_already_has_balance_formula_under_8_cols(self):
        """已有 has_balance_formula 且列数 < 8，跳过"""
        note = _note(
            name="长期待摊费用",
            headers=["项目", "期初", "增加", "摊销", "减少", "期末"],
        )
        ts = _ts_simple(note.id, num_cols=6, has_balance=True)
        assert not analyzer.is_wide_table_candidate(note, ts)

    def test_already_has_balance_formula_8_plus_cols(self):
        """已有 has_balance_formula 但列数 ≥ 8，仍需宽表分析"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["名称", "期初", "减值期初", "追加", "减少", "损益", "其他", "期末"],
        )
        ts = _ts_simple(note.id, num_cols=8, has_balance=True)
        assert analyzer.is_wide_table_candidate(note, ts)

    def test_generic_wide_table_8_cols(self):
        """通用检测：含期初/期末且列数 ≥ 8"""
        note = _note(
            name="某特殊科目",
            title="某特殊科目变动",
            headers=["项目", "期初余额", "增加1", "增加2", "减少1", "减少2", "其他", "期末余额"],
        )
        assert analyzer.is_wide_table_candidate(note)

    def test_no_keyword_no_period_headers(self):
        """不匹配关键词且无期初/期末表头"""
        note = _note(
            name="某科目",
            title="某科目",
            headers=["项目", "金额1", "金额2", "金额3", "金额4", "金额5", "金额6", "金额7"],
        )
        assert not analyzer.is_wide_table_candidate(note)

    def test_classification_table_not_wide(self):
        """分类表（如按组合计提坏账准备）不应被识别为宽表"""
        note = _note(
            name="其他应收款",
            title="采用其他组合方法计提坏账准备的其他应收款",
            headers=["组合名称", "账面余额", "坏账准备", "计提比例(%)",
                     "期初金额", "本期计提金额", "计提比例(%)", "期末金额"],
        )
        assert not analyzer.is_wide_table_candidate(note)

    def test_bad_debt_provision_table_not_wide(self):
        """坏账准备余额对照表（无变动列）不应被识别为宽表"""
        note = _note(
            name="应收账款",
            title="坏账准备",
            headers=["类别", "期末账面余额", "期末坏账准备", "期初账面余额",
                     "期初坏账准备", "计提比例(%)", "账面价值"],
        )
        assert not analyzer.is_wide_table_candidate(note)


# ─── _find_preset_for_note 测试 ───

class TestFindPreset:
    def test_equity_investment_detail(self):
        """长期股权投资明细匹配预设"""
        note = _note(name="长期股权投资", title="长期股权投资明细")
        preset = analyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "长期股权投资明细"

    def test_construction_in_progress(self):
        """在建工程项目变动匹配预设"""
        note = _note(name="在建工程", title="重要在建工程项目变动情况")
        preset = analyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "在建工程项目变动"

    def test_long_term_prepaid(self):
        """长期待摊费用匹配预设"""
        note = _note(name="长期待摊费用", title="长期待摊费用")
        preset = analyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "长期待摊费用"

    def test_dev_expense(self):
        """开发支出匹配预设"""
        note = _note(name="开发支出", title="开发支出")
        preset = analyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "开发支出"

    def test_inventory_provision(self):
        """存货跌价准备匹配预设"""
        note = _note(name="存货", title="存货跌价准备及合同履约成本减值准备")
        preset = analyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "存货跌价准备变动"

    def test_exclude_title_keywords(self):
        """排除关键词生效：开发支出减值准备不匹配开发支出预设"""
        note = _note(name="开发支出", title="开发支出减值准备")
        preset = analyzer._find_preset_for_note(note)
        assert preset is None

    def test_no_match(self):
        """不匹配任何预设"""
        note = _note(name="应收账款", title="应收账款")
        preset = analyzer._find_preset_for_note(note)
        assert preset is None

    def test_parent_company_equity_investment(self):
        """母公司对联营合营企业投资匹配预设"""
        note = _note(name="长期股权投资", title="对联营、合营企业投资")
        preset = analyzer._find_preset_for_note(note)
        assert preset is not None
        assert preset["name"] == "长期股权投资明细"


# ─── try_build_formula_from_preset 规则匹配测试 ───

class TestBuildFormulaFromPreset:
    def test_equity_investment_13_cols(self):
        """长期股权投资明细表13列规则匹配"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初余额(账面价值)", "减值准备期初余额",
                     "追加投资", "减少投资", "权益法下确认的投资损益",
                     "其他综合收益调整", "其他权益变动", "宣告发放现金股利或利润",
                     "计提减值准备", "其他", "期末余额(账面价值)", "减值准备期末余额"],
            rows=[
                ["A公司", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 1185, 50],
                ["合计", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 1185, 50],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        assert result["formula_type"] == "movement"

        cols = result["columns"]
        # 验证 opening 和 closing 列正确
        opening = [c for c in cols if c["role"] == "opening"]
        closing = [c for c in cols if c["role"] == "closing"]
        assert len(opening) == 1
        assert len(closing) == 1
        assert "期初" in opening[0]["name"]
        assert "期末" in closing[0]["name"]

        # 验证 movement 列
        movements = [c for c in cols if c["role"] == "movement"]
        movement_names = [c["name"] for c in movements]
        assert any("追加" in n for n in movement_names)
        assert any("减少" in n for n in movement_names)
        assert any("投资损益" in n for n in movement_names)

        # 验证 skip 列（减值准备）
        skips = [c for c in cols if c["role"] == "skip"]
        assert any("减值" in c["name"] for c in skips)

        # 用 check_wide_table_formula 验证公式正确性
        # 1000 + 200 - 100 + 80 + 20 + 10 - 30 - 0 + 5 = 1185
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_equity_investment_formula_error_detected(self):
        """长期股权投资明细表规则匹配后能检测出公式错误"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初余额(账面价值)", "减值准备期初余额",
                     "追加投资", "减少投资", "权益法下确认的投资损益",
                     "其他综合收益调整", "其他权益变动", "宣告发放现金股利或利润",
                     "计提减值准备", "其他", "期末余额(账面价值)", "减值准备期末余额"],
            rows=[
                ["A公司", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 9999, 50],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 1
        assert "宽表横向公式不平" in findings[0].description

    def test_construction_in_progress(self):
        """在建工程项目变动规则匹配"""
        note = _note(
            name="在建工程",
            title="重要在建工程项目变动情况",
            headers=["工程名称", "期初余额", "本期增加", "转入固定资产",
                     "其他减少", "利息资本化累计金额", "本期利息资本化金额",
                     "本期利息资本化率%", "期末余额"],
            rows=[
                ["厂房工程", 5000, 2000, 1000, 500, 100, 50, 5, 5500],
                ["合计", 5000, 2000, 1000, 500, 100, 50, 5, 5500],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None

        # 验证公式：5000 + 2000 - 1000 - 500 = 5500
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_long_term_prepaid(self):
        """长期待摊费用规则匹配"""
        note = _note(
            name="长期待摊费用",
            title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加", "本期摊销",
                     "其他减少", "期末余额"],
            rows=[
                ["装修费", 100, 20, 30, 0, 90],
                ["合计", 100, 20, 30, 0, 90],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_long_term_prepaid_with_e_suffix(self):
        """长期待摊费用 — 表头带"额"后缀（如"本期增加额"）"""
        note = _note(
            name="长期待摊费用",
            title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加额", "本期摊销额",
                     "其他减少额", "期末余额"],
            rows=[
                ["装修费", 100, 20, 30, 0, 90],
                ["合计", 100, 20, 30, 0, 90],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        # 验证公式结构正确
        cols = result["columns"]
        movement_cols = [c for c in cols if c["role"] == "movement"]
        assert len(movement_cols) == 3  # 本期增加额(+), 本期摊销额(-), 其他减少额(-)
        plus_cols = [c for c in movement_cols if c["sign"] == "+"]
        minus_cols = [c for c in movement_cols if c["sign"] == "-"]
        assert len(plus_cols) == 1  # 本期增加额
        assert len(minus_cols) == 2  # 本期摊销额, 其他减少额
        # 验证公式计算正确
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_long_term_prepaid_unbalanced(self):
        """长期待摊费用 — 横向公式不平衡应报错"""
        note = _note(
            name="长期待摊费用",
            title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加额", "本期摊销额",
                     "其他减少额", "期末余额"],
            rows=[
                ["装修费", 100, 20, 30, 0, 999],  # 应为90，实际999
                ["合计", 100, 20, 30, 0, 999],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 2  # 两行都不平
        assert all("宽表横向公式不平" in f.description for f in findings)

    def test_long_term_prepaid_5_cols(self):
        """长期待摊费用 — 5列（无"其他减少"列）也能匹配预设"""
        note = _note(
            name="长期待摊费用",
            title="长期待摊费用",
            headers=["项目", "期初余额", "本期增加额", "本期摊销额", "期末余额"],
            rows=[
                ["装修费", 100, 20, 30, 90],
                ["合计", 100, 20, 30, 90],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        # 验证公式结构：只有2个movement列（增加+, 摊销-）
        cols = result["columns"]
        movement_cols = [c for c in cols if c["role"] == "movement"]
        assert len(movement_cols) == 2
        plus_cols = [c for c in movement_cols if c["sign"] == "+"]
        minus_cols = [c for c in movement_cols if c["sign"] == "-"]
        assert len(plus_cols) == 1  # 本期增加额
        assert len(minus_cols) == 1  # 本期摊销额
        # 验证公式计算正确: 100 + 20 - 30 = 90
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_no_preset_returns_none(self):
        """不匹配任何预设时返回 None"""
        note = _note(
            name="应收账款",
            title="应收账款",
            headers=["项目", "期初", "增加", "减少", "期末", "备注"],
            rows=[["A", 100, 50, 30, 120, ""]],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is None

    def test_too_few_columns_returns_none(self):
        """列数不足时返回 None"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初", "期末"],
            rows=[["A", 100, 100]],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is None

    def test_equity_investment_variant_headers(self):
        """长期股权投资明细表变体表头（简化列名）"""
        note = _note(
            name="长期股权投资",
            title="对联营企业投资",
            headers=["被投资单位", "年初余额", "减值年初",
                     "追加投资", "减少投资", "投资损益",
                     "其他综合收益", "其他权益变动", "现金股利",
                     "计提减值", "其他", "年末余额", "减值年末"],
            rows=[
                ["A公司", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 1185, 50],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None

        # 验证 opening 用"年初"，closing 用"年末"
        opening = [c for c in result["columns"] if c["role"] == "opening"]
        closing = [c for c in result["columns"] if c["role"] == "closing"]
        assert "年初" in opening[0]["name"]
        assert "年末" in closing[0]["name"]

        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_construction_in_progress_category_sum(self):
        """上市版在建工程：列为各工程项目+合计，应识别为 category_sum"""
        note = _note(
            name="在建工程",
            title="重要在建工程项目变动情况",
            headers=["项目", "厂房工程", "设备安装", "技改工程",
                     "办公楼装修", "信息系统", "合计"],
            rows=[
                ["期初余额", 5000, 3000, 2000, 1000, 500, 11500],
                ["本期增加", 1000, 500, 300, 200, 100, 2100],
                ["转入固定资产", 2000, 1000, 500, 0, 0, 3500],
                ["其他减少", 0, 0, 0, 0, 0, 0],
                ["期末余额", 4000, 2500, 1800, 1200, 600, 10100],
                ["合计", 4000, 2500, 1800, 1200, 600, 10100],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        assert result["formula_type"] == "category_sum"

        data_cols = [c for c in result["columns"] if c["role"] == "data"]
        total_cols = [c for c in result["columns"] if c["role"] == "total"]
        assert len(data_cols) == 5
        assert len(total_cols) == 1
        assert total_cols[0]["name"] == "合计"

        # 验证公式正确性
        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_equity_investment_category_sum(self):
        """上市版长期股权投资：列为各被投资单位+合计，应识别为 category_sum"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["项目", "A子公司", "B联营企业", "C合营企业",
                     "D子公司", "E联营企业", "合计"],
            rows=[
                ["期初余额(账面价值)", 10000, 5000, 3000, 2000, 1000, 21000],
                ["追加投资", 0, 1000, 0, 500, 0, 1500],
                ["投资损益", 0, 200, 100, 0, 50, 350],
                ["期末余额(账面价值)", 10000, 6200, 3100, 2500, 1050, 22850],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        assert result["formula_type"] == "category_sum"

        data_cols = [c for c in result["columns"] if c["role"] == "data"]
        total_cols = [c for c in result["columns"] if c["role"] == "total"]
        assert len(data_cols) == 5
        assert len(total_cols) == 1

        findings = engine.check_wide_table_formula(note, result)
        assert len(findings) == 0

    def test_movement_not_misdetected_as_category_sum(self):
        """国企版长期股权投资明细（含期初/期末列）不应被误判为 category_sum"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初余额(账面价值)", "减值准备期初余额",
                     "追加投资", "减少投资", "权益法下确认的投资损益",
                     "其他综合收益调整", "其他权益变动", "宣告发放现金股利或利润",
                     "计提减值准备", "其他", "期末余额(账面价值)", "减值准备期末余额"],
            rows=[
                ["A公司", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 1185, 50],
            ],
        )
        result = analyzer.try_build_formula_from_preset(note)
        assert result is not None
        # 应该是 movement，不是 category_sum
        assert result["formula_type"] == "movement"


# ─── check_wide_table_formula 测试 ───

class TestCheckWideTableFormula:
    def _make_formula(self, columns, data_row_start=0):
        return {"columns": columns, "data_row_start": data_row_start}

    def test_balanced_row(self):
        """横向公式平衡：期初100 + 增加50 - 减少30 = 期末120"""
        note = _note(
            headers=["项目", "期初", "增加", "减少", "期末"],
            rows=[["A公司", 100, 50, 30, 120]],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "movement", "sign": "+", "name": "增加"},
            {"col_index": 3, "role": "movement", "sign": "-", "name": "减少"},
            {"col_index": 4, "role": "closing", "sign": "=", "name": "期末"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_unbalanced_row(self):
        """横向公式不平衡"""
        note = _note(
            headers=["项目", "期初", "增加", "减少", "期末"],
            rows=[["A公司", 100, 50, 30, 999]],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "movement", "sign": "+", "name": "增加"},
            {"col_index": 3, "role": "movement", "sign": "-", "name": "减少"},
            {"col_index": 4, "role": "closing", "sign": "=", "name": "期末"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 1
        assert "宽表横向公式不平" in findings[0].description

    def test_skip_columns(self):
        """skip 列不参与公式"""
        note = _note(
            headers=["项目", "期初", "减值期初", "增加", "减少", "期末", "减值期末"],
            rows=[["A公司", 100, 10, 50, 30, 120, 15]],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "skip", "name": "减值期初"},
            {"col_index": 3, "role": "movement", "sign": "+", "name": "增加"},
            {"col_index": 4, "role": "movement", "sign": "-", "name": "减少"},
            {"col_index": 5, "role": "closing", "sign": "=", "name": "期末"},
            {"col_index": 6, "role": "skip", "name": "减值期末"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_skip_qizhong_row(self):
        """跳过'其中'行"""
        note = _note(
            headers=["项目", "期初", "增加", "减少", "期末"],
            rows=[
                ["A公司", 100, 50, 30, 120],
                ["其中：子项", 60, 30, 10, 999],  # 不平但应跳过
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "movement", "sign": "+", "name": "增加"},
            {"col_index": 3, "role": "movement", "sign": "-", "name": "减少"},
            {"col_index": 4, "role": "closing", "sign": "=", "name": "期末"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_total_row_high_risk(self):
        """合计行不平衡应为 HIGH 风险"""
        note = _note(
            headers=["项目", "期初", "增加", "减少", "期末"],
            rows=[["合计", 100, 50, 30, 999]],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "movement", "sign": "+", "name": "增加"},
            {"col_index": 3, "role": "movement", "sign": "-", "name": "减少"},
            {"col_index": 4, "role": "closing", "sign": "=", "name": "期末"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 1
        assert findings[0].risk_level.value == "high"

    def test_empty_formula(self):
        """空公式返回空"""
        note = _note(headers=["项目"], rows=[["A"]])
        assert engine.check_wide_table_formula(note, None) == []
        assert engine.check_wide_table_formula(note, {}) == []

    def test_data_row_start(self):
        """data_row_start 跳过前面的行"""
        note = _note(
            headers=["项目", "期初", "增加", "减少", "期末"],
            rows=[
                ["表头行", "期初", "增加", "减少", "期末"],  # 行0：表头
                ["A公司", 100, 50, 30, 120],                  # 行1：数据
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "movement", "sign": "+", "name": "增加"},
            {"col_index": 3, "role": "movement", "sign": "-", "name": "减少"},
            {"col_index": 4, "role": "closing", "sign": "=", "name": "期末"},
        ], data_row_start=1)
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_equity_investment_13_cols(self):
        """长期股权投资明细表13列完整测试"""
        note = _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初(账面价值)", "减值准备期初",
                     "追加投资", "减少投资", "权益法投资损益",
                     "其他综合收益", "其他权益变动", "现金股利",
                     "计提减值", "其他", "期末(账面价值)", "减值准备期末"],
            rows=[
                ["A公司", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 1185, 50],
                ["小计", 1000, 50, 200, 100, 80, 20, 10, 30, 0, 5, 1185, 50],
            ],
        )
        # 公式: 1000 + 200 - 100 + 80 + 20 + 10 - 30 - 0 + 5 = 1185
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "被投资单位"},
            {"col_index": 1, "role": "opening", "sign": "+", "name": "期初"},
            {"col_index": 2, "role": "skip", "name": "减值准备期初"},
            {"col_index": 3, "role": "movement", "sign": "+", "name": "追加投资"},
            {"col_index": 4, "role": "movement", "sign": "-", "name": "减少投资"},
            {"col_index": 5, "role": "movement", "sign": "+", "name": "投资损益"},
            {"col_index": 6, "role": "movement", "sign": "+", "name": "其他综合收益"},
            {"col_index": 7, "role": "movement", "sign": "+", "name": "其他权益变动"},
            {"col_index": 8, "role": "movement", "sign": "-", "name": "现金股利"},
            {"col_index": 9, "role": "movement", "sign": "-", "name": "计提减值"},
            {"col_index": 10, "role": "movement", "sign": "+", "name": "其他"},
            {"col_index": 11, "role": "closing", "sign": "=", "name": "期末"},
            {"col_index": 12, "role": "skip", "name": "减值准备期末"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0


# ─── 分类合计型（上市版）宽表横向公式测试 ───

class TestCheckWideTableCategorySum:
    """上市版宽表：各分类列之和 = 合计列"""

    def _make_formula(self, columns, data_row_start=0):
        return {
            "formula_type": "category_sum",
            "columns": columns,
            "data_row_start": data_row_start,
        }

    def test_balanced_category_sum(self):
        """各分类列之和等于合计列：无 finding"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "运输设备", "合计"],
            rows=[
                ["一、账面原值", None, None, None, None],
                ["1.期初余额", 1000, 500, 200, 1700],
                ["2.本期增加金额", 100, 50, 30, 180],
                ["3.本期减少金额", 20, 10, 5, 35],
                ["4.期末余额", 1080, 540, 225, 1845],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "data", "sign": "+", "name": "运输设备"},
            {"col_index": 4, "role": "total", "sign": "=", "name": "合计"},
        ], data_row_start=1)
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_unbalanced_category_sum(self):
        """合计列与各分类列之和不一致"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "运输设备", "合计"],
            rows=[
                ["1.期初余额", 1000, 500, 200, 1800],  # 实际合计应为1700
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "data", "sign": "+", "name": "运输设备"},
            {"col_index": 4, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 1
        assert "宽表横向合计不平" in findings[0].description
        assert findings[0].difference == -100.0

    def test_skip_qizhong_row(self):
        """跳过'其中'行"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "合计"],
            rows=[
                ["1.期初余额", 1000, 500, 1500],
                ["其中：已抵押", 200, 100, 999],  # 不平但应跳过
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_skip_empty_row(self):
        """所有分类列为 None 且合计为 0 时跳过"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "合计"],
            rows=[
                ["一、账面原值", None, None, None],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_fixed_asset_full_table(self):
        """上市版固定资产完整表格测试（含原价、折旧、减值、账面价值）"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "运输设备", "电子设备", "合计"],
            rows=[
                ["一、账面原值：", None, None, None, None, None],
                ["1.期初余额", 5000, 3000, 800, 400, 9200],
                ["2.本期增加金额", 200, 500, 100, 50, 850],
                ["（1）购置", 100, 300, 80, 50, 530],
                ["（2）在建工程转入", 100, 200, 20, 0, 320],
                ["3.本期减少金额", 50, 100, 30, 20, 200],
                ["4.期末余额", 5150, 3400, 870, 430, 9850],
                ["二、累计折旧", None, None, None, None, None],
                ["1.期初余额", 1000, 1500, 400, 200, 3100],
                ["2.本期增加金额", 100, 300, 80, 40, 520],
                ["3.本期减少金额", 10, 50, 15, 10, 85],
                ["4.期末余额", 1090, 1750, 465, 230, 3535],
                ["三、减值准备", None, None, None, None, None],
                ["1.期初余额", 0, 50, 0, 0, 50],
                ["4.期末余额", 0, 50, 0, 0, 50],
                ["四、账面价值", None, None, None, None, None],
                ["1.期末账面价值", 4060, 1600, 405, 200, 6265],
                ["2.期初账面价值", 4000, 1450, 400, 200, 6050],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "data", "sign": "+", "name": "运输设备"},
            {"col_index": 4, "role": "data", "sign": "+", "name": "电子设备"},
            {"col_index": 5, "role": "total", "sign": "=", "name": "合计"},
        ], data_row_start=1)
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_intangible_asset_category_sum(self):
        """上市版无形资产分类合计测试"""
        note = _note(
            name="无形资产",
            title="无形资产情况",
            headers=["项目", "土地使用权", "专利权", "非专利技术", "合计"],
            rows=[
                ["1.期初余额", 2000, 500, 300, 2800],
                ["2.本期增加金额", 0, 100, 50, 150],
                ["3.本期减少金额", 0, 0, 10, 10],
                ["4.期末余额", 2000, 600, 340, 2940],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "土地使用权"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "专利权"},
            {"col_index": 3, "role": "data", "sign": "+", "name": "非专利技术"},
            {"col_index": 4, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_investment_property_category_sum(self):
        """上市版投资性房地产分类合计测试"""
        note = _note(
            name="投资性房地产",
            title="投资性房地产情况",
            headers=["项目", "房屋、建筑物", "土地使用权", "合计"],
            rows=[
                ["1.期初余额", 3000, 1000, 4000],
                ["2.本期增加金额", 500, 0, 500],
                ["4.期末余额", 3500, 1000, 4500],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋、建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "土地使用权"},
            {"col_index": 3, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_auto_detect_category_sum_without_formula_type(self):
        """无 formula_type 时根据列角色自动推断为 category_sum"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "合计"],
            rows=[
                ["1.期初余额", 1000, 500, 1500],
            ],
        )
        # 不设置 formula_type，但有 data 和 total 角色
        formula = {
            "columns": [
                {"col_index": 0, "role": "label", "name": "项目"},
                {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
                {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
                {"col_index": 3, "role": "total", "sign": "=", "name": "合计"},
            ],
            "data_row_start": 0,
        }
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_category_sum_with_skip_col(self):
        """分类合计型含 skip 列（如百分比列）"""
        note = _note(
            name="使用权资产",
            title="使用权资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "占比%", "合计"],
            rows=[
                ["1.期初余额", 800, 200, 80, 1000],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "skip", "name": "占比%"},
            {"col_index": 4, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 0

    def test_total_row_high_risk_category_sum(self):
        """分类合计型中合计行不平衡应为 HIGH 风险"""
        note = _note(
            name="固定资产",
            title="固定资产情况",
            headers=["项目", "房屋及建筑物", "机器设备", "合计"],
            rows=[
                ["合计", 1000, 500, 9999],
            ],
        )
        formula = self._make_formula([
            {"col_index": 0, "role": "label", "name": "项目"},
            {"col_index": 1, "role": "data", "sign": "+", "name": "房屋及建筑物"},
            {"col_index": 2, "role": "data", "sign": "+", "name": "机器设备"},
            {"col_index": 3, "role": "total", "sign": "=", "name": "合计"},
        ])
        findings = engine.check_wide_table_formula(note, formula)
        assert len(findings) == 1
        assert findings[0].risk_level.value == "high"


# ─── check_equity_method_income_consistency 测试 ───

class TestEquityMethodIncomeConsistency:
    def _equity_detail_note(self, total_income=80.0):
        """长期股权投资明细表，含权益法投资损益列"""
        return _note(
            name="长期股权投资",
            title="长期股权投资明细",
            headers=["被投资单位", "期初", "减值期初", "追加", "减少",
                     "权益法下确认的投资损益", "其他综合", "其他权益",
                     "现金股利", "计提减值", "其他", "期末", "减值期末"],
            rows=[
                ["A公司", 500, 0, 0, 0, 50, 0, 0, 0, 0, 0, 550, 0],
                ["B公司", 300, 0, 0, 0, 30, 0, 0, 0, 0, 0, 330, 0],
                ["合计", 800, 0, 0, 0, total_income, 0, 0, 0, 0, 0, 880, 0],
            ],
        )

    def _invest_income_note(self, equity_income=80.0):
        """投资收益附注表"""
        return _note(
            name="投资收益",
            title="投资收益",
            headers=["项目", "本期发生额", "上期发生额"],
            rows=[
                ["权益法核算的长期股权投资收益", equity_income, 60],
                ["处置长期股权投资产生的投资收益", 10, 5],
                ["合计", equity_income + 10, 65],
            ],
        )

    def test_all_three_consistent(self):
        """三方一致：无 finding"""
        notes = [
            self._equity_detail_note(80),
            self._invest_income_note(80),
        ]
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=80),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 0

    def test_detail_vs_income_note_mismatch(self):
        """明细表 vs 投资收益表不一致"""
        notes = [
            self._equity_detail_note(80),
            self._invest_income_note(90),  # 不一致
        ]
        items = []
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 1
        assert "权益法投资损益跨科目不一致" in findings[0].description

    def test_detail_vs_statement_mismatch(self):
        """明细表 vs 利润表不一致"""
        notes = [self._equity_detail_note(80)]
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=90),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 1

    def test_all_three_mismatch(self):
        """三方都不一致：产生3个 finding（两两比对）"""
        notes = [
            self._equity_detail_note(80),
            self._invest_income_note(90),
        ]
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=100),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 3

    def test_only_one_source(self):
        """只有一个来源，无法比对"""
        notes = [self._equity_detail_note(80)]
        items = []
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 0

    def test_no_equity_detail(self):
        """无长期股权投资明细表，只比对投资收益表 vs 利润表"""
        notes = [self._invest_income_note(80)]
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=80),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 0

    def test_income_note_vs_statement_mismatch(self):
        """投资收益表 vs 利润表不一致"""
        notes = [self._invest_income_note(80)]
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=90),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, notes, {},
        )
        assert len(findings) == 1
        assert "80" in findings[0].description
        assert "90" in findings[0].description

    def test_invest_income_note_reversed_columns(self):
        """投资收益表列顺序为 项目|上期|本期 时，仍能正确取本期值"""
        note = _note(
            name="投资收益",
            title="投资收益",
            headers=["项目", "上期发生额", "本期发生额"],
            rows=[
                ["权益法核算的长期股权投资收益", 60, 80],
                ["合计", 65, 90],
            ],
        )
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=80),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, [note], {},
        )
        assert len(findings) == 0  # 80 == 80，一致

    def test_balance_col_not_matched_as_income(self):
        """期初余额列含"投资损益"子串时不应被误匹配为投资损益列"""
        # 模拟多行表头合并后产生的列名：期初投资损益余额（实际是余额列）
        note = _note(
            name="长期股权投资",
            title="权益法核算的长期股权投资明细",
            headers=["被投资单位", "期初投资成本", "期初余额",
                     "减值准备期初余额", "权益法下确认的投资损益",
                     "其他综合收益", "其他权益变动", "现金股利",
                     "计提减值", "其他", "期末余额", "减值准备期末"],
            rows=[
                ["A公司", 500, 500, 0, 50, 0, 0, 0, 0, 0, 550, 0],
                ["合计", 800, 800, 0, 80, 0, 0, 0, 0, 0, 880, 0],
            ],
        )
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=80),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, [note], {},
        )
        # 应匹配到 col4（权益法下确认的投资损益=80），与利润表80一致
        assert len(findings) == 0

    def test_balance_col_with_touzi_sunyi_excluded(self):
        """列名含"期初"+"投资损益"时应被排除，不作为投资损益列"""
        note = _note(
            name="长期股权投资",
            title="权益法核算的长期股权投资明细",
            # 故意把"投资损益"放在一个含"期初"的列名中
            headers=["被投资单位", "期初投资损益余额", "减值准备",
                     "追加", "减少", "其他综合", "其他权益",
                     "现金股利", "计提减值", "其他", "期末", "减值期末"],
            rows=[
                ["A公司", 9999, 0, 0, 0, 0, 0, 0, 0, 0, 550, 0],
                ["合计", 9999, 0, 0, 0, 0, 0, 0, 0, 0, 880, 0],
            ],
        )
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=80),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, [note], {},
        )
        # "期初投资损益余额"含"期初"，应被排除；无有效投资损益列，
        # 只有利润表一个来源，不足两方比对，无 finding
        assert len(findings) == 0

    def test_parent_company_note_skipped(self):
        """母公司附注的长期股权投资明细表不参与跨科目核对"""
        note = _note(
            name="长期股权投资",
            title="母公司财务报表主要项目注释-长期股权投资明细",
            headers=["被投资单位", "期初", "减值期初", "追加", "减少",
                     "权益法下确认的投资损益", "其他综合", "其他权益",
                     "现金股利", "计提减值", "其他", "期末", "减值期末"],
            rows=[
                ["A公司", 500, 0, 0, 0, 50, 0, 0, 0, 0, 0, 550, 0],
                ["合计", 800, 0, 0, 0, 42, 0, 0, 0, 0, 0, 880, 0],
            ],
        )
        items = [
            _item("其中：对联营企业和合营企业的投资收益", closing=80),
        ]
        findings = engine.check_equity_method_income_consistency(
            items, [note], {},
        )
        # 母公司附注被跳过，只有利润表一个来源，不足两方比对
        assert len(findings) == 0
