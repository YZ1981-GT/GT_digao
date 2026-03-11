"""报表科目预设清单。

标准合并财务报表科目，按资产负债表、利润表、现金流量表分类。
每个科目包含：
- name: 标准科目名称
- category: 所属分类（asset/liability_equity/income/cash_flow）
- statement_type: 报表类型
- note_keywords: 附注中匹配该科目的关键词列表
- order: 显示排序
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class PresetAccount:
    """预设报表科目"""
    name: str
    category: str  # asset / liability_equity / income / cash_flow / related_party
    statement_type: str  # balance_sheet / income_statement / cash_flow / equity_change
    note_keywords: List[str] = field(default_factory=list)
    order: int = 0


# ═══════════════════════════════════════════════════════════
# 资产负债表 - 资产类
# ═══════════════════════════════════════════════════════════
_ASSET_ITEMS = [
    # 流动资产
    PresetAccount("货币资金", "asset", "balance_sheet", ["货币资金"], 100),
    PresetAccount("结算备付金", "asset", "balance_sheet", ["结算备付金"], 101),
    PresetAccount("拆出资金", "asset", "balance_sheet", ["拆出资金"], 102),
    PresetAccount("交易性金融资产", "asset", "balance_sheet", ["交易性金融资产"], 103),
    PresetAccount("以公允价值计量且其变动计入当期损益的金融资产", "asset", "balance_sheet",
                  ["以公允价值计量", "公允价值变动"], 104),
    PresetAccount("衍生金融资产", "asset", "balance_sheet", ["衍生金融资产"], 105),
    PresetAccount("应收票据", "asset", "balance_sheet", ["应收票据"], 106),
    PresetAccount("应收账款", "asset", "balance_sheet", ["应收账款"], 107),
    PresetAccount("应收款项融资", "asset", "balance_sheet", ["应收款项融资"], 108),
    PresetAccount("预付款项", "asset", "balance_sheet", ["预付款项", "预付账款"], 109),
    PresetAccount("应收保费", "asset", "balance_sheet", ["应收保费"], 110),
    PresetAccount("应收分保账款", "asset", "balance_sheet", ["应收分保"], 111),
    PresetAccount("应收分保合同准备金", "asset", "balance_sheet", ["分保合同准备金"], 112),
    PresetAccount("其他应收款", "asset", "balance_sheet", ["其他应收款"], 113),
    PresetAccount("买入返售金融资产", "asset", "balance_sheet", ["买入返售"], 114),
    PresetAccount("存货", "asset", "balance_sheet", ["存货"], 115),
    PresetAccount("合同资产", "asset", "balance_sheet", ["合同资产"], 116),
    PresetAccount("持有待售资产", "asset", "balance_sheet", ["持有待售"], 117),
    PresetAccount("一年内到期的非流动资产", "asset", "balance_sheet", ["一年内到期"], 118),
    PresetAccount("其他流动资产", "asset", "balance_sheet", ["其他流动资产"], 119),
    # 非流动资产
    PresetAccount("发放贷款和垫款", "asset", "balance_sheet", ["发放贷款", "垫款"], 130),
    PresetAccount("债权投资", "asset", "balance_sheet", ["债权投资"], 131),
    PresetAccount("其他债权投资", "asset", "balance_sheet", ["其他债权投资"], 132),
    PresetAccount("长期应收款", "asset", "balance_sheet", ["长期应收款"], 133),
    PresetAccount("长期股权投资", "asset", "balance_sheet", ["长期股权投资"], 134),
    PresetAccount("其他权益工具投资", "asset", "balance_sheet", ["其他权益工具投资"], 135),
    PresetAccount("其他非流动金融资产", "asset", "balance_sheet", ["其他非流动金融资产"], 136),
    PresetAccount("投资性房地产", "asset", "balance_sheet", ["投资性房地产"], 137),
    PresetAccount("固定资产", "asset", "balance_sheet", ["固定资产"], 138),
    PresetAccount("在建工程", "asset", "balance_sheet", ["在建工程"], 139),
    PresetAccount("生产性生物资产", "asset", "balance_sheet", ["生产性生物资产"], 140),
    PresetAccount("油气资产", "asset", "balance_sheet", ["油气资产"], 141),
    PresetAccount("使用权资产", "asset", "balance_sheet", ["使用权资产"], 142),
    PresetAccount("无形资产", "asset", "balance_sheet", ["无形资产"], 143),
    PresetAccount("开发支出", "asset", "balance_sheet", ["开发支出"], 144),
    PresetAccount("商誉", "asset", "balance_sheet", ["商誉"], 145),
    PresetAccount("长期待摊费用", "asset", "balance_sheet", ["长期待摊费用"], 146),
    PresetAccount("递延所得税资产", "asset", "balance_sheet", ["递延所得税资产"], 147),
    PresetAccount("其他非流动资产", "asset", "balance_sheet", ["其他非流动资产"], 148),
]
