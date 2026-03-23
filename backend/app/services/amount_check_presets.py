"""报表数 vs 附注数一致性校对预设规则。

定义每个科目下哪些附注表格需要跟报表余额做一致性校对。
只有匹配预设规则的表格才参与校对，其余表格不做报表-附注一致性核对。

设计原则：
- 正向白名单：明确列出需要校对的表格类型
- title_keywords 来自国企/上市报表附注模板中实际的表格标题
- 部分科目有二级明细校对（如固定资产的原价/累计折旧/减值准备/账面价值）
- 变动表（期初+增加-减少=期末）由 wide_table_presets 单独处理横向公式校验

数据结构：
- account_keywords: 报表科目匹配关键词列表
- verify_tables: 需要校对的表格类型列表
  - type: "summary" (汇总表，取合计行) | "section" (多段表，取段落小计)
  - title_keywords: 表格标题匹配关键词（用于定位需要校对的表格）
  - exclude_keywords: 排除关键词（标题含这些词的表格不匹配）
  - max_tables: 该类型最多匹配几个表格（默认1）
"""
from typing import Dict, List, Optional, TypedDict


class VerifyTableRule(TypedDict, total=False):
    type: str                    # "summary" | "section"
    title_keywords: List[str]    # 标题匹配关键词
    exclude_keywords: List[str]  # 排除关键词
    max_tables: int              # 最多匹配几个（默认1）


class AmountCheckPreset(TypedDict):
    account_keywords: List[str]  # 报表科目匹配关键词
    verify_tables: List[VerifyTableRule]  # 需要校对的表格规则


# ═══════════════════════════════════════════════════════════
# 报表-附注一致性校对预设规则
# title_keywords 来源：国企报表附注.md / 上市报表附注.md 模板
# ═══════════════════════════════════════════════════════════
AMOUNT_CHECK_PRESETS: List[AmountCheckPreset] = [

    # ── 资产负债表：流动资产 ──
    {
        # 货币资金：第1个汇总表（项目/期末余额/期初余额）
        'account_keywords': ['货币资金'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['货币资金'],
                           'exclude_keywords': ['受限制', '受到限制']}],
    },
    {
        # 交易性金融资产：汇总表（项目/期末公允价值/期初公允价值）
        'account_keywords': ['交易性金融资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['交易性金融资产']}],
    },
    {
        # 衍生金融资产：汇总表
        'account_keywords': ['衍生金融资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['衍生金融资产']}],
    },
    {
        # 应收票据：应收票据分类表（票据种类/期末数/期初数，含账面价值列）
        'account_keywords': ['应收票据'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应收票据分类', '应收票据'],
                           'exclude_keywords': [
                               '坏账准备', '已质押', '已背书', '已贴现',
                               '前五名', '前5名', '出票人', '转为应收账款',
                               '终止确认', '逾期', '核销', '转回', '按账龄',
                               '按组合', '按单项', '计提方法',
                           ]}],
    },
    {
        # 应收账款：①按账龄表（F5-1/F5-2: 报表数 = 合计行.(账面余额-坏账准备)）
        # 注意：②按坏账准备计提方法分类表不直接跟报表数核对，仅参与跨表交叉校验(F5-8)
        'account_keywords': ['应收账款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['按账龄', '应收账款'],
                           'exclude_keywords': [
                               '坏账准备计提方法', '按计提方法', '按组合', '按单项',
                               '前五名', '前5名', '核销', '转回', '逾期',
                               '款项性质', '终止确认', '金融资产转移',
                               '坏账准备变动', '组合计提',
                           ]}],
    },
    {
        # 应收款项融资：汇总表（种类/期末余额/期初余额）
        'account_keywords': ['应收款项融资'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应收款项融资'],
                           'exclude_keywords': ['坏账准备', '减值准备']}],
    },
    {
        # 预付款项：按账龄列示表（账龄/期末数/期初数，含合计行）
        'account_keywords': ['预付款项', '预付账款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['按账龄列示', '按账龄', '预付款项', '预付账款'],
                           'exclude_keywords': [
                               '账龄超过', '前五名', '前5名', '按欠款方',
                           ]}],
    },
    {
        # 其他应收款：汇总表（项目/期末余额/期初余额，含应收利息/应收股利/其他应收款项）
        'account_keywords': ['其他应收款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他应收款'],
                           'exclude_keywords': [
                               '按账龄', '按组合', '按单项', '坏账准备', '计提方法',
                               '前五名', '前5名', '核销', '转回', '逾期', '款项性质',
                               '应收利息', '应收股利', '其他应收款项',
                           ]}],
    },
    {
        # 存货：存货分类表（项目/期末数/期初数，含账面余额/跌价准备/账面价值）
        'account_keywords': ['存货'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['存货分类', '存货'],
                           'exclude_keywords': [
                               '跌价准备', '合同履约成本减值', '数据资源',
                               '借款费用', '合同履约成本本期',
                           ]}],
    },
    {
        # 合同资产：合同资产情况表
        'account_keywords': ['合同资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['合同资产情况', '合同资产'],
                           'exclude_keywords': ['减值准备', '坏账准备', '重大变动']}],
    },
    {
        # 持有待售资产
        'account_keywords': ['持有待售资产', '持有待售'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['持有待售资产', '持有待售'],
                           'exclude_keywords': ['减值准备', '持有待售负债']}],
    },
    {
        'account_keywords': ['一年内到期的非流动资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['一年内到期的非流动资产']}],
    },
    {
        'account_keywords': ['其他流动资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他流动资产']}],
    },

    # ── 资产负债表：非流动资产 ──
    {
        # 债权投资：债权投资情况表
        'account_keywords': ['债权投资'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['债权投资情况', '债权投资'],
                           'exclude_keywords': ['减值准备', '其他债权']}],
    },
    {
        # 其他债权投资：其他债权投资情况表
        'account_keywords': ['其他债权投资'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他债权投资情况', '其他债权投资'],
                           'exclude_keywords': ['减值准备']}],
    },
    {
        # 长期应收款：按性质披露表
        'account_keywords': ['长期应收款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['按性质披露', '长期应收款'],
                           'exclude_keywords': ['坏账准备', '减值准备', '终止确认']}],
    },
    {
        # 长期股权投资：分类表（对合营/联营投资汇总）
        'account_keywords': ['长期股权投资'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['长期股权投资分类', '长期股权投资'],
                           'exclude_keywords': [
                               '明细', '对联营', '对合营', '对子公司',
                               '主要财务信息', '减值测试', '不重要',
                           ]}],
    },
    {
        'account_keywords': ['其他权益工具投资'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他权益工具投资情况', '其他权益工具投资'],
                           'exclude_keywords': ['期末其他权益']}],
    },
    {
        'account_keywords': ['其他非流动金融资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他非流动金融资产']}],
    },
    {
        # 投资性房地产：成本计量或公允价值计量的变动表
        'account_keywords': ['投资性房地产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['投资性房地产', '成本计量', '公允价值计量'],
                           'exclude_keywords': ['未办妥', '抵押', '出租',
                                                '原价', '累计折旧', '累计摊销', '账面净值', '减值准备']}],
    },
    {
        # 固定资产：
        # 1) 汇总表（期末账面价值/期初账面价值）
        # 2) 固定资产情况表（多段：原价/累计折旧/净值/减值准备/账面价值 → 二级明细校对）
        'account_keywords': ['固定资产'],
        'verify_tables': [
            {'type': 'summary', 'title_keywords': ['固定资产'],
             'exclude_keywords': [
                 '清理', '暂时闲置', '未办妥', '抵押', '出租',
                 '重要在建工程', '本期变动情况', '本期计提',
                 '固定资产情况',
                 '原价', '累计折旧', '账面净值', '减值准备',
             ]},
            {'type': 'section', 'title_keywords': ['固定资产情况'],
             'exclude_keywords': ['清理']},
        ],
    },
    {
        # 在建工程：汇总表
        'account_keywords': ['在建工程'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['在建工程'],
                           'exclude_keywords': ['重要在建工程', '本期变动情况', '减值', '本期计提']}],
    },
    {
        'account_keywords': ['生产性生物资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['生产性生物资产'],
                           'exclude_keywords': ['减值']}],
    },
    {
        'account_keywords': ['油气资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['油气资产分类', '油气资产'],
                           'exclude_keywords': ['减值']}],
    },
    {
        # 使用权资产：变动表（多段：原值/累计折旧/净值/减值准备/账面价值）
        'account_keywords': ['使用权资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['使用权资产'],
                           'exclude_keywords': ['减值']}],
    },
    {
        # 无形资产：无形资产情况表（多段：原价/累计摊销/减值准备/账面价值）
        'account_keywords': ['无形资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['无形资产情况', '无形资产'],
                           'exclude_keywords': ['减值', '未办妥', '数据资源', '开发支出',
                                                '原价', '累计摊销', '账面净值']}],
    },
    {
        'account_keywords': ['开发支出'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['开发支出'],
                           'exclude_keywords': ['减值准备', '重要的资本化']}],
    },
    {
        # 商誉：账面原值表 + 减值准备表（合计=账面价值）
        'account_keywords': ['商誉'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['商誉账面原值', '商誉'],
                           'exclude_keywords': ['减值测试', '资产组', '关键假设']}],
    },
    {
        'account_keywords': ['长期待摊费用'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['长期待摊费用']}],
    },
    {
        # 递延所得税资产：未经抵销表
        'account_keywords': ['递延所得税资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['未经抵销', '递延所得税资产'],
                           'exclude_keywords': ['未确认', '净额', '可抵扣亏损']}],
    },
    {
        'account_keywords': ['递延所得税负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['未经抵销', '递延所得税负债'],
                           'exclude_keywords': ['未确认', '净额']}],
    },
    {
        'account_keywords': ['其他非流动资产'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他非流动资产']}],
    },

    # ── 资产负债表：流动负债 ──
    {
        # 短期借款：短期借款分类表
        'account_keywords': ['短期借款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['短期借款分类', '短期借款'],
                           'exclude_keywords': ['逾期']}],
    },
    {
        'account_keywords': ['交易性金融负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['交易性金融负债']}],
    },
    {
        'account_keywords': ['衍生金融负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['衍生金融负债']}],
    },
    {
        'account_keywords': ['应付票据'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应付票据']}],
    },
    {
        # 应付账款：按账龄列示表
        'account_keywords': ['应付账款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应付账款'],
                           'exclude_keywords': ['前五名', '前5名', '账龄超过']}],
    },
    {
        'account_keywords': ['预收款项', '预收账款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['预收款项', '预收账款'],
                           'exclude_keywords': ['账龄超过']}],
    },
    {
        'account_keywords': ['合同负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['合同负债'],
                           'exclude_keywords': ['重大变动']}],
    },
    {
        # 应付职工薪酬：应付职工薪酬列示表（汇总：短期薪酬/离职后福利/辞退福利/合计）
        'account_keywords': ['应付职工薪酬'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应付职工薪酬列示', '应付职工薪酬'],
                           'exclude_keywords': [
                               '短期薪酬列示', '短期薪酬明细', '设定提存', '设定受益',
                               '辞退福利', '一年内到期',
                           ]}],
    },
    {
        'account_keywords': ['应交税费'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应交税费']}],
    },
    {
        # 其他应付款：汇总表（应付利息/应付股利/其他应付款项/合计）
        'account_keywords': ['其他应付款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他应付款'],
                           'exclude_keywords': [
                               '应付利息', '应付股利', '其他应付款项',
                               '前五名', '前5名', '账龄超过',
                           ]}],
    },
    {
        'account_keywords': ['持有待售负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['持有待售负债']}],
    },
    {
        'account_keywords': ['一年内到期的非流动负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['一年内到期的非流动负债']}],
    },
    {
        'account_keywords': ['其他流动负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他流动负债']}],
    },

    # ── 资产负债表：非流动负债 ──
    {
        # 长期借款：长期借款分类表
        'account_keywords': ['长期借款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['长期借款'],
                           'exclude_keywords': ['逾期']}],
    },
    {
        'account_keywords': ['应付债券'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['应付债券'],
                           'exclude_keywords': ['增减变动']}],
    },
    {
        'account_keywords': ['租赁负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['租赁负债']}],
    },
    {
        'account_keywords': ['长期应付款'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['长期应付款'],
                           'exclude_keywords': ['专项应付款']}],
    },
    {
        'account_keywords': ['长期应付职工薪酬'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['长期应付职工薪酬']}],
    },
    {
        'account_keywords': ['预计负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['预计负债']}],
    },
    {
        # 递延收益：变动表（期初/增加/减少/期末）
        'account_keywords': ['递延收益'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['递延收益'],
                           'exclude_keywords': ['政府补助情况']}],
    },
    {
        'account_keywords': ['其他非流动负债'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他非流动负债']}],
    },

    # ── 资产负债表：所有者权益 ──
    {
        'account_keywords': ['实收资本', '股本'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['实收资本', '股本']}],
    },
    {
        'account_keywords': ['其他权益工具'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他权益工具'],
                           'exclude_keywords': ['投资']}],
    },
    {
        'account_keywords': ['资本公积'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['资本公积']}],
    },
    {
        'account_keywords': ['其他综合收益'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他综合收益'],
                           'exclude_keywords': ['不能重分类', '将重分类']}],
    },
    {
        'account_keywords': ['专项储备'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['专项储备']}],
    },
    {
        'account_keywords': ['盈余公积'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['盈余公积']}],
    },
    {
        'account_keywords': ['未分配利润'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['未分配利润']}],
    },

    # ── 利润表 ──
    {
        # 营业收入/营业成本：汇总表（主营业务/其他业务/合计）
        'account_keywords': ['营业收入', '营业成本'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['营业收入', '营业成本'],
                           'exclude_keywords': [
                               '按行业', '按地区', '按产品', '按商品转让时间',
                               '按合同类型', '履约义务', '剩余履约',
                           ]}],
    },
    {
        'account_keywords': ['税金及附加'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['税金及附加']}],
    },
    {
        'account_keywords': ['销售费用'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['销售费用']}],
    },
    {
        'account_keywords': ['管理费用'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['管理费用']}],
    },
    {
        'account_keywords': ['研发费用'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['研发费用']}],
    },
    {
        'account_keywords': ['财务费用'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['财务费用']}],
    },
    {
        'account_keywords': ['其他收益'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['其他收益']}],
    },
    {
        'account_keywords': ['投资收益'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['投资收益']}],
    },
    {
        'account_keywords': ['公允价值变动收益', '公允价值变动损益'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['公允价值变动']}],
    },
    {
        'account_keywords': ['信用减值损失'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['信用减值损失']}],
    },
    {
        'account_keywords': ['资产减值损失'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['资产减值损失']}],
    },
    {
        'account_keywords': ['资产处置收益'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['资产处置收益']}],
    },
    {
        'account_keywords': ['营业外收入'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['营业外收入']}],
    },
    {
        'account_keywords': ['营业外支出'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['营业外支出']}],
    },
    {
        'account_keywords': ['所得税费用', '所得税'],
        'verify_tables': [{'type': 'summary', 'title_keywords': ['所得税费用', '所得税'],
                           'exclude_keywords': ['调整过程', '适用税率']}],
    },
]



def find_amount_check_preset(account_name: str) -> Optional[AmountCheckPreset]:
    """根据报表科目名称查找对应的一致性校对预设规则。

    Returns:
        匹配的预设规则，或 None（不在预设范围内，不做一致性校对）
    """
    for preset in AMOUNT_CHECK_PRESETS:
        if any(kw in account_name for kw in preset['account_keywords']):
            return preset
    return None


def should_verify_note_table(
    account_name: str,
    note_section_title: str,
    note_account_name: str,
) -> bool:
    """判断某个附注表格是否应参与报表-附注一致性校对。

    白名单匹配逻辑：
    1. 查找科目对应的预设规则
    2. 遍历 verify_tables 中的每条规则
    3. 先检查 exclude_keywords（命中则跳过该规则）
    4. 再检查 title_keywords（命中则通过）
    5. 所有规则都不匹配 → 不参与校对

    Args:
        account_name: 报表科目名称
        note_section_title: 附注表格的 section_title
        note_account_name: 附注表格的 account_name

    Returns:
        True = 应参与校对，False = 不参与
    """
    preset = find_amount_check_preset(account_name)
    if preset is None:
        return False

    combined_title = (note_section_title or '') + (note_account_name or '')
    combined_title = combined_title.replace(' ', '').replace('\u3000', '')

    for rule in preset['verify_tables']:
        exclude_kws = rule.get('exclude_keywords', [])
        if exclude_kws and any(kw in combined_title for kw in exclude_kws):
            continue

        title_kws = rule.get('title_keywords', [])
        if title_kws and any(kw in combined_title for kw in title_kws):
            return True

    return False
