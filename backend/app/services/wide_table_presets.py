"""宽表横向公式预设数据（基于上市/国企模板中的标准表格结构）。

每个预设定义了：匹配关键词、标准列结构、公式描述。
LLM 收到预设后只需确认/微调列映射，而非从零推断。

从 table_structure_analyzer.py 中抽取，便于独立维护和扩展。
"""
from typing import Dict, List

# 宽表关键词：匹配这些科目名称的表格可能是多列变动表
WIDE_TABLE_ACCOUNT_KEYWORDS: List[str] = [
    "长期股权投资", "存货跌价准备", "长期待摊费用", "开发支出",
    "在建工程", "固定资产", "无形资产", "使用权资产",
    "投资性房地产", "生产性生物资产", "油气资产", "商誉",
    "合同履约成本减值", "坏账准备", "债权投资减值准备",
    "递延所得税资产", "递延所得税负债", "长期应收款",
    "其他权益工具投资", "其他非流动金融资产",
]

# 宽表公式预设列表
WIDE_TABLE_FORMULA_PRESETS: List[Dict] = [
    {
        "name": "长期股权投资明细",
        "match_keywords": ["长期股权投资"],
        "match_title_keywords": ["明细", "对联营", "对合营", "对子公司"],
        "exclude_title_keywords": ["分类", "减值测试"],
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
        "name": "在建工程项目变动",
        "match_keywords": ["在建工程"],
        "match_title_keywords": ["重要在建工程", "在建工程项目变动", "在建工程变动"],
        "exclude_title_keywords": ["减值"],
        "template_columns": [
            {"role": "label", "name": "工程名称"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "本期增加"},
            {"role": "movement", "sign": "-", "name": "转入固定资产"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "skip", "name": "利息资本化累计金额"},
            {"role": "skip", "name": "本期利息资本化金额"},
            {"role": "skip", "name": "本期利息资本化率%"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 本期增加 - 转入固定资产 - 其他减少 = 期末余额",
    },
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
    {
        "name": "存货跌价准备变动",
        "match_keywords": ["存货跌价准备", "合同履约成本减值"],
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
    {
        "name": "商誉账面原值/减值准备变动",
        "match_keywords": ["商誉"],
        "match_title_keywords": ["账面原值", "减值准备"],
        "exclude_title_keywords": ["减值测试"],
        "template_columns": [
            {"role": "label", "name": "被投资单位/事项"},
            {"role": "opening", "sign": "+", "name": "期初余额"},
            {"role": "movement", "sign": "+", "name": "企业合并形成/计提"},
            {"role": "movement", "sign": "+", "name": "其他增加"},
            {"role": "movement", "sign": "-", "name": "处置"},
            {"role": "movement", "sign": "-", "name": "其他减少"},
            {"role": "closing", "sign": "=", "name": "期末余额"},
        ],
        "formula": "期初余额 + 增加项 - 减少项 = 期末余额",
    },
    # ── 固定资产（国企版：多段变动表，每段独立公式）──
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
    # ── 固定资产（上市版：分类合计型，列为资产类别，行为变动项目）──
    # 上市版由 _try_build_category_sum_from_headers 自动检测，此处不需要额外预设
    # ── 无形资产（国企版：多段变动表）──
    {
        "name": "无形资产变动-国企版",
        "match_keywords": ["无形资产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值", "未办妥", "抵押", "出租", "开发支出"],
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
    # ── 使用权资产（国企版：多段变动表）──
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
    # ── 投资性房地产（国企版：多段变动表）──
    {
        "name": "投资性房地产变动-国企版",
        "match_keywords": ["投资性房地产"],
        "match_title_keywords": [],
        "exclude_title_keywords": ["减值", "公允价值"],
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
    # ── 生产性生物资产（国企版：多段变动表）──
    {
        "name": "生产性生物资产变动-国企版",
        "match_keywords": ["生产性生物资产"],
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
    # ── 坏账准备变动（应收账款/其他应收款等）──
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
    # ── 递延所得税资产/负债变动 ──
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
]
