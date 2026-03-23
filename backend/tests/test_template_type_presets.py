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


class TestOtherComprehensiveIncomeFiltering:
    """其他综合收益子表过滤测试。

    Problem 3: 其他综合收益各项目及其所得税影响和转入损益情况表
    该表的列头是"本期发生额/上期发生额"（变动额），不是"期末余额/期初余额"（余额），
    不应参与报表-附注余额一致性校对。
    """

    def test_oci_summary_table_matches(self):
        """其他综合收益汇总表应匹配。"""
        assert should_verify_note_table('其他综合收益', '其他综合收益', '') is True

    def test_oci_tax_impact_table_excluded(self):
        """所得税影响和转入损益情况表应被排除（含"发生额"列头，非余额表）。"""
        assert should_verify_note_table(
            '其他综合收益',
            '其他综合收益各项目及其所得税影响和转入损益情况',
            '其他综合收益各项目及其所得税影响和转入损益情况',
        ) is False

    def test_oci_reclassification_excluded(self):
        """不能重分类/将重分类子表应被排除。"""
        assert should_verify_note_table(
            '其他综合收益', '以后不能重分类进损益的其他综合收益', ''
        ) is False
        assert should_verify_note_table(
            '其他综合收益', '以后将重分类进损益的其他综合收益', ''
        ) is False


class TestGoodwillFiltering:
    """商誉子表过滤测试。

    Problem 4: 商誉账面原值表只有原值（gross value），
    但报表数是净值（原值-减值准备），不应用原值表做余额核对。
    """

    def test_goodwill_summary_table_matches(self):
        """商誉汇总表（含净值）应匹配。"""
        assert should_verify_note_table('商誉', '商誉', '') is True

    def test_goodwill_gross_value_table_excluded(self):
        """商誉账面原值表应被排除（只有原值，不含减值准备扣减）。"""
        assert should_verify_note_table(
            '商誉', '商誉账面原值', '商誉账面原值'
        ) is False

    def test_goodwill_impairment_provision_excluded(self):
        """商誉减值准备表应被排除。"""
        assert should_verify_note_table(
            '商誉', '商誉减值准备', '商誉减值准备'
        ) is False

    def test_goodwill_impairment_test_excluded(self):
        """商誉减值测试表应被排除。"""
        assert should_verify_note_table(
            '商誉', '商誉减值测试信息', '商誉减值测试信息'
        ) is False

    def test_goodwill_asset_group_excluded(self):
        """资产组信息表应被排除。"""
        assert should_verify_note_table(
            '商誉', '包含商誉的资产组或资产组组合', ''
        ) is False


class TestNetHedgeGainPreset:
    """净敞口套期收益 (F67) 预设测试。"""

    def test_net_hedge_gain_matches(self):
        assert should_verify_note_table('净敞口套期收益', '净敞口套期收益', '') is True

    def test_net_hedge_gain_found(self):
        preset = find_amount_check_preset('净敞口套期收益')
        assert preset is not None
        assert '净敞口套期收益' in preset['account_keywords']


class TestCashFlowPresets:
    """现金流量表6项科目 (F76~F81) 预设测试。"""

    @pytest.mark.parametrize("account", [
        '收到其他与经营活动有关的现金',
        '支付其他与经营活动有关的现金',
        '收到其他与投资活动有关的现金',
        '支付其他与投资活动有关的现金',
        '收到其他与筹资活动有关的现金',
        '支付其他与筹资活动有关的现金',
    ])
    def test_cash_flow_preset_found(self, account):
        """每个现金流量表科目都应有对应预设。"""
        preset = find_amount_check_preset(account)
        assert preset is not None, f"未找到预设: {account}"

    @pytest.mark.parametrize("account", [
        '收到其他与经营活动有关的现金',
        '支付其他与经营活动有关的现金',
        '收到其他与投资活动有关的现金',
        '支付其他与投资活动有关的现金',
        '收到其他与筹资活动有关的现金',
        '支付其他与筹资活动有关的现金',
    ])
    def test_cash_flow_table_matches(self, account):
        """现金流量表科目的明细表应匹配。"""
        assert should_verify_note_table(account, account, '') is True


class TestTreasuryStockPreset:
    """库存股 (FK-1/FK-2) 预设测试——上市版特有。"""

    def test_treasury_stock_found(self):
        preset = find_amount_check_preset('库存股')
        assert preset is not None

    def test_treasury_stock_matches(self):
        assert should_verify_note_table('库存股', '库存股明细', '') is True

    def test_treasury_stock_generic_title(self):
        assert should_verify_note_table('库存股', '库存股', '') is True


class TestDefinedBenefitPlanPreset:
    """设定受益计划净资产 (FS-1/FS-2) 预设测试——上市版特有。"""

    def test_defined_benefit_plan_found(self):
        preset = find_amount_check_preset('设定受益计划净资产')
        assert preset is not None

    def test_defined_benefit_plan_matches(self):
        assert should_verify_note_table('设定受益计划净资产', '设定受益计划净资产明细', '') is True

    def test_defined_benefit_plan_generic_title(self):
        assert should_verify_note_table('设定受益计划净资产', '设定受益计划净资产', '') is True


class TestFundCollectionPreset:
    """应收资金集中管理款 (F7A) 预设测试——TASK 21 第一个已添加的预设。"""

    def test_fund_collection_found(self):
        preset = find_amount_check_preset('应收资金集中管理款')
        assert preset is not None

    def test_fund_collection_matches(self):
        assert should_verify_note_table('应收资金集中管理款', '应收资金集中管理款', '') is True
