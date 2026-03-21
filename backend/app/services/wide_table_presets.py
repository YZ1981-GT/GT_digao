"""宽表横向公式预设数据（基于上市/国企模板中的标准表格结构）。

每个预设定义了：匹配关键词、标准列结构、公式描述。
LLM 收到预设后只需确认/微调列映射，而非从零推断。

从 table_structure_analyzer.py 中抽取，便于独立维护和扩展。

预设分为两大类：
1. movement（变动公式型）：期初 + 变动项 = 期末（国企版常见）
2. category_sum（分类合计型）：各分类列之和 = 合计列（上市版常见）

国企版和上市版的主要差异：
- 固定资产/无形资产/使用权资产等：国企版为 movement（行=资产类别，列=期初/增加/减少/期末），
  上市版为 category_sum（行=变动项目，列=资产类别+合计），由 _try_build_category_sum_from_headers 自动检测
- 长期股权投资明细、坏账准备变动等：两版结构基本一致
"""
from typing import Dict, List

# ────────────────────────────────────────────────────────────
# 宽表关键词：匹配这些科目名称的表格可能是多列变动表
# ────────────────────────────────────────────────────────────
WIDE_TABLE_ACCOUNT_KEYWORDS: List[str] = [
    "长期股权投资", "存货跌价准备", "长期待摊费用", "开发支出",
    "在建工程", "固定资产", "无形资产", "使用权资产",
    "投资性房地产", "生产性生物资产", "油气资产", "商誉",
    "合同履约成本减值", "坏账准备", "债权投资减值准备",
    "递延所得税资产", "递延所得税负债", "长期应收款",
    "其他权益工具投资", "其他非流动金融资产",
    # ── 新增：权益类、薪酬类、递延收益等 ──
    "应付职工薪酬", "资本公积", "盈余公积", "专项储备",
    "递延收益", "实收资本", "股本", "库存股",
    "其他债权投资", "持有待售资产",
    "设定受益计划",
]

# ────────────────────────────────────────────────────────────
# 宽表公式预设列表
# ────────────────────────────────────────────────────────────
WIDE_TABLE_FORMULA_PRESETS: List[Dict] = [
    # ══════════════════════════════════════════════════════════
    # 一、长期股权投资
    # ══════════════════════════════════════════════════════════
    {
        "name": "长期股权投资明细",
        "match_keywords": ["长期股权投资"],
        "match_title_keywords": ["明细", "对联营", "对合营", "对子公司"],
        "exclude_title_keywords": ["分类", "减值测试", "主要财务信息"],
        "template_columns": [
            {"role": "label", "name": "被投资单位"},
            {"role": "opening", "sign": "+", "name": "期初余额(账面价值)"},
            {"role": "skip", "name": "减值准备期初余额"},
            {"role": "movement", "sign": "+", "name": "追加/新增投资"},
            {"role": "movement", "sign": "-", "name": "减少投资"},
            {"role": "movement", "sign": "+", "name": "权益法下确认的投资损益"},
            {"role": "movement", "sign": "+", "name": "其他综合收益调整"},
            {"role": "movement", "sign": "+", "name": "其他权益变动"},
            {"role": "movement", "sign": "-", "name": "宣告发放现金股利或利润"},
            {"role": "movement", "sign": "-", "name": "计提减值准备"},
            {"role": "movement", "sign": "+", "name": "其他"},
            {"role": "closing", "sign": "=", "name": "期末余额(账面价值)"},
            {"role": "skip", "name": "减值准备期末余额"},
        ],
        "formula": "期初账面价值 + 追加投资 + 投资损益 + 其他综合收益 + 其他权益变动 - 减少投资 - 现金股利 - 计提减值 + 其他 = 期末账面价值",
    },
    {
        "name": "长期股权投资分类",
        "match_keywords": ["长期股权投资"],
        "match_title_keywords": ["分类"],
        "exclude_title_keywords": ["明细", "减值测试"],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 二、在建工程
    # ══════════════════════════════════════════════════════════
    {
        "name": "在建工程项目变动",
        "match_keywords": ["在建工程"],
        "match_title_keywords": ["重要在建工程", "在建工程项目变动", "在建工程变动"],
        "exclude_title_keywords": ["减值"],
        "template_columns": [
            {"role": "label", "name": "工程名称"},
            {"role": "skip", "name": "预算数"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "转入固定资产"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
            {"role": "skip", "name": "工程累计投入占预算比例"},
            {"role": "skip", "name": "工程进度"},
            {"role": "skip", "name": "利息资本化累计金额"},
            {"role": "skip", "name": "本期利息资本化金额"},
            {"role": "skip", "name": "本期利息资本化率%"},
            {"role": "skip", "name": "资金来源"},
        ],
        "formula": "期初余额 + 本期增加 - 转入固定资产 - 其他减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 三、长期待摊费用
    # ══════════════════════════════════════════════════════════
    {
        "name": "长期待摊费用",
        "match_keywords": ["长期待摊费用"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期摊销"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期摊销 - 其他减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 四、开发支出
    # ══════════════════════════════════════════════════════════
    {
        "name": "开发支出",
        "match_keywords": ["开发支出"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值准备", "重要的资本化"],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "内部开发支出"},
            {"role": "movement", "sign": "+", "name": "其他增加"},
            {"role": "movement", "sign": "-", "name": "确认为无形资产"},
            {"role": "movement", "sign": "-", "name": "计入当期损益"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 内部开发支出 + 其他增加 - 确认为无形资产 - 计入当期损益 - 其他减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 五、存货跌价准备 / 合同履约成本减值准备
    # ══════════════════════════════════════════════════════════
    {
        "name": "存货跌价准备变动",
        "match_keywords": ["存货跌价准备", "合同履约成本减值", "存货"],
        "match_title_keywords": ["跌价准备", "减值准备"],
        "exclude_title_keywords": ["按组合", "按单项"],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "计提"},
            {"role": "movement", "sign": "+", "name": "其他增加"},
            {"role": "movement", "sign": "-", "name": "转回或转销"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 计提 + 其他增加 - 转回或转销 - 其他减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 六、商誉
    # ══════════════════════════════════════════════════════════
    {
        "name": "商誉账面原值变动",
        "match_keywords": ["商誉"],
        "match_title_keywords": ["账面原值"],
        "exclude_title_keywords": ["减值测试"],
        "template_columns": [
            {"role": "label", "name": "被投资单位/事项"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "企业合并形成"},
            {"role": "movement", "sign": "+", "name": "其他增加"},
            {"role": "movement", "sign": "-", "name": "处置"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 企业合并形成 + 其他增加 - 处置 - 其他减少 = 期末余额",
    },
    {
        "name": "商誉减值准备变动",
        "match_keywords": ["商誉"],
        "match_title_keywords": ["减值准备"],
        "exclude_title_keywords": ["减值测试"],
        "template_columns": [
            {"role": "label", "name": "被投资单位/事项"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "计提"},
            {"role": "movement", "sign": "+", "name": "其他增加"},
            {"role": "movement", "sign": "-", "name": "处置"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 计提 + 其他增加 - 处置 - 其他减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 七、固定资产（国企版：多段变动表）
    # ══════════════════════════════════════════════════════════
    # 国企版：行=资产类别，列=期初/增加/减少/期末，多段（原值/折旧/减值/账面价值）
    # 上市版：行=变动项目，列=资产类别+合计 → category_sum，由自动检测处理
    {
        "name": "固定资产变动-国企版",
        "match_keywords": ["固定资产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["清理", "减值", "暂时闲置", "未办妥", "抵押", "出租"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 八、无形资产（国企版：多段变动表）
    # ══════════════════════════════════════════════════════════
    {
        "name": "无形资产变动-国企版",
        "match_keywords": ["无形资产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值", "未办妥", "抵押", "出租", "开发支出", "数据资源"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 九、使用权资产（国企版：多段变动表）
    # ══════════════════════════════════════════════════════════
    {
        "name": "使用权资产变动-国企版",
        "match_keywords": ["使用权资产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 十、投资性房地产
    # ══════════════════════════════════════════════════════════
    {
        "name": "投资性房地产-成本计量",
        "match_keywords": ["投资性房地产"],
        "match_title_keywords": ["成本计量"],
        "exclude_title_keywords": ["减值", "公允价值", "未办妥"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "购置或计提"},
            {"role": "movement", "sign": "+", "name": "自用房地产或存货转入"},
            {"role": "movement", "sign": "-", "name": "处置"},
            {"role": "movement", "sign": "-", "name": "转为自用房地产"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 购置或计提 + 转入 - 处置 - 转为自用 = 期末余额",
        "multi_section": True,
    },
    {
        "name": "投资性房地产-公允价值计量",
        "match_keywords": ["投资性房地产"],
        "match_title_keywords": ["公允价值"],
        "exclude_title_keywords": ["减值", "未办妥"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初公允价值"},
            {"role": "movement", "sign": "+", "name": "购置"},
            {"role": "movement", "sign": "+", "name": "自用房地产或存货转入"},
            {"role": "movement", "sign": "+", "name": "公允价值变动损益"},
            {"role": "movement", "sign": "-", "name": "处置"},
            {"role": "movement", "sign": "-", "name": "转为自用房地产"},
            {"role": "closing", "sign": "=", "name": "期末公允价值"},
        ],
        "formula": "期初公允价值 + 购置 + 转入 + 公允价值变动 - 处置 - 转为自用 = 期末公允价值",
        "multi_section": True,
    },
    # 通用兜底（无标题关键词时）
    {
        "name": "投资性房地产变动-国企版",
        "match_keywords": ["投资性房地产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值", "公允价值", "未办妥"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 十一、生产性生物资产
    # ══════════════════════════════════════════════════════════
    {
        "name": "生产性生物资产变动",
        "match_keywords": ["生产性生物资产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初账面价值"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末账面价值"},
        ],
        "formula": "期初账面价值 + 本期增加 - 本期减少 = 期末账面价值",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 十二、油气资产（国企版：多段变动表）
    # ══════════════════════════════════════════════════════════
    {
        "name": "油气资产变动",
        "match_keywords": ["油气资产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值"],
        "template_columns": [
            {"role": "label", "name": "项目/类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 十三、坏账准备变动
    # ══════════════════════════════════════════════════════════
    {
        "name": "坏账准备变动",
        "match_keywords": ["坏账准备", "应收账款", "其他应收款", "应收票据", "长期应收款"],
        "match_title_keywords": ["坏账准备变动", "坏账准备计提"],
        "exclude_title_keywords": ["按组合", "按单项", "账龄", "分类"],
        "template_columns": [
            {"role": "label", "name": "类别"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "计提"},
            {"role": "movement", "sign": "+", "name": "其他增加"},
            {"role": "movement", "sign": "-", "name": "收回或转回"},
            {"role": "movement", "sign": "-", "name": "核销"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 计提 + 其他增加 - 收回或转回 - 核销 - 其他减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 十四、递延所得税资产/负债
    # ══════════════════════════════════════════════════════════
    {
        "name": "递延所得税变动",
        "match_keywords": ["递延所得税资产", "递延所得税负债"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["抵销", "相抵"],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "skip", "name": "暂时性差异期末"},
            {"role": "closing", "sign": "=", "name": "递延所得税期末余额"},
            {"role": "skip", "name": "暂时性差异期初"},
            {"role": "opening", "sign": "+", "name": "递延所得税期初余额"},
        ],
        "formula": "（含暂时性差异列，仅校验递延所得税列的期初→期末变动）",
    },

    # ══════════════════════════════════════════════════════════
    # 十五、债权投资减值准备
    # ══════════════════════════════════════════════════════════
    {
        "name": "债权投资减值准备变动",
        "match_keywords": ["债权投资"],
        "match_title_keywords": ["减值准备"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 十六、其他债权投资减值准备
    # ══════════════════════════════════════════════════════════
    {
        "name": "其他债权投资减值准备变动",
        "match_keywords": ["其他债权投资"],
        "match_title_keywords": ["减值准备"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 十七、持有待售资产减值准备
    # ══════════════════════════════════════════════════════════
    {
        "name": "持有待售资产减值准备变动",
        "match_keywords": ["持有待售资产"],
        "match_title_keywords": ["减值准备"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期转回"},
            {"role": "movement", "sign": "-", "name": "本期出售"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期转回 - 本期出售 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 十八、应付职工薪酬
    # ══════════════════════════════════════════════════════════
    {
        "name": "应付职工薪酬列示",
        "match_keywords": ["应付职工薪酬"],
        "match_title_keywords": ["列示", "薪酬"],
        "exclude_title_keywords": ["短期薪酬", "设定提存", "设定受益", "长期应付"],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
    {
        "name": "短期薪酬列示",
        "match_keywords": ["应付职工薪酬"],
        "match_title_keywords": ["短期薪酬"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
    {
        "name": "设定提存计划列示",
        "match_keywords": ["应付职工薪酬"],
        "match_title_keywords": ["设定提存"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 十九、递延收益
    # ══════════════════════════════════════════════════════════
    {
        "name": "递延收益变动",
        "match_keywords": ["递延收益"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
    {
        "name": "递延收益-政府补助",
        "match_keywords": ["递延收益"],
        "match_title_keywords": ["政府补助"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "补助项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期新增补助金额"},
            {"role": "movement", "sign": "-", "name": "本期计入损益金额"},
            {"role": "skip", "name": "本期计入损益的列报项目"},
            {"role": "movement", "sign": "-", "name": "本期返还的金额"},
            {"role": "movement", "sign": "+", "name": "其他变动"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
            {"role": "skip", "name": "与资产相关/与收益相关"},
            {"role": "skip", "name": "本期返还的原因"},
        ],
        "formula": "期初余额 + 新增补助 - 计入损益 - 返还 + 其他变动 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 二十、权益类科目
    # ══════════════════════════════════════════════════════════
    {
        "name": "实收资本/股本变动",
        "match_keywords": ["实收资本", "股本"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["溢价"],
        "template_columns": [
            {"role": "label", "name": "投资者名称"},
            {"role": "opening", "sign": "+", "name": "期初余额/投资金额"},
            {"role": "skip", "name": "所占比例"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额/投资金额"},
            {"role": "skip", "name": "所占比例"},
        ],
        "formula": "期初投资金额 + 本期增加 - 本期减少 = 期末投资金额",
    },
    {
        "name": "资本公积变动",
        "match_keywords": ["资本公积"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
    {
        "name": "专项储备变动",
        "match_keywords": ["专项储备"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
    {
        "name": "盈余公积变动",
        "match_keywords": ["盈余公积"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
    {
        "name": "库存股变动",
        "match_keywords": ["库存股"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 二十一、设定受益计划净资产（上市版特有）
    # ══════════════════════════════════════════════════════════
    {
        "name": "设定受益计划净资产变动",
        "match_keywords": ["设定受益计划"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 二十二、数据资源（无形资产/存货）
    # ══════════════════════════════════════════════════════════
    {
        "name": "数据资源无形资产变动",
        "match_keywords": ["无形资产", "数据资源"],
        "match_title_keywords": ["数据资源"],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加金额"},
            {"role": "movement", "sign": "-", "name": "本期减少金额"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
        "multi_section": True,
    },

    # ══════════════════════════════════════════════════════════
    # 二十三、长期应付职工薪酬
    # ══════════════════════════════════════════════════════════
    {
        "name": "长期应付职工薪酬变动",
        "match_keywords": ["长期应付职工薪酬"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 二十四、专项应付款
    # ══════════════════════════════════════════════════════════
    {
        "name": "专项应付款变动",
        "match_keywords": ["专项应付款"],
        "match_title_keywords": [],
        "exclude_title_keywords": [],
        "template_columns": [
            {"role": "label", "name": "项目"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },

    # ══════════════════════════════════════════════════════════
    # 二十五、开发产品（房地产企业）
    # ══════════════════════════════════════════════════════════
    {
        "name": "开发产品变动",
        "match_keywords": ["开发产品", "存货"],
        "match_title_keywords": ["开发产品"],
        "exclude_title_keywords": ["跌价准备"],
        "template_columns": [
            {"role": "label", "name": "项目名称"},
            {"role": "skip", "name": "竣工时间"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "本期减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
            {"role": "skip", "name": "期末跌价准备"},
        ],
        "formula": "期初余额 + 本期增加 - 本期减少 = 期末余额",
    },
]
