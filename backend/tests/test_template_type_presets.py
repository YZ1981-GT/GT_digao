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
