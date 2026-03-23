"""测试 amount_check_presets 的模板类型区分逻辑。

重点验证：
1. 长期股权投资：国企版用①分类表，上市版用①明细表
2. template_type=None 时使用默认规则（国企版行为）
3. _get_verify_tables 正确选择覆盖规则
"""
import pytest
from app.services.amount_check_presets import (
    should_verify_note_table,
    find_amount_check_preset,
    _get_verify_tables,
)


class TestLongTermEquityInvestment:
    """长期股权投资 (F17) 模板区分测试。"""

    # ── 国企版：①分类表匹配，明细表被排除 ──

    def test_soe_classification_table_matches(self):
        """国企版：①分类表应匹配。"""
        assert should_verify_note_table(
            '长期股权投资', '长期股权投资分类', '', template_type='soe'
        ) is True

    def test_soe_detail_table_excluded(self):
        """国企版：②明细表应被排除（exclude '明细'）。"""
        assert should_verify_note_table(
            '长期股权投资', '长期股权投资明细', '', template_type='soe'
        ) is False

    def test_soe_subsidiary_excluded(self):
        """国企版：对子公司投资表应被排除。"""
        assert should_verify_note_table(
            '长期股权投资', '对子公司投资', '', template_type='soe'
        ) is False

    # ── 上市版：①明细表匹配（无分类汇总表）──

    def test_listed_detail_table_matches(self):
        """上市版：①明细表应匹配（上市版无分类汇总表，明细表是唯一目标）。"""
        assert should_verify_note_table(
            '长期股权投资', '长期股权投资明细', '', template_type='listed'
        ) is True

    def test_listed_generic_title_matches(self):
        """上市版：标题仅含'长期股权投资'也应匹配。"""
        assert should_verify_note_table(
            '长期股权投资', '长期股权投资', '', template_type='listed'
        ) is True

    def test_listed_subsidiary_excluded(self):
        """上市版：对子公司投资表仍应被排除。"""
        assert should_verify_note_table(
            '长期股权投资', '对子公司投资', '', template_type='listed'
        ) is False

    def test_listed_joint_venture_excluded(self):
        """上市版：对合营企业投资表仍应被排除。"""
        assert should_verify_note_table(
            '长期股权投资', '对合营企业投资', '', template_type='listed'
        ) is False

    def test_listed_impairment_test_excluded(self):
        """上市版：减值测试表应被排除。"""
        assert should_verify_note_table(
            '长期股权投资', '减值测试', '', template_type='listed'
        ) is False

    # ── 默认（无 template_type）：使用国企版行为 ──

    def test_default_classification_matches(self):
        """默认：①分类表应匹配。"""
        assert should_verify_note_table(
            '长期股权投资', '长期股权投资分类', ''
        ) is True

    def test_default_detail_excluded(self):
        """默认：②明细表应被排除（与国企版一致）。"""
        assert should_verify_note_table(
            '长期股权投资', '长期股权投资明细', ''
        ) is False


class TestGetVerifyTables:
    """_get_verify_tables 辅助函数测试。"""

    def test_returns_default_when_no_template_type(self):
        preset = find_amount_check_preset('长期股权投资')
        tables = _get_verify_tables(preset, None)
        assert tables == preset['verify_tables']

    def test_returns_default_when_no_override(self):
        """无 template_overrides 的科目，任何 template_type 都返回默认。"""
        preset = find_amount_check_preset('货币资金')
        tables = _get_verify_tables(preset, 'listed')
        assert tables == preset['verify_tables']

    def test_returns_override_for_listed(self):
        preset = find_amount_check_preset('长期股权投资')
        tables = _get_verify_tables(preset, 'listed')
        overrides = preset.get('template_overrides', {})
        assert 'listed' in overrides
        assert tables == overrides['listed']

    def test_returns_default_for_soe(self):
        """国企版无覆盖时返回默认规则。"""
        preset = find_amount_check_preset('长期股权投资')
        tables = _get_verify_tables(preset, 'soe')
        # soe 没有覆盖，应返回默认
        assert tables == preset['verify_tables']


class TestOtherAccountsUnchanged:
    """确保其他科目的行为不受影响。"""

    @pytest.mark.parametrize("account,section,expected", [
        ('应收账款', '按账龄', True),
        ('应收账款', '坏账准备计提方法', False),
        ('货币资金', '货币资金', True),
        ('货币资金', '受限制的货币资金', False),
        ('固定资产', '固定资产', True),
        ('固定资产', '固定资产情况', True),
        ('存货', '存货分类', True),
        ('存货', '跌价准备', False),
    ])
    def test_other_accounts_soe(self, account, section, expected):
        assert should_verify_note_table(account, section, '', template_type='soe') is expected

    @pytest.mark.parametrize("account,section,expected", [
        ('应收账款', '按账龄', True),
        ('货币资金', '货币资金', True),
        ('固定资产', '固定资产', True),
    ])
    def test_other_accounts_listed(self, account, section, expected):
        assert should_verify_note_table(account, section, '', template_type='listed') is expected



class TestReceivablesSubTableFiltering:
    """应收账款子表过滤测试：只有①按账龄表参与校对，其余子表排除。"""

    @pytest.mark.parametrize("section,account,expected", [
        # ①按账龄表 → 参与校对
        ('（1）按账龄披露应收账款', '按账龄披露应收账款', True),
        # ②按坏账准备计提方法分类表 → 排除
        ('（2）按坏账准备计提方法分类披露应收账款', '按坏账准备计提方法分类披露应收账款', False),
        # ②下的子表：单项计提 → 排除
        ('期末单项计提坏账准备的应收账款', '期末单项计提坏账准备的应收账款', False),
        # ②下的子表：组合方法计提 → 排除
        ('采用其他组合方法计提坏账准备的应收账款', '采用其他组合方法计提坏账准备的应收账款', False),
        # ③前五名 → 排除
        ('（3）按欠款方归集的期末余额前五名的应收账款', '按欠款方归集的期末余额前五名的应收账款', False),
        # 坏账准备变动 → 排除
        ('应收账款坏账准备变动', '应收账款坏账准备变动', False),
        # 核销 → 排除
        ('本期实际核销的应收账款', '本期实际核销的应收账款', False),
    ])
    def test_receivables_sub_tables(self, section, account, expected):
        """应收账款各子表的白名单过滤结果。"""
        assert should_verify_note_table('应收账款', section, account) is expected

    def test_receivables_sub_tables_with_template_type(self):
        """模板类型不影响应收账款的过滤逻辑（国企版和上市版规则相同）。"""
        for tt in ['soe', 'listed', None]:
            assert should_verify_note_table(
                '应收账款', '（1）按账龄披露应收账款', '按账龄披露应收账款',
                template_type=tt,
            ) is True
            assert should_verify_note_table(
                '应收账款', '期末单项计提坏账准备的应收账款', '期末单项计提坏账准备的应收账款',
                template_type=tt,
            ) is False



class TestIntangibleAssetFiltering:
    """无形资产子表过滤测试。"""

    def test_intangible_asset_situation_table(self):
        assert should_verify_note_table('无形资产', '无形资产情况', '') is True

    def test_intangible_asset_amortization_method_excluded(self):
        """摊销方法说明表不应参与余额核对。"""
        assert should_verify_note_table(
            '无形资产', '使用寿命有限的无形资产摊销方法如下：',
            '使用寿命有限的无形资产摊销方法如下：',
        ) is False

    def test_intangible_asset_impairment_excluded(self):
        assert should_verify_note_table('无形资产', '无形资产减值准备', '') is False


class TestIncomeTaxExpenseFiltering:
    """所得税费用子表过滤测试。"""

    def test_income_tax_expense_table(self):
        assert should_verify_note_table('所得税费用', '所得税费用', '所得税费用') is True

    def test_deferred_tax_asset_excluded(self):
        """递延所得税资产表不应参与所得税费用的余额核对。"""
        assert should_verify_note_table(
            '所得税费用', '未经抵销的递延所得税资产和递延所得税负债', '',
        ) is False

    def test_deferred_tax_offset_excluded(self):
        assert should_verify_note_table(
            '所得税费用', '以抵销后净额列示的递延所得税资产或负债', '',
        ) is False

    def test_unrecognized_deferred_tax_excluded(self):
        assert should_verify_note_table(
            '所得税费用', '未确认递延所得税资产明细', '',
        ) is False

    def test_oci_tax_impact_excluded(self):
        """其他综合收益所得税影响表不应参与所得税费用的余额核对。"""
        assert should_verify_note_table(
            '所得税费用', '其他综合收益各项目及其所得税影响和转入损益情况', '',
        ) is False

    def test_adjustment_process_excluded(self):
        assert should_verify_note_table(
            '所得税费用', '会计利润与所得税费用调整过程', '',
        ) is False
