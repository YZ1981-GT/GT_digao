"""基于模板的审计文档生成服务。

核心流程参照现有审计文档程序的章节拆分和内容生成模式：
1. 用户上传模板文件（审计计划、审计小结、尽调报告等）
2. 调用 extract_template_outline() 通过LLM自动识别模板中的章节结构
3. 用户在前端确认/调整章节大纲
4. 逐章节调用 _generate_section_content() 流式生成内容
5. 每个章节支持手动编辑和AI对话式修改
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..models.audit_schemas import (
    DocumentExportRequest,
    FontSettings,
    GeneratedDocument,
    GeneratedSection,
    ProjectInfo,
    SectionRevisionRequest,
    TemplateOutlineItem,
)
from .knowledge_service import knowledge_service
from .knowledge_retriever import knowledge_retriever
from .openai_service import OpenAIService, estimate_token_count, truncate_to_token_limit, _get_context_limit, OUTPUT_RESERVE_RATIO
from .template_service import TemplateManager
from .word_service import WordExportService

logger = logging.getLogger(__name__)


# 审计文档生成系统提示词
_AUDIT_DOCUMENT_SYSTEM_PROMPT = """你是致同会计师事务所的资深合伙人，具有二十年以上审计执业经验，现在正在亲自撰写审计工作底稿和报告文档。

【核心规则】
1. 如果提供了知识库参考资料，优先使用其中的真实信息
2. 即使没有知识库资料，也必须根据项目信息（客户名称、审计期间等）和你的审计专业知识，生成完整、有实质内容的章节
3. 结合章节标题和上下文结构，输出符合该章节定位的专业审计内容
4. 只有确实需要具体数据的地方（如具体金额、具体日期、具体人员姓名、具体合同编号等）才标注【待补充】
5. 审计程序、方法论、风险评估框架、内控描述等专业内容不需要标【待补充】，应直接撰写
6. 使用专业的审计术语和规范的文档格式
7. 直接输出正文内容，不要输出章节标题或元信息

【写作风格——严格遵守】
你的文字必须读起来像一位经验丰富的注册会计师亲笔撰写的正式文档，而非AI生成的内容。具体要求：

1. 语言风格：
   - 使用会计师事务所正式公文的语体，措辞严谨、平实、克制
   - 句式以陈述句为主，语气客观冷静，避免任何煽动性或宣传性表述
   - 多用"本所"、"我们"、"项目组"等第一人称专业表述
   - 善用"根据……的规定"、"经审计程序执行"、"经核查"等审计惯用表达

2. 结构与行文：
   - 段落长短自然变化，不要每段都是三句话的固定模式
   - 避免机械化的并列分点，适当使用连贯的段落叙述
   - 论述时先说结论或判断，再展开依据和过程
   - 过渡自然，不要用"首先……其次……最后……"这类模板化连接词

3. 绝对禁止使用的词汇和表达：
   - 禁止：赋能、闭环、抓手、打通、全方位、多维度、深度融合、无缝衔接、保驾护航
   - 禁止：旨在、致力于、不断提升、持续优化、积极推进、有效保障
   - 禁止：值得注意的是、需要指出的是、综上所述（除非确实在总结全文）
   - 禁止：在……背景下、随着……的不断发展、在……的大环境下
   - 禁止使用感叹号

4. 推荐使用的表达方式：
   - "本次审计中，我们对……实施了……程序"
   - "经查阅……并与管理层沟通，我们了解到……"
   - "根据《中国注册会计师审计准则第XXXX号》的要求"
   - "项目组对上述事项进行了专项分析，认为……"
   - "基于已获取的审计证据，我们认为……"

5. 不要使用Markdown标题格式（# ## ###），用中文序号组织层次
"""

# 大纲提取系统提示词
_OUTLINE_EXTRACTION_PROMPT = """你是一位审计文档结构分析专家。请分析以下模板文本，识别其中的章节结构。

请返回一个JSON数组，每个元素代表一个章节，格式如下：
[
  {
    "id": "1",
    "title": "章节标题",
    "description": "章节内容概述",
    "target_word_count": 1500,
    "fillable_fields": ["需要填充的字段1", "需要填充的字段2"],
    "children": [
      {
        "id": "1.1",
        "title": "子章节标题",
        "description": "子章节内容概述",
        "target_word_count": 800,
        "fillable_fields": [],
        "children": []
      }
    ]
  }
]

要求：
1. 准确识别标题层级关系（一级、二级、三级标题）
2. 为每个章节估算合理的目标字数
3. 识别需要填充的字段（如客户名称、审计期间等）
4. description 简要描述该章节应包含的内容
5. 只返回JSON数组，不要包含其他文字
"""

# ─── 预置大纲模板 ───
# 按模板类型存储标准大纲结构，当结构化解析和文件重解析都失败时，
# 根据模板类型匹配预置大纲，避免调用 LLM。
# 关键词列表用于从模板文本中模糊匹配模板类型。

_PRESET_OUTLINES: Dict[str, Dict] = {
    "audit_plan": {
        "name": "总体审计策略及具体审计计划",
        "keywords": ["审计计划", "总体审计策略", "审计工作范围", "审计安排", "重大错报风险", "具体审计计划", "审计策略"],
        "min_keyword_matches": 2,
        "outline": [
            {
                "id": "1", "title": "审计工作范围", "description": "确定审计业务的特征以界定审计范围，明确报告目标以计划审计的时间安排和所需沟通性质",
                "target_word_count": 3000, "fillable_fields": ["客户名称", "审计期间"], "children": [
                    {"id": "1.1", "title": "委托事项", "description": "说明以前曾委托事项（最近三年的财务报表审计、中期审阅、其他鉴证等，如系首次接受委托也请注明）和当期委托事项。如同时承接财务报表审计和内部控制审计，应采用整合审计方法。", "target_word_count": 800, "fillable_fields": ["客户名称"], "children": []},
                    {"id": "1.2", "title": "报告准则要求", "description": "填写适用的会计准则、审计准则等，包括：适用的财务报告编制基础（企业会计准则及其应用指南、解释等）、与财务报告相关的行业特别规定（如证监会、交易所、银监会、国资委、财政部等发布的信息披露法规）、适用的审计准则（中国注册会计师执业准则及相关规定）、制定审计策略需考虑的其他事项（如特殊编制基础、补充信息、其他报告责任等）。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                    {"id": "1.3", "title": "报告时间要求", "description": "填写各类拟出具业务报告的时间节点，包括：财务报表审计报告、控股股东及其他关联方占用资金情况专项说明、内控制度鉴证报告（如适用）、募集资金专项审核报告（如适用）、营业收入扣除情况说明专项核查报告（如适用）、ESG鉴证报告（如适用）等。", "target_word_count": 600, "fillable_fields": [], "children": []},
                    {"id": "1.4", "title": "需单独出具审计报告的组成部分情况", "description": "列明需单独出具审计报告的组成部分名称、注册地、与集团关系（子公司/分公司/控股/重大影响等）、组成部分注册会计师（集团项目组/致同分所/致同网络成员所/其他事务所）、与组成部分会计师沟通的初步时间安排。若非集团审计，说明不适用。", "target_word_count": 600, "fillable_fields": [], "children": []},
                    {"id": "1.5", "title": "已开展的初步业务活动", "description": "填写已完成的初步业务活动程序及索引号，包括：业务评价及风险评价、与前任注册会计师的沟通、独立性检查、已签订的业务约定书等。", "target_word_count": 500, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "2", "title": "被审计单位基本情况及本期重大变化", "description": "客户基本信息、行业特点及本期重大变化事项",
                "target_word_count": 3000, "fillable_fields": ["客户名称"], "children": [
                    {"id": "2.1", "title": "基本情况", "description": "简述被审计单位所处行业、经营范围、主要产品或劳务、市场、关键环境因素、注册资本及股权结构等（不能简单复制财务报表附注中的历史沿革）。包括：所有权性质、母公司、实际控制人、注册资本、经营范围、注册地址、办公地址。适用于上市实体的还需说明：上市日期、上市后公司名称/控股股东/实际控制人的变化情况、与现有主营业务相关的重大资产重组情况（如业绩承诺和大额商誉等）、证监会行业分类。", "target_word_count": 1500, "fillable_fields": ["客户名称"], "children": []},
                    {"id": "2.2", "title": "本期重大变化", "description": "影响被审计单位的重大业务发展变化，需同时说明这种变化对审计工作的影响。包括：（1）外部环境或行业监管政策的重大变化；（2）主要业务和产品的变化情况（包括重大客户和供应商的变化）；（3）本期重大收购兼并情况；（4）关键管理人员变化情况；（5）重要会计政策、会计估计及其变更情况；（6）报告期接受监管调查情况（包括被审计单位和其审计机构被监管调查的情形）；（7）其他变化情况。", "target_word_count": 1500, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "3", "title": "审计安排", "description": "审计团队组成、时间安排、工作分工、专家利用及沟通安排",
                "target_word_count": 4000, "fillable_fields": [], "children": [
                    {"id": "3.1", "title": "执行审计时间安排", "description": "按计划审计工作阶段、审计实施阶段、报告及沟通阶段分别列明初步时间计划。计划阶段包括：项目启动会、计划阶段项目组讨论会、制订总体审计策略、中介机构协调会等。实施阶段包括：存货监盘、银行流水查阅及核对、客户供应商工商档案取得与核对、客户供应商走访、外部调查等。报告阶段包括：提交项目质量复核、提交专业技术委员会审核、项目总结会等。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "3.2", "title": "人员安排", "description": "（1）项目组关键成员：记录职位、姓名及主要职责（项目合伙人、授权签字注册会计师等）；（2）项目组其他成员：组成部分负责人、内控现场负责人及其他成员的工作分工和时间安排；（3）项目质量复核合伙人的委派（A类业务应进行项目质量复核）；（4）质量控制复核人的指定（A类及B类业务应进行质量控制复核）；（5）专业技术复核人的指定（境外上市业务或事务所特别安排）；（6）税务复核人的指定（IPO审计、上市公司重大资产重组审计、税务事项复杂或风险较高的审计业务）。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                    {"id": "3.3", "title": "审计项目工时预算与控制", "description": "审计项目的工时预算分配和实际执行情况，确保审计资源合理配置", "target_word_count": 400, "fillable_fields": [], "children": []},
                    {"id": "3.4", "title": "利用专家及其他的工作", "description": "（1）对注册会计师专家工作的利用：是否需要利用专家工作及哪方面专家，记录利用领域、专家姓名、主要职责及工作范围、利用原因、专家来源（内部/外部）。内部专家应遵守与审计项目组成员相同的独立性要求。（2）对内部审计人员工作的利用：主要利用领域、利用策略、拟利用的内部审计工作内容。（3）对其他注册会计师工作的利用：主要适用于委托其他注册会计师对存放在偏远地点的存货实施监盘、固定资产检查、银行账户函证、实地走访客户或供应商等。（4）对被审计单位使用的服务机构工作的利用。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "3.5", "title": "对首次承接审计的考虑", "description": "首次承接审计业务需考虑的补充事项：与前任注册会计师沟通（查阅前任注册会计师工作底稿）、与管理层讨论首次接受审计委托的重大问题、为针对期初余额获取充分适当审计证据而需实施的审计程序、事务所质量控制制度规定的其他程序（如首次承接的上市公司年审业务需经专业技术委员会审核）。如不适用请说明。", "target_word_count": 500, "fillable_fields": [], "children": []},
                    {"id": "3.6", "title": "对被审计单位运用信息技术导致的风险的考虑", "description": "评估IT审计的适用情形（IPO/上市公司整合审计、复杂金融企业、互联网企业、发债/新三板公司等），确定信息系统复杂性，安排具有信息技术专业技能的项目组成员参与审计工作（咨询/指导/IT团队执行相关测试程序三种模式）。", "target_word_count": 600, "fillable_fields": [], "children": []},
                    {"id": "3.7", "title": "沟通的时间安排", "description": "（1）项目组与被审计单位沟通：记录各层面审计人员与企业人员沟通的事项、方式和时间安排，包括进场前与独立董事/审计委员会的沟通、与管理层沟通、与治理层沟通、出具初步审计意见后的再次沟通等。（2）项目组与监管机构的沟通：与所在地证监局、国资委、银保监管部门等的沟通事项、方式和时间安排。", "target_word_count": 600, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "4", "title": "未审财务报表的总体分析", "description": "对公司合并的未审计财务报表进行分析。对主要报表项目（如占总资产10%或收入10%的有关项目）结构分析，以及项目金额异常或年度间变动异常（如占公司报表日资产总额5%或报告期利润总额10%以上，且两个期间的数据变动幅度达20%以上）的有关分析结果详细记录。可以有针对性的记录分析出的可能存在的风险和拟实施的应对措施。针对IPO审计，除对最近一期财务报表进行分析之外，应对申报期财务报表进行整体分析，关注各申报期的业绩波动、收入增长和毛利变化情况，以及是否存在收入和成本费用的截止性差异。",
                "target_word_count": 3000, "fillable_fields": [], "children": [
                    {"id": "4.1", "title": "未审财务报表横向、纵向分析", "description": "（1）财务报表数据：对金额异常或年度间变动异常的报表项目逐项分析变动原因，说明审计过程中拟重点关注的事项和拟执行的审计程序。（2）财务指标：对主要财务指标进行分析，包括每股收益、每股净资产、每股经营活动产生的现金流量净额、净资产收益率、总资产净利润、销售净利率、销售毛利率、期间费用净利率、资产负债率、存货周转率、应收账款周转率、流动比率、速动比率等。", "target_word_count": 1200, "fillable_fields": [], "children": []},
                    {"id": "4.2", "title": "同行业公司对比分析", "description": "主要适用于证券期货业务（上市公司、IPO公司、发债企业等）。选取3-5家同行业对标公司，对比重要财务指标（如净资产收益率、毛利率、存货周转率、应收账款周转率、销售费用率、管理费用率等），分析数据和趋势的不一致及其原因和合理性。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "4.3", "title": "财务与非财务信息印证", "description": "主要适用于证券期货业务。（1）整体经营情况与财务数据的一致性：分析公司整体经营情况与营业收入、营业成本、管理费用、销售费用等财务数据的一致性。（2）财务与非财务信息的印证：分析已审报表与公司招股说明书、法律意见书中相关信息的一致性，以及水电煤消耗量、一线生产员工人数变动与产量变动是否匹配。（3）异常的财务指标：分析会计政策会计估计的一致性与同行业可比性、财务数据异常变动原因及合理性、人工成本合理性、固定资产和在建工程余额变动合理性。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "5", "title": "重要性水平的初步确定", "description": "确定财务报表整体重要性水平、实际执行的重要性水平和明显微小错报临界值",
                "target_word_count": 2000, "fillable_fields": [], "children": [
                    {"id": "5.1", "title": "初步确定重要性水平", "description": "确定基准（如税前利润、营业收入或资产总额）、财务报表整体的重要性水平、实际执行的重要性水平、临界值（明显微小的错报）。对于以营利为目的的实体，通常以经营性业务的税前利润作为基准；如果税前利润不稳定，选用毛利或营业收入等其他基准可能更合适。如上市公司、IPO公司、发债企业、新三板公司使用的重要性水平基准不是税前利润或百分比大于5%，应履行业务咨询程序。", "target_word_count": 1200, "fillable_fields": [], "children": []},
                    {"id": "5.2", "title": "为一个或多个特定类别的交易、账户余额或披露确定较低的重要性水平", "description": "对于受到中小股东和监管机构高度关注的项目（如关联交易）、可能影响盈亏逆转的项目（如信用减值损失）、以前年度审计曾发现差异的项目（如存货）等，确定较低的重要性和实际执行的重要性水平，说明选取较低重要性的原因和基准。", "target_word_count": 800, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "6", "title": "识别的重大错报风险汇总", "description": "各层次重大错报风险的汇总分析及详细应对措施计划",
                "target_word_count": 4000, "fillable_fields": [], "children": [
                    {"id": "6.1", "title": "财务报表层次的重大错报风险汇总（含舞弊风险的识别）", "description": "列表汇总财务报表层次的重大错报风险，包括风险因素、风险描述、是否属于特别风险、是否与舞弊相关。典型风险如：管理层凌驾于控制之上的风险（特别风险/舞弊相关）、IT一般控制环境及控制流程变化导致的广泛影响财务报表的风险等。", "target_word_count": 1200, "fillable_fields": [], "children": []},
                    {"id": "6.2", "title": "认定层次的重大错报风险汇总", "description": "列表汇总认定层次的重大错报风险，包括风险因素、风险描述、相关的财务报表项目或披露、相关认定、是否属于特别风险、是否与舞弊相关。注册会计师应当恰当识别和评估收入相关重大错报风险，了解被审计单位及其环境的复杂程度，识别收入舞弊风险因素或异常迹象，了解重要客户供应商的资信状况，对涉及存在未披露关联方及其交易的迹象设计恰当的应对措施。", "target_word_count": 1200, "fillable_fields": [], "children": []},
                    {"id": "6.3", "title": "重大错报风险应对措施详细计划", "description": "针对识别出的重大错报风险，制定详细的应对措施和审计程序。（1）财务报表层次重大错报风险应对措施：如向项目组强调保持职业怀疑、分派更有经验的项目组成员、提供更多督导、增加不可预见性等。（2）认定层次重大错报风险应对措施：针对收入舞弊等风险，说明具体审计程序（函证、实地走访、检查原始单据等）、样本量、执行人。（3）仅金额重大项目的应对措施。", "target_word_count": 1600, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "7", "title": "相关交易类别、账户余额和披露及仅金额重大的项目", "description": "SCOT+项目及仅金额重大的项目的识别和审计方案",
                "target_word_count": 2000, "fillable_fields": [], "children": [
                    {"id": "7.1", "title": "相关交易类别、账户余额和披露（SCOT+）", "description": "此部分的SCOT+名称应该与前述认定层次的重大错报风险汇总中识别出的认定层次重大错报风险相对应。列明识别出的底稿索引号、相关交易类别/账户余额和披露名称、所包括的具体交易/账户和披露、拟采取的方案（综合性/实质性）。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                    {"id": "7.2", "title": "仅金额重大的项目", "description": "对于仅金额重大的交易、账户和披露，在财务报表审计中至少应当采取实质性方案。项目组如拟信赖内部控制运行有效，也可以采用综合性方案。在整合审计中，项目组应当考虑对企业生产经营活动中的重要业务与事项实施业务层面控制测试。列明识别出的底稿索引号、仅金额重大的交易/账户余额和披露、拟采取的方案。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "8", "title": "对集团财务报表审计的特殊考虑", "description": "如果拟利用组成部分注册会计师的工作，按集团审计计划记录。实施集团审计时，根据组成部分的财务重大性、可能导致集团财务报表发生重大错报的特别风险，将组成部分分类为具有财务重大性的组成部分、具有特别风险的组成部分以及不重要的组成部分，并分别制订相应的审计策略。如承接的客户存在境外业务时，应由本所人员出境执业或恰当利用境外网络所、境外组成部分注册会计师的工作。",
                "target_word_count": 2500, "fillable_fields": [], "children": [
                    {"id": "8.1", "title": "初步识别的重要组成部分", "description": "（1）单个组成部分对集团具有财务重大性：列明重要组成部分、审计策略（使用组成部分重要性对组成部分财务信息实施审计）、亲自执行或利用组成部分注册会计师工作。（2）由于单个组成部分的特定性质或情况可能导致合并财务报表发生重大错报的特别风险：列明组成部分、审计策略（审计与该风险相关的账户余额/交易/事项，或特定审计）。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                    {"id": "8.2", "title": "不重要的组成部分", "description": "如在集团层面实施分析程序不能获得充分适当的审计证据，进一步识别并选择组成部分。列明不重要的组成部分、审计策略（审计/审阅/在集团层面实施分析程序）、亲自执行或利用组成部分注册会计师工作。如单独出具审计报告，则需按照单独一项审计业务执行审计程序。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "8.3", "title": "组成部分的重要性水平", "description": "组成部分的重要性水平适用于基于集团审计目的，组成部分注册会计师对该组成部分财务信息实施审计。如不适用集团审计，说明不存在利用组成部分注册会计师工作。", "target_word_count": 400, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "9", "title": "关键审计事项", "description": "本部分内容主要适用于上市实体整套通用目的财务报表的审计业务，以及注册会计师认为需要在审计报告沟通关键审计事项的情形。其他情形的审计业务应标注不适用。",
                "target_word_count": 1500, "fillable_fields": [], "children": [
                    {"id": "9.1", "title": "初步识别的关键审计事项", "description": "列明识别为关键审计事项及其内容、识别为关键审计事项的判断依据、计划采取的应对措施", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "9.2", "title": "关键审计事项的沟通", "description": "列明沟通时间、沟通的关键审计事项、参与沟通的被审计单位人员、沟通函索引号", "target_word_count": 500, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "10", "title": "对被审计单位持续经营的考虑", "description": "若计划风险评估阶段未发现对被审计单位持续经营能力产生重大疑虑的事项或情况，应明确说明。如果通过了解被审计单位及内部控制、初步分析程序、计划审计工作发现了存在对被审计单位持续经营能力产生重大疑虑的事项或情况，则对照《中国注册会计师审计准则第1324号——持续经营》应用指南列举项目填写相关情形和计划的应对措施。",
                "target_word_count": 1000, "fillable_fields": [], "children": []
            },
            {
                "id": "11", "title": "对被审计单位适用法律法规的考虑", "description": "项目组应了解被审计单位适用的法律法规，记录拟执行的获取被审计单位遵守这些规定的充分适当审计证据的应对措施（如向管理层和治理层询问、检查与许可证颁发机构或监管机构的往来函件、访谈法律顾问等）。主要记录被审计单位违反或者疑似违反法律法规时可能对财务报表产生的重大影响。",
                "target_word_count": 1500, "fillable_fields": [], "children": [
                    {"id": "11.1", "title": "重大违法行为对财务报表整体层面重大错报风险的影响", "description": "分析管理层诚信和舞弊风险、企业整体层面内部控制的缺陷、持续经营的重大不确定性等方面是否适用，说明可能违法行为概述和计划应对措施", "target_word_count": 600, "fillable_fields": [], "children": []},
                    {"id": "11.2", "title": "违反法律法规对认定层次重大错报风险的影响", "description": "分析对经营范围的限定、环保相关法律法规、产品质量标准、网络安全法规、安全生产相关规定、税收相关法规、劳动法等法规关于就业平等和社保缴纳的规定、对监管指标的规定、反垄断法律法规、反洗钱法律法规等方面的影响及计划应对措施", "target_word_count": 600, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "12", "title": "重大会计实务、职业判断及应对措施", "description": "记录根据前述识别的重大错报风险相应涉及的会计审计问题，亦应记录在项目组计划会议上讨论的重大会计和审计问题及拟实施的应对措施。此处的重大会计审计问题应至少涵盖前述评估的财务报表层次重大错报风险的总体应对措施和认定层次的重大错报风险的应对程序。除舞弊相关的特别风险之外，还可能包括：连续审计情形下上期审计的遗留事项和重大分歧事项、IQCR结论待重大改进项目中的需改进事项、首次承接A类业务中质量控制委员会提示关注的事项、评估为高风险项目的重大事项、已收到审计关注函或媒体负面信息/举报事项、预审小结中提及或现场复核发现的重大事项。",
                "target_word_count": 2000, "fillable_fields": [], "children": []
            },
            {
                "id": "13", "title": "其他信息", "description": "本部分内容主要适用于年度审计且被审计单位发布年度报告的情形，常见于上市公司、新三板挂牌企业、金融机构等公众利益实体的财务报表审计项目。说明其他信息的范围及计划公告的时间，以及阅读其他信息的安排（时间计划、人员安排）。对于IPO申报和申请发行债券的财务报表审计项目，其他信息的相关要求一般不适用。",
                "target_word_count": 800, "fillable_fields": [], "children": []
            },
            {
                "id": "14", "title": "其他需要考虑的事项", "description": "其他需要在审计计划中考虑的事项，如集团注册会计师的指示等。如不存在，应明确说明。",
                "target_word_count": 600, "fillable_fields": [], "children": []
            },
            {
                "id": "15", "title": "对审计计划的更新和修改", "description": "对重大错报风险的评估结果和审计程序应对措施是随着审计工作的执行实时动态更新的。注册会计师应当记录对总体审计策略作出的重大更改及其理由，以及对导致此类更改的事项、条件或审计程序结果采取的应对措施。应作为修改审计计划的常见情形包括：对集团审计安排的重大调整、对重要性水平的重新确定、对信息系统测试/利用专家工作等安排的重大调整、关键审计事项数量和内容发生变化、因识别出新的重大舞弊迹象/重大前期会计差错或其他因素变化而导致实施审计程序的时间范围等发生重大变化、对审计工作进度安排进行重大调整、审计过程中收到的审计关注函或媒体负面信息/举报事项等。",
                "target_word_count": 1500, "fillable_fields": [], "children": [
                    {"id": "15.1", "title": "对SCOT+的完整性进行再评估", "description": "经再评估后是否识别出需要补充作为SCOT+的其他相关认定，如有则列明补充的SCOT+名称、相关认定、重大错报风险、拟实施的审计程序", "target_word_count": 500, "fillable_fields": [], "children": []},
                    {"id": "15.2", "title": "其他对审计计划的修改", "description": "如果未发生需要变更审计计划的情况，也仍然需要在此说明。列明修改轮次、修改时间、原计划或安排、更新和修改情况、更新和修改理由、更新和修改后的安排或实施的程序。", "target_word_count": 800, "fillable_fields": [], "children": []},
                ]
            },
        ]
    },
    "audit_summary": {
        "name": "重大事项概要汇总（审计小结）",
        "keywords": ["审计小结", "审计总结", "重大事项概要", "审计完成阶段", "审计发现汇总", "重大错报风险", "已审财务报表", "合伙人关注"],
        "min_keyword_matches": 2,
        "outline": [
            {
                "id": "1", "title": "审计业务约定范围及执行情况", "description": "明确审计业务约定范围、报告用途及执行情况",
                "target_word_count": 2000, "fillable_fields": ["客户名称", "审计期间"], "children": [
                    {"id": "1.1", "title": "业务约定范围及报告用途", "description": "根据与被审计单位签订的财务报表审计业务约定书内容，说明本次审计需出具的报告类型（如合并及公司财务报表审计报告、控股股东及其他关联方占用资金情况的专项说明、内控制度自我评估报告核实评价意见、资金风险状况专项报告等），以及上述报告的用途。需说明是否还包括其他子分公司的审计报告，是否根据证券交易所、证监局、国资委等监管部门有关规定出具其他报告。", "target_word_count": 1000, "fillable_fields": ["客户名称"], "children": []},
                    {"id": "1.2", "title": "按约定审计范围的执行情况", "description": "说明审计范围是否按约定书执行，审计范围是否扩大、是否受到限制。注意：最近一个会计年度经审计的利润总额、净利润或者扣除非经常性损益后的净利润孰低者为负值的公司，应当在年度报告中披露营业收入扣除情况及扣除后的营业收入金额。针对最近一个会计年度经审计营业收入低于3亿元（沪深主板）/1亿元（科创板创业板）但利润总额、净利润及扣除非经常性损益后的净利润均为正值的公司，会计师事务所应当对其非经常性损益披露的真实性、准确性、完整性出具专项核查意见。", "target_word_count": 800, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "2", "title": "独立性", "description": "根据职业道德守则和事务所有关规定，说明项目组成员在形式上、实质上是否均独立于审计客户，没有任何关联关系。签发审计报告的注册会计师在形式上、实质上完全独立于被审计单位，且没有任何关联关系。",
                "target_word_count": 1500, "fillable_fields": [], "children": [
                    {"id": "2.1", "title": "项目组成员独立性声明", "description": "项目组成员在形式上、实质上是否均独立于审计客户，没有任何关联关系的声明", "target_word_count": 500, "fillable_fields": [], "children": []},
                    {"id": "2.2", "title": "与治理层关于独立性的书面确认", "description": "被审计单位治理层（董事会或审计委员会）与注册会计师就年度审计进行的沟通记录中涉及独立性的书面确认", "target_word_count": 500, "fillable_fields": [], "children": []},
                    {"id": "2.3", "title": "审计过程中识别出的独立性威胁和利益冲突", "description": "如有独立性威胁和利益冲突，请说明就独立性威胁和利益冲突的咨询情况、所采取的防范措施及结论。如无，应明确说明不存在。", "target_word_count": 500, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "3", "title": "对审计计划的更新和修改", "description": "审计计划执行情况、重要性水平再评估及工时情况",
                "target_word_count": 2000, "fillable_fields": [], "children": [
                    {"id": "3.1", "title": "对审计计划的修改及理由", "description": "说明审计工作是否按总体审计策略进行，或者说明对审计计划的修改及理由。如在审计过程中取得的证据与初步评估获取的审计证据相矛盾，应及时修正风险评估结果，并相应修改应对措施。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "3.2", "title": "重要性水平的再评估", "description": "根据审定的财务数据，重新确定重要性水平和实际执行重要性水平。将此重要性水平与计划阶段确定的重要性水平进行分析，说明是否恰当、稳健，以及是否需要进行修改，并说明所增加的审计程序能够支持相关结论。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "3.3", "title": "项目完成工时情况", "description": "可按审计不同阶段或业务类别（指审计业务同时的其他业务），具体描述完成工时是否在计划范围内。如增加或减少工时达10%以上的，应说明工时变动的原因，以及该变动是否经项目合伙人批准。", "target_word_count": 600, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "4", "title": "需合伙人关注事项", "description": "审计过程中需要合伙人关注的重大事项，包括特别风险、错报、控制缺陷、重大职业判断等",
                "target_word_count": 4000, "fillable_fields": [], "children": [
                    {"id": "4.1", "title": "特别风险", "description": "识别出的特别风险，说明影响财务报表的领域、所采取的措施及结论、与管理层和治理层沟通的情况", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "4.2", "title": "已更正或未更正的错报", "description": "错报汇总、评价及与治理层的沟通", "target_word_count": 2000, "fillable_fields": [], "children": [
                        {"id": "4.2.1", "title": "已更正错报汇总及评价", "description": "按公司披露明细，调整金额进行统计，汇总已更正错报的明细及金额", "target_word_count": 600, "fillable_fields": [], "children": []},
                        {"id": "4.2.2", "title": "未更正错报汇总及评价", "description": "（1）按公司排列，未调整金额进行统计，与审计计划确定的重要性水平进行比较，说明在此阶段未调整金额小于重要性水平。运用重要性水平，除注重金额外，还应关注事项性质的影响。未调整事项不应包括金额不重大但性质重大的事项。（2）未更正错报应与治理层沟通中附件一和附件二中所列的未更正错报单独/汇总金额核对，不应超过实际执行的重要性水平，对财务报表整体的影响不重大。", "target_word_count": 600, "fillable_fields": [], "children": []},
                        {"id": "4.2.3", "title": "披露不足事项汇总", "description": "财务报表披露不足事项的汇总", "target_word_count": 400, "fillable_fields": [], "children": []},
                        {"id": "4.2.4", "title": "与管理层和治理层的沟通", "description": "完成阶段与管理层和治理层沟通的主要事项包括：注册会计师与财务报表审计相关的责任；审计中发现的重大问题（被审计单位会计实务重大方面的质量的看法、审计工作中遇到的重大困难、讨论或书面沟通审计中出现的重大事项、要求提供书面声明）；审计过程中识别出的值得关注的内部控制缺陷；审计过程中累计已识别错报（注册会计师还应要求管理层更正这些错报）；审计中出现的、根据职业判断认为对监督财务报告过程中的其他事项。", "target_word_count": 600, "fillable_fields": [], "children": []},
                    ]},
                    {"id": "4.3", "title": "值得关注的缺陷和其他控制缺陷", "description": "说明在审计过程中是否发现需对被审计单位舞弊风险以及内控方面的重大缺陷的评估做出改变，特别是与治理层沟通内控重大缺陷的情况下。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    {"id": "4.4", "title": "重大职业判断", "description": "审计过程中作出的重大职业判断事项，说明影响财务报表的领域、所采取的措施及结论、与管理层和治理层沟通的情况", "target_word_count": 600, "fillable_fields": [], "children": []},
                    {"id": "4.5", "title": "导致注册会计师难以实施必要审计程序的情形", "description": "说明影响审计工作进度或导致审计范围受限的原因、影响程度及与管理层、治理层沟通的情况。如果影响重大且经采用应对措施后仍未解决，应评估对审计意见类型的影响。", "target_word_count": 500, "fillable_fields": [], "children": []},
                    {"id": "4.6", "title": "可能导致出具非无保留意见审计报告的事项", "description": "说明事项性质和内容、错报或受限影响金额、对财务报表影响程度的判断、已执行的程序及获取的审计证据、与管理层和治理层沟通的情况", "target_word_count": 500, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "5", "title": "业务咨询记录及专业意见分歧解决情况", "description": "业务咨询及专业意见分歧的记录与解决。如果不存在业务咨询及分歧事项，应明确说明。",
                "target_word_count": 800, "fillable_fields": [], "children": []
            },
            {
                "id": "6", "title": "对重大错报风险的应对措施执行情况", "description": "财务报表层次和认定层次重大错报风险的应对措施执行情况，需项目组对照总体审计策略中识别的重大错报风险及应对措施，说明执行的情况及结果",
                "target_word_count": 4000, "fillable_fields": [], "children": [
                    {"id": "6.1", "title": "财务报表层次重大错报风险的总体应对措施", "description": "说明财务报表层次重大错报风险的总体应对措施执行情况，列表说明风险描述及对应的总体应对措施执行情况", "target_word_count": 1000, "fillable_fields": [], "children": []},
                    {"id": "6.2", "title": "认定层次的重大错报风险及应对措施", "description": "列举认定层次的重大错报风险及应对措施，需项目组对照总体审计策略中识别的重大错报风险及应对措施，说明执行的情况及结果", "target_word_count": 3000, "fillable_fields": [], "children": [
                        {"id": "6.2.1", "title": "长期股权投资及减值准备", "description": "（1）简要介绍财务报表截止日合并及母公司长期股权投资结构（与附注一致），各被投资单位经营情况、投资回报情况，以及本次审计考虑的减值准备计提情况。（2）说明报告期被审计单位收购和处置情况，按被审计单位进行描述，审计发现的重大问题（包括背景、被审计单位的会计处理）以及审计情况（包括审计证据、判断、结论），比如区分同一控制下或非同一控制下企业合并时，说明入账原则的判断、所采用公允价值是如何获取的以及合并报表的范围判断等。（3）对非同一控制下企业合并的商誉及商誉减值测试情况，详细描述商誉形成背景、会计处理依据、减值测试过程，包括折现率的选择，结论等。（4）可供出售金融资产、交易性金融资产的会计处理，以及审计程序、判断、结论。", "target_word_count": 800, "fillable_fields": [], "children": []},
                        {"id": "6.2.2", "title": "收入舞弊", "description": "（1）审计期间被审计单位收入、成本构成及变动原因分析；（2）被审计单位收入确认具体原则；（3）实施的主要审计程序执行情况；（4）审计结论。", "target_word_count": 800, "fillable_fields": [], "children": []},
                        {"id": "6.2.3", "title": "减值准备", "description": "（1）被审计单位本期减值准备变动情况，详细说明变动原因及计提依据；（2）相关会计政策及变更情况；（3）实施的审计程序、准则相关规定及审计执行情况；（4）判断计提充足性；（5）审计结论以及会计政策变更对报表的影响。", "target_word_count": 600, "fillable_fields": [], "children": []},
                        {"id": "6.2.4", "title": "对外担保、诉讼等或有事项", "description": "（1）被审计单位对外担保、诉讼具体情况，对财务报表的影响及潜在风险；（2）实施的审计程序；（3）判断或有事项对财务报表影响是否充分考虑；（4）审计结论及信息披露情况。", "target_word_count": 600, "fillable_fields": [], "children": []},
                        {"id": "6.2.5", "title": "购买资产", "description": "（1）报告期被审计单位资产购买的具体描述，包括背景、审批手续、合同条款、付款金额及时间、收购资产情况、对财务报表的影响等；（2）实施的审计程序；（3）判断财务处理的正确性；（4）审计结论及信息披露情况。", "target_word_count": 500, "fillable_fields": [], "children": []},
                    ]},
                    {"id": "6.3", "title": "延伸检查程序", "description": "被审计单位的财务报告用于资本运作或融资目的、首次承接的公众利益实体的审计业务、被审计单位处于高风险行业的、审计过程中已发现舞弊或疑似舞弊迹象的审计业务，还需说明执行延伸检查程序的情况。延伸检查程序包括但不限于：核查关联方资金流水、实地走访主要客户、利用企业信息查询工具检索未披露的关联关系、检查经销商的最终销售实现情况等。", "target_word_count": 800, "fillable_fields": [], "children": []},
                ]
            },
            {
                "id": "7", "title": "利用专家的工作", "description": "根据总体审计策略和具体审计过程中遇到的重大事项，说明利用内外部专家工作的情况。需征求事务所内部（质量控制部、专业技术委员会）和外部专家的专业意见的，应详细说明在对外部专家进行了解的前提下，与之签约情况、咨询事项、咨询结果以及项目组的判断评价。征求专家意见的内容包括但不限于：复杂金融工具估值、土地及建筑物评估、保险合同或员工福利计划精算、石油天然气储量估算、环境负债和场地清理费用估价、合同法律法规解释、复杂纳税问题分析、信息系统内部控制有效性等。",
                "target_word_count": 800, "fillable_fields": [], "children": []
            },
            {
                "id": "8", "title": "已审财务报表分析", "description": "已审财务报表的数据分析、同行业对比及财务与非财务信息印证。针对IPO审计，需补充分析申报期前两年财务报表，关注是否有收入和成本费用截止性差异。",
                "target_word_count": 4000, "fillable_fields": [], "children": [
                    {"id": "8.1", "title": "已审财务报表分析", "description": "报表项目分析及财务指标分析", "target_word_count": 2000, "fillable_fields": [], "children": [
                        {"id": "8.1.1", "title": "财务报表数据", "description": "报表项目分析：对于金额异常或年度间变动异常的报表项目（如两个期间的数据变动幅度达30%以上或超过执行重要性水平，或占公司报表日资产总额5%或报告期利润总额10%以上的）、非会计准则指定的报表项目、名称反映不出其性质或内容的报表项目，应当说明该项目的具体情况及变动原因。对于上述报表项目的变动情况，应结合风险评估和计划阶段评估出的重大错报风险、拟实施的审计程序，逐项说明已经实施的审计程序和审计结论。（注：和本小结第六项重复的，可以索引）", "target_word_count": 1200, "fillable_fields": [], "children": []},
                        {"id": "8.1.2", "title": "财务指标", "description": "对财务指标进行分析，包括：上市公司基本指标（每股收益、每股净资产、每股经营活动产生的现金流量净额）；盈利能力指标（净资产收益率、总资产净利润、销售净利率、销售毛利率、期间费用净利率）；营运能力指标（资产负债率、存货周转率、应收账款周转率）；偿债能力指标（流动比率、速动比率等）。", "target_word_count": 800, "fillable_fields": [], "children": []},
                    ]},
                    {"id": "8.2", "title": "同行业公司对比分析", "description": "列表并描述重要财务指标（如净资产收益率、毛利率、存货周转率、应收账款周转率、销售费用率、管理费用率等）与3-5家同行业可比公司的对比分析。若存在数据、趋势的不一致，分析原因及其合理性。", "target_word_count": 1000, "fillable_fields": [], "children": []},
                    {"id": "8.3", "title": "财务与非财务信息印证", "description": "财务数据与非财务信息的一致性分析", "target_word_count": 1200, "fillable_fields": [], "children": [
                        {"id": "8.3.1", "title": "整体经营情况与财务数据的一致性", "description": "结合公司整体经营情况，分析与营业收入、营业成本、管理费用、销售费用等财务数据的一致性", "target_word_count": 400, "fillable_fields": [], "children": []},
                        {"id": "8.3.2", "title": "财务与非财务信息的印证", "description": "分析已审报表与公司招股说明书、法律意见书中相关信息的一致性；其他非财务信息与财务信息的一致性，如公司的水、电、煤消耗量变动情况及一线生产员工人数的变动情况与产量的变动情况是否匹配。", "target_word_count": 400, "fillable_fields": [], "children": []},
                        {"id": "8.3.3", "title": "关注财务异常信息", "description": "分析公司会计政策、会计估计的一致性、与同行业的可比性；财务数据异常变动原因及合理性分析；财务指标与同行业其他公司对比分析；公司人工成本、固定资产和在建工程余额、变动的合理性分析。", "target_word_count": 400, "fillable_fields": [], "children": []},
                    ]},
                ]
            },
            {
                "id": "9", "title": "对关联方及关联方交易的结论", "description": "评价重大错报风险评估和应对过程中识别出的关联方关系及其交易的主要会计处理和披露，获取管理层和治理层对全部已知关联方名称、特征、关系及其交易，且其对交易进行恰当会计处理和披露的书面声明。",
                "target_word_count": 1000, "fillable_fields": [], "children": []
            },
            {
                "id": "10", "title": "基于持续经营假设的考虑", "description": "通过实施持续经营能力的审计程序后，对被审计单位生产经营能力、产品市场占有率、现金流量的分析、潜在风险等因素以及被审计单位董事会对未来的经营判断，总结得出对被审计单位的持续经营假设的结论。如得出的结论是否认被审计单位的持续经营假设或不能消除可能导致对持续经营能力产生重大疑虑的事项时，应考虑出具非无保留意见审计意见。",
                "target_word_count": 1000, "fillable_fields": [], "children": []
            },
            {
                "id": "11", "title": "对期后事项形成的结论", "description": "已获取充分、适当的审计证据，确定财务报表日至审计报告日之间发生的、需要在财务报表中调整或披露的事项已经按照适用的财务报告编制基础在财务报表中得到恰当反映。",
                "target_word_count": 800, "fillable_fields": [], "children": []
            },
            {
                "id": "12", "title": "拟在审计报告中沟通的关键审计事项", "description": "根据职业判断确定对本期财务报表审计最为重要的事项，从而构成关键审计事项。注意：前述第四章（一）至（五）中的需合伙人关注事项中，如果未作为关键审计事项，需说明判断理由。",
                "target_word_count": 1200, "fillable_fields": [], "children": []
            },
            {
                "id": "13", "title": "其他信息", "description": "年度报告中除财务报表和审计报告以外的其他信息审阅。其他信息是指在年度报告中包含的除财务报表和审计报告以外的财务信息和非财务信息。说明已获取并阅读了年度报告中的其他信息，分析其他信息与财务报表之间是否存在重大不一致，其他信息与审计中了解到的情况之间是否存在重大不一致。如发现重大不一致或对事实的重大错报，应说明具体情况。",
                "target_word_count": 800, "fillable_fields": [], "children": []
            },
            {
                "id": "14", "title": "财务报表审计结论", "description": "综合分析判断：（1）按照中国注册会计师审计准则的规定执行了审计工作，获取的审计证据是否充分、适当，为发表审计意见提供了基础；（2）被审计单位财务报表在所有重大方面是否按照企业会计准则的规定编制，是否公允反映了财务状况、经营成果和现金流量；（3）确定可以出具的审计意见类型。如出具非无保留意见审计报告，应说明具体意见。A、B类业务出具非无保留意见审计报告的，还应通过专业技术委员会审核，说明审核结论及进一步的措施。",
                "target_word_count": 1000, "fillable_fields": [], "children": []
            },
            {
                "id": "15", "title": "其他特殊考虑事项", "description": "内部控制审计、发债业务、新三板等特殊考虑事项（如不适用请删除相应部分）",
                "target_word_count": 3000, "fillable_fields": [], "children": [
                    {"id": "15.1", "title": "出具内部控制审计意见的考虑", "description": "内部控制缺陷汇总及拟发表的审计意见", "target_word_count": 1500, "fillable_fields": [], "children": [
                        {"id": "15.1.1", "title": "识别出的内部控制缺陷汇总", "description": "内部控制缺陷的识别与分类汇总", "target_word_count": 1000, "fillable_fields": [], "children": [
                            {"id": "15.1.1.1", "title": "财务报告内部控制缺陷汇总", "description": "财务报告相关内部控制缺陷的汇总，包括组成部分、相关业务流程/应用系统、缺陷描述及影响、缺陷类型（设计/运行）、所影响的账户交易披露及相关认定、补偿性控制、发生错报的可能性及严重程度分析、缺陷认定结论", "target_word_count": 400, "fillable_fields": [], "children": []},
                            {"id": "15.1.1.2", "title": "非财务报告内部控制重大缺陷", "description": "非财务报告相关内部控制重大缺陷，包括组成部分、相关业务流程/应用系统、缺陷描述及影响（说明影响的方面如经营效率或合规性等）、缺陷类型（设计/运行）、补偿性控制、缺陷认定结论（说明判断为重大缺陷的理由）", "target_word_count": 300, "fillable_fields": [], "children": []},
                            {"id": "15.1.1.3", "title": "内部控制缺陷在期后的整改情况", "description": "已识别内部控制缺陷的期后整改情况", "target_word_count": 300, "fillable_fields": [], "children": []},
                        ]},
                        {"id": "15.1.2", "title": "拟发表的内部控制审计意见类型", "description": "已评价对控制的测试结果、财务报表审计中发现的错报以及已识别的所有控制缺陷。在评价审计证据时，查阅了本年度涉及内部控制的内部审计报告或类似报告，并评价了这些报告中指出的控制缺陷。已取得经企业签署的书面声明，已考虑期后事项的影响，已评价企业内部控制评价报告对相关法律法规规定的要素列报的完整性和恰当性。综合判断可以出具的内部控制审计意见类型。如出具非标准无保留意见内部控制审计报告，应说明具体情况，并按照事务所的质量控制制度规定提交专业技术委员会审核。", "target_word_count": 500, "fillable_fields": [], "children": []},
                    ]},
                    {"id": "15.2", "title": "发债业务的特殊考虑", "description": "发债业务中的非经营性资产、偿债能力及担保情况", "target_word_count": 1200, "fillable_fields": [], "children": [
                        {"id": "15.2.1", "title": "非经营性资产", "description": "描述被审计单位控制或受托管理的非经营性资产情况，包括政府办公场所、公园、医院、学校、事业单位资产以及不产生收益的市政道路、桥梁、博物馆等纯公益性资产。说明对非经营性资产列报和披露是否符合企业会计准则的规定，以及项目组所执行的主要审计程序。", "target_word_count": 400, "fillable_fields": [], "children": []},
                        {"id": "15.2.2", "title": "偿债能力分析", "description": "根据审定财务报表数据，分析被审计单位自身偿债能力及偿债保障措施。发行人累计债券余额（含本期）应小于最近一年全口径所有者权益（包含少数股东权益）的40%。发行人最近3年平均净利润应能覆盖本期债券1年的利息。对于资产负债率超过65%的项目，需要对其负债率进行专项分析，说明其有息资产负债率等。对于资产负债率在80%至90%之间的发债申请企业，必须要求提供担保。资产负债率超过90%，不予核准发行债券。", "target_word_count": 400, "fillable_fields": [], "children": []},
                        {"id": "15.2.3", "title": "担保情况", "description": "描述被审计单位债券担保的有效性，抵押担保是否存在一物多押，抵质押资产是否是易变现有效资产，第三方担保是否存在互保或连环保。说明对担保事项列报、披露完整性执行的审计程序。", "target_word_count": 400, "fillable_fields": [], "children": []},
                    ]},
                    {"id": "15.3", "title": "新三板审计业务特殊核查事项", "description": "新三板挂牌审计的特殊核查要求", "target_word_count": 800, "fillable_fields": [], "children": [
                        {"id": "15.3.1", "title": "是否存在会计监管6号提及的情形", "description": "核查被审计单位是否存在会计监管提示第6号提及的情形，包括：企业类型（融资需求、分层调整动机、首次公开发行股票、有对赌协议）、业务类型（首次承接的新三板已挂牌公司的首份业务报告、首次申请新三板挂牌的业务报告）、风险情形（创新层挂牌公司审计、挂牌公司成立时间短/处于发展或成长期、存在特殊业务模式、选择和运用复杂或异常的会计政策、重要循环存在重大前期差错、持续经营存在重大不确定性等）", "target_word_count": 300, "fillable_fields": [], "children": []},
                        {"id": "15.3.2", "title": "会计监管提示6号及9号九方面问题核查", "description": "会计监管提示6号及9号涉及的九方面问题核查，包括：审计项目质量控制（承接评价与业务分类、前后任沟通、项目质量控制复核）、风险评估（五个方面及管理层凌驾内控之上的风险）、持续经营、收入确认（收入舞弊、收入与财务数据逻辑关系、同行业比较）、关联方认定及交易、货币资金（分析程序、函证、银行流水、原始凭证等）、费用确认和计量（研发支出资本化、异常大额费用）、内部控制有效性、财务报表披露", "target_word_count": 300, "fillable_fields": [], "children": []},
                        {"id": "15.3.3", "title": "新三板挂牌审计一般问题核查", "description": "新三板挂牌审计的一般性问题核查，包括：合法合规（规模出资瑕疵的会计处理）、财务与业务匹配性（收入、成本、毛利率、期间费用、应收账款、存货、现金流量表）、财务规范性（内控制度有效性及会计核算基础规范性、税收缴纳）、财务指标与会计政策估计、关联交易（关联方、关联交易类型、必要性与公允性）", "target_word_count": 200, "fillable_fields": [], "children": []},
                    ]},
                ]
            },
            {
                "id": "16", "title": "提请下年度审计关注事项", "description": "需要下年度审计重点关注的事项，涵盖监管政策变化、本年度重大事项延续、内部控制变化、职业判断提示、项目组构成、期后事项及监管检查等方面",
                "target_word_count": 2000, "fillable_fields": [], "children": [
                    {"id": "16.1", "title": "监管政策、市场变化对下年度的影响", "description": "分析监管政策和市场环境变化对下年度审计的影响，包括新出台的法规、行业监管要求变化等", "target_word_count": 300, "fillable_fields": [], "children": []},
                    {"id": "16.2", "title": "本年度重大事项在下年度的延续", "description": "本年度重大事项在下年度的延续影响，如未决诉讼、重大合同执行、资产减值后续等", "target_word_count": 300, "fillable_fields": [], "children": []},
                    {"id": "16.3", "title": "本年度内部控制的重大变化在下年度的执行情况", "description": "内部控制重大变化在下年度的执行跟踪，关注新制度的落实效果", "target_word_count": 300, "fillable_fields": [], "children": []},
                    {"id": "16.4", "title": "对重大职业判断和特别风险的提示", "description": "需持续关注的重大职业判断和特别风险，提醒下年度审计团队重点关注", "target_word_count": 300, "fillable_fields": [], "children": []},
                    {"id": "16.5", "title": "特殊行业项目组的构成提示", "description": "人员结构、知识层次、人员数量、工时等方面的提示，确保下年度项目组具备必要的专业能力", "target_word_count": 200, "fillable_fields": [], "children": []},
                    {"id": "16.6", "title": "期后事项在下年度的执行情况", "description": "期后事项在下年度的跟踪执行，关注期后事项的最终解决情况", "target_word_count": 200, "fillable_fields": [], "children": []},
                    {"id": "16.7", "title": "监管部门检查对下年度的影响", "description": "监管部门检查结果对下年度审计的影响，包括检查发现的问题及整改要求", "target_word_count": 200, "fillable_fields": [], "children": []},
                ]
            },
        ]
    },
}


def _match_preset_outline(template_type: str, template_text: str) -> Optional[List[Dict[str, Any]]]:
    """尝试匹配预置大纲模板。

    先按 template_type 精确匹配，再用关键词从文本中模糊匹配。
    返回匹配到的大纲（深拷贝），或 None。
    """
    import copy

    # 1) 按模板类型精确匹配
    if template_type in _PRESET_OUTLINES:
        logger.info(f"[预置大纲] 按模板类型 '{template_type}' 精确匹配到预置大纲")
        return copy.deepcopy(_PRESET_OUTLINES[template_type]["outline"])

    # 2) 用关键词从模板文本中模糊匹配
    if template_text:
        text_lower = template_text[:5000]  # 只检查前5000字
        for key, preset in _PRESET_OUTLINES.items():
            matches = sum(1 for kw in preset["keywords"] if kw in text_lower)
            if matches >= preset.get("min_keyword_matches", 2):
                logger.info(
                    f"[预置大纲] 关键词匹配到预置大纲 '{preset['name']}'"
                    f"（匹配 {matches}/{len(preset['keywords'])} 个关键词）"
                )
                return copy.deepcopy(preset["outline"])

    return None


def _enrich_outline_with_preset(outline: List[Dict[str, Any]], template_type: str, template_text: str) -> bool:
    """尝试用预置大纲的 description 丰富已提取的大纲。

    当结构化标题提取成功但 description 为空时，通过多策略标题匹配
    将预置大纲中的 description、fillable_fields、target_word_count 合并进去。

    匹配策略（按优先级）：
    1. 精确匹配：normalized 标题完全相同
    2. 子串匹配：一方标题包含另一方
    3. 关键词重叠：提取中文关键词计算 Jaccard 相似度 ≥ 0.4
    4. 位置匹配：同层级、同位置的章节（仅用于顶层章节，且数量接近时）

    返回 True 表示成功匹配并丰富，False 表示未匹配到预置大纲。
    """
    import copy
    import re

    # 先找到匹配的预置大纲
    preset_outline = None
    if template_type in _PRESET_OUTLINES:
        preset_outline = _PRESET_OUTLINES[template_type]["outline"]
    elif template_text:
        text_lower = template_text[:5000]
        for key, preset in _PRESET_OUTLINES.items():
            matches = sum(1 for kw in preset["keywords"] if kw in text_lower)
            if matches >= preset.get("min_keyword_matches", 2):
                preset_outline = preset["outline"]
                break

    if not preset_outline:
        return False

    def _normalize(title: str) -> str:
        """去除序号、空格、标点，只保留核心文字用于匹配。"""
        t = re.sub(r'^[\d.]+\s*', '', title)
        t = re.sub(r'^[（(][一二三四五六七八九十百千]+[）)]\s*', '', t)
        t = re.sub(r'^[一二三四五六七八九十百千]+[、．.]\s*', '', t)
        t = re.sub(r'[\s　，。、：；（）()\-—]+', '', t)
        return t

    def _extract_keywords(text: str) -> set:
        """提取中文关键词（2-4字的连续中文片段）用于相似度计算。"""
        # 先 normalize
        t = _normalize(text)
        # 提取所有2字及以上的中文子串作为关键词
        keywords = set()
        for length in (4, 3, 2):
            for i in range(len(t) - length + 1):
                seg = t[i:i+length]
                if re.match(r'^[\u4e00-\u9fff]+$', seg):
                    keywords.add(seg)
        return keywords

    def _similarity(title_a: str, title_b: str) -> float:
        """计算两个标题的相似度（0~1），综合子串匹配和关键词 Jaccard。"""
        na, nb = _normalize(title_a), _normalize(title_b)
        if not na or not nb:
            return 0.0
        # 精确匹配
        if na == nb:
            return 1.0
        # 子串匹配（短的包含在长的里面）
        shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
        if shorter in longer:
            return 0.85 + 0.1 * (len(shorter) / len(longer))
        # 关键词 Jaccard
        ka, kb = _extract_keywords(title_a), _extract_keywords(title_b)
        if not ka or not kb:
            return 0.0
        intersection = ka & kb
        union = ka | kb
        return len(intersection) / len(union) if union else 0.0

    def _flatten_preset(items: List[Dict], depth: int = 0) -> List[tuple]:
        """递归展平预置大纲，返回 (normalized_title, preset_item, depth) 列表。"""
        result = []
        for item in items:
            key = _normalize(item.get("title", ""))
            result.append((key, item, depth))
            children = item.get("children", [])
            if children:
                result.extend(_flatten_preset(children, depth + 1))
        return result

    def _merge_preset_into_item(item: Dict, preset_item: Dict):
        """将预置信息合并到大纲项中。"""
        if not item.get("description") or len(item.get("description", "")) < 10:
            item["description"] = preset_item.get("description", "")
        if not item.get("fillable_fields") and preset_item.get("fillable_fields"):
            item["fillable_fields"] = copy.deepcopy(preset_item["fillable_fields"])
        if preset_item.get("target_word_count", 0) > item.get("target_word_count", 0):
            item["target_word_count"] = preset_item["target_word_count"]

    # 展平预置大纲用于模糊匹配
    flat_preset = _flatten_preset(preset_outline)
    # 跟踪已被匹配的预置项，避免重复匹配
    used_preset_indices = set()

    def _find_best_preset(title: str, depth: int) -> Optional[Dict]:
        """为给定标题找到最佳匹配的预置项。"""
        best_score = 0.0
        best_idx = -1
        for idx, (p_key, p_item, p_depth) in enumerate(flat_preset):
            if idx in used_preset_indices:
                continue
            # 同层级优先（但不强制）
            depth_penalty = 0.0 if p_depth == depth else 0.1
            score = _similarity(title, p_item.get("title", "")) - depth_penalty
            if score > best_score:
                best_score = score
                best_idx = idx
        # 阈值：至少 0.4 的相似度才算匹配
        if best_score >= 0.4 and best_idx >= 0:
            used_preset_indices.add(best_idx)
            return flat_preset[best_idx][1]
        return None

    def _apply_preset_fuzzy(items: List[Dict], depth: int = 0) -> int:
        """递归地用模糊匹配将预置 description 合并到大纲中。"""
        matched = 0
        for item in items:
            title = item.get("title", "")
            preset_item = _find_best_preset(title, depth)
            if preset_item:
                _merge_preset_into_item(item, preset_item)
                matched += 1
                logger.debug(f"[预置大纲丰富] 匹配: '{title}' ← '{preset_item.get('title', '')}'")
            children = item.get("children", [])
            if children:
                matched += _apply_preset_fuzzy(children, depth + 1)
        return matched

    # 策略1+2+3: 模糊匹配（包含精确、子串、关键词Jaccard）
    matched = _apply_preset_fuzzy(outline)

    # 策略4: 位置匹配兜底 — 仅对顶层未匹配的章节，按位置对应
    if matched < len(outline) and len(preset_outline) > 0:
        # 顶层章节数量接近时（差距不超过30%），用位置匹配补充
        ratio = min(len(outline), len(preset_outline)) / max(len(outline), len(preset_outline))
        if ratio >= 0.7:
            for i, item in enumerate(outline):
                if item.get("description") and len(item.get("description", "")) >= 10:
                    continue  # 已有 description，跳过
                if i < len(preset_outline):
                    p_item = preset_outline[i]
                    # 确认这个预置项还没被用过（通过检查 title 是否在 used 中）
                    p_key = _normalize(p_item.get("title", ""))
                    already_used = any(
                        flat_preset[idx][0] == p_key for idx in used_preset_indices
                    )
                    if not already_used:
                        _merge_preset_into_item(item, p_item)
                        matched += 1
                        logger.debug(
                            f"[预置大纲丰富-位置] 位置匹配: '{item.get('title', '')}' ← '{p_item.get('title', '')}'"
                        )

    if matched > 0:
        logger.info(f"[预置大纲丰富] 成功匹配并丰富了 {matched} 个章节的 description")
        return True
    return False


class DocumentGenerator:
    """基于模板的审计文档生成服务。"""

    def __init__(self):
        self.template_manager = TemplateManager()

    @property
    def openai_service(self) -> OpenAIService:
        """每次访问时创建新实例，确保使用最新的 LLM 配置（热更新）。"""
        return OpenAIService()

    # ── 大纲提取 ──

    async def _get_template_text(self, template_id: str, template) -> str:
        """获取模板的纯文本内容（用于关键词匹配）。"""
        file_path = self.template_manager.get_template_file_path(template_id)
        if not file_path:
            return ""
        try:
            from .workpaper_parser import WorkpaperParser
            parser = WorkpaperParser()
            parse_result = await parser.parse_file(file_path, template.name + "." + template.file_format)
            return parse_result.content_text
        except Exception:
            return ""

    async def extract_template_outline(
        self,
        template_id: str,
        force_llm: bool = False,
    ) -> List[Dict[str, Any]]:
        """从用户上传的模板文件中提取章节结构，生成树形大纲。

        优先使用模板文件中的标题样式（Heading 1/2/3）直接构建树形大纲，
        无需调用 LLM，速度快且结构准确。
        仅当模板没有标题样式或 force_llm=True 时才调用 LLM 识别。
        """
        import time
        start_time = time.time()
        
        template = self.template_manager.get_template(template_id)
        if not template:
            raise ValueError(f"模板不存在：{template_id}")

        # 用于预置大纲 description 丰富的参数
        _tpl_type = template.template_type.value if hasattr(template.template_type, 'value') else str(template.template_type)

        # 优先使用模板上传时已解析的结构化标题信息
        if not force_llm and template.structure and template.structure.sections:
            sections = template.structure.sections
            # 检查是否有有效的标题层级
            has_levels = any(s.level >= 1 for s in sections)
            if has_levels and len(sections) >= 2:
                elapsed = time.time() - start_time
                logger.info(
                    f"[大纲提取] 模板 '{template.name}' 使用结构化标题构建大纲"
                    f"（{len(sections)} 个章节），耗时: {elapsed:.3f}秒"
                )
                result = self._build_outline_from_sections(sections)
                # 尝试用预置大纲丰富 description（先按类型匹配，不行再加载文本做关键词匹配）
                if not _enrich_outline_with_preset(result, _tpl_type, ""):
                    _tpl_text = await self._get_template_text(template_id, template)
                    if _tpl_text:
                        _enrich_outline_with_preset(result, "", _tpl_text)
                return result
            else:
                logger.info(
                    f"[大纲提取] 模板 '{template.name}' 结构化标题不满足条件: "
                    f"has_levels={has_levels}, sections_count={len(sections)}"
                )
        else:
            has_structure = template.structure is not None
            has_sections = has_structure and template.structure.sections is not None and len(template.structure.sections) > 0
            logger.info(
                f"[大纲提取] 模板 '{template.name}' 无法使用快速路径: "
                f"force_llm={force_llm}, has_structure={has_structure}, has_sections={has_sections}"
            )

        # 回退：尝试重新解析模板文件，用文本模式检测标题
        if not force_llm:
            file_path = self.template_manager.get_template_file_path(template_id)
            if file_path:
                try:
                    structure = await self.template_manager.parse_template_structure(file_path)
                    if structure and structure.sections and len(structure.sections) >= 2:
                        has_levels = any(s.level >= 1 for s in structure.sections)
                        if has_levels:
                            elapsed = time.time() - start_time
                            logger.info(
                                f"[大纲提取] 模板 '{template.name}' 重新解析后使用结构化标题构建大纲"
                                f"（{len(structure.sections)} 个章节），耗时: {elapsed:.3f}秒"
                            )
                            result = self._build_outline_from_sections(structure.sections)
                            if not _enrich_outline_with_preset(result, _tpl_type, ""):
                                _tpl_text = await self._get_template_text(template_id, template)
                                if _tpl_text:
                                    _enrich_outline_with_preset(result, "", _tpl_text)
                            return result
                except Exception as e:
                    logger.warning(f"[大纲提取] 重新解析模板失败: {e}")

        # 回退：尝试匹配预置大纲模板（按模板类型或关键词）
        if not force_llm:
            # 获取模板文本用于关键词匹配
            preset_text = ""
            file_path = self.template_manager.get_template_file_path(template_id)
            if file_path:
                try:
                    from .workpaper_parser import WorkpaperParser
                    parser = WorkpaperParser()
                    parse_result = await parser.parse_file(file_path, template.name + "." + template.file_format)
                    preset_text = parse_result.content_text
                except Exception:
                    pass

            preset_outline = _match_preset_outline(
                template.template_type.value if hasattr(template.template_type, 'value') else str(template.template_type),
                preset_text,
            )
            if preset_outline:
                elapsed = time.time() - start_time
                logger.info(
                    f"[大纲提取] 模板 '{template.name}' 使用预置大纲模板，耗时: {elapsed:.3f}秒"
                )
                return preset_outline

        # 回退到 LLM 识别
        logger.info(f"[大纲提取] 模板 '{template.name}' 使用 LLM 识别大纲结构")

        file_path = self.template_manager.get_template_file_path(template_id)
        if not file_path:
            raise ValueError(f"模板文件不存在：{template_id}")

        from .workpaper_parser import WorkpaperParser

        parser = WorkpaperParser()
        parse_result = await parser.parse_file(file_path, template.name + "." + template.file_format)
        template_text = parse_result.content_text

        if not template_text.strip():
            raise ValueError("模板文件内容为空，无法提取大纲")

        # 如果解析结果中有标题信息，附加到提示中帮助 LLM 理解结构
        heading_hint = ""
        if parse_result.structured_data:
            headings = parse_result.structured_data.get("headings", [])
            if headings:
                heading_lines = [
                    f"{'  ' * (h.get('level', 1) - 1)}[Heading {h.get('level', 1)}] {h.get('text', '')}"
                    for h in headings
                ]
                heading_hint = (
                    "\n\n【重要提示】以下是从文档样式中提取的标题层级信息，"
                    "请严格按照这些标题及其层级关系构建大纲：\n"
                    + "\n".join(heading_lines)
                )

        # 截断过长的模板文本
        context_limit = _get_context_limit(self.openai_service.model_name)
        max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
        prompt_overhead = estimate_token_count(_OUTLINE_EXTRACTION_PROMPT) + estimate_token_count(heading_hint) + 500
        max_template_tokens = max(max_input_tokens - prompt_overhead, 2000)
        template_text = truncate_to_token_limit(template_text, max_template_tokens)

        messages = [
            {"role": "system", "content": _OUTLINE_EXTRACTION_PROMPT},
            {"role": "user", "content": f"请分析以下审计模板文本，识别章节结构并返回JSON大纲：\n\n{template_text}{heading_hint}"},
        ]

        full_content = ""
        async for chunk in self.openai_service.stream_chat_completion(
            messages, temperature=0.3
        ):
            full_content += chunk

        outline = self._parse_outline_json(full_content)
        
        # 统一使用层级数字编号
        DocumentGenerator._reindex_outline_smart(outline)
        
        # 尝试用预置大纲丰富 description
        _enrich_outline_with_preset(outline, _tpl_type, template_text)
        
        elapsed = time.time() - start_time
        logger.info(f"[大纲提取] LLM识别完成，耗时: {elapsed:.3f}秒")
        
        return outline

    @staticmethod
    def _build_outline_from_sections(
        sections: list,
    ) -> List[Dict[str, Any]]:
        """从模板的结构化章节列表构建树形大纲（不依赖 LLM）。

        将扁平的 TemplateSection 列表（带 level）转换为嵌套的树形结构。
        使用栈算法，时间复杂度 O(n)，性能优化。

        序号处理：如果原标题中已包含中文序号（如"十二、""（一）""1."），
        则提取为 id 并从 title 中去除，保留原模板的序号风格。
        """
        if not sections:
            return []
        
        import time
        start_time = time.time()
        
        root: List[Dict[str, Any]] = []
        # 栈：(level, children_list) — 用于追踪当前层级的父节点
        stack: List[tuple] = [(0, root)]

        for section in sections:
            level = section.level if hasattr(section, 'level') else 1
            title = section.title if hasattr(section, 'title') else str(section)
            fillable = section.fillable_fields if hasattr(section, 'fillable_fields') else []

            # 弹出栈中层级 >= 当前层级的项（保持栈的层级递增性）
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()

            # 从标题中提取原始序号
            original_id, clean_title = DocumentGenerator._extract_original_id(title)

            # 根据层级估算目标字数
            if level == 1:
                target_words = 1500
            elif level == 2:
                target_words = 800
            else:
                target_words = 500

            item: Dict[str, Any] = {
                "id": original_id,  # 优先使用原始序号，空串则后续补编号
                "title": clean_title,
                "description": "",
                "target_word_count": target_words,
                "fillable_fields": fillable if fillable else [],
                "children": [],
            }

            # 添加到当前父节点的 children
            stack[-1][1].append(item)

            # 将当前节点压入栈，作为后续子节点的父节点
            stack.append((level, item["children"]))

        # 统一使用层级数字编号
        DocumentGenerator._reindex_outline_smart(root)
        
        elapsed = time.time() - start_time
        logger.info(
            f"[大纲构建] 从 {len(sections)} 个章节构建树形大纲，"
            f"根节点数: {len(root)}，耗时: {elapsed:.3f}秒"
        )
        
        return root

    @staticmethod
    def _extract_original_id(title: str) -> tuple:
        """从标题文本中提取原始序号和去除序号后的标题。

        支持的序号格式：
        - 中文数字：一、 二、 十二、
        - 中文括号：（一） (一) （二）
        - 阿拉伯数字：1. 1、 12.
        - 阿拉伯括号：(1) （1）
        - 章节格式：第一章 第二部分 第三节

        Returns:
            (original_id, clean_title)
            如果没有识别到序号，original_id 为空串。
        """
        title = title.strip()
        if not title:
            return ("", title)

        # 按优先级匹配各种序号模式
        patterns = [
            # 第X章/部分/节/篇
            (r'^(第[一二三四五六七八九十百零\d]+[章部分节篇])\s*', None),
            # 中文数字 + 顿号/点号：一、 二、 十二、
            (r'^([一二三四五六七八九十百零]+)[、.．]\s*', None),
            # 中文括号数字：（一） (一)
            (r'^[（(]([一二三四五六七八九十百零]+)[）)]\s*', lambda m: f'（{m.group(1)}）'),
            # 阿拉伯数字 + 点号/顿号：1. 1、 12.
            (r'^(\d+)[、.．]\s*', lambda m: f'{m.group(1)}.'),
            # 阿拉伯括号数字：(1) （1）
            (r'^[（(](\d+)[）)]\s*', lambda m: f'（{m.group(1)}）'),
        ]

        for pattern, id_formatter in patterns:
            m = re.match(pattern, title)
            if m:
                if id_formatter:
                    original_id = id_formatter(m)
                else:
                    original_id = m.group(0).strip()
                clean_title = title[m.end():].strip()
                # 如果去掉序号后标题为空，保留原标题
                if not clean_title:
                    return (original_id, title)
                return (original_id, clean_title)

        return ("", title)

    @staticmethod
    def _reindex_outline_smart(
        items: List[Dict[str, Any]], prefix: str = ""
    ) -> None:
        """智能编号：统一使用层级数字编号（1, 1.1, 1.1.1）。

        原始序号（中文序号等）已保存在 title 提取阶段，
        这里统一用阿拉伯数字层级编号，确保前端显示和后端引用一致。
        """
        for idx, item in enumerate(items, 1):
            item["id"] = f"{prefix}{idx}" if not prefix else f"{prefix}.{idx}"

            # 递归处理子节点
            if item.get("children"):
                DocumentGenerator._reindex_outline_smart(
                    item["children"], item["id"]
                )

    @staticmethod
    def _reindex_outline(
        items: List[Dict[str, Any]], prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """递归重新编号大纲项的 ID。"""
        for idx, item in enumerate(items, 1):
            item["id"] = f"{prefix}{idx}" if not prefix else f"{prefix}.{idx}"
            if item.get("children"):
                DocumentGenerator._reindex_outline(item["children"], item["id"])
        return items

    def _parse_outline_json(self, content: str) -> List[Dict[str, Any]]:
        """从LLM响应中解析大纲JSON。"""
        # 尝试直接解析
        content = content.strip()

        # 移除可能的markdown代码块标记
        if content.startswith("```"):
            lines = content.split("\n")
            # 去掉首尾的 ``` 行
            start = 1
            end = len(lines)
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip().startswith("```"):
                    end = i
                    break
            content = "\n".join(lines[start:end]).strip()

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "outline" in result:
                return result["outline"]
            return [result]
        except json.JSONDecodeError:
            # 尝试提取JSON数组
            import re
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

            logger.error("无法解析LLM返回的大纲JSON: %s", content[:500])
            raise ValueError("无法解析模板大纲结构，请重试")

    # ── 文档流式生成 ──

    async def generate_document_stream(
        self,
        template_id: str,
        outline: List[Dict[str, Any]],
        knowledge_library_ids: List[str],
        project_info: ProjectInfo,
    ) -> AsyncGenerator[str, None]:
        """逐章节流式生成审计文档内容。

        遍历大纲中的叶子章节，逐个调用 _generate_section_content()，
        每个章节生成时注入 parent 和 sibling 上下文。

        Yields:
            JSON-encoded SSE event strings.
        """
        yield json.dumps(
            {"status": "started", "message": "开始生成审计文档..."},
            ensure_ascii=False,
        )

        # 加载知识库内容（使用智能检索器，全量缓存不截断）
        yield json.dumps(
            {"status": "loading_knowledge", "message": "正在读取知识库..."},
            ensure_ascii=False,
        )

        knowledge_loaded = False
        if knowledge_library_ids:
            try:
                # 使用 knowledge_retriever 预加载全量知识库
                for evt in knowledge_retriever.preload(
                    knowledge_service,
                    library_ids=knowledge_library_ids,
                ):
                    yield json.dumps(
                        {"status": "loading_knowledge", "message": evt.get('message', '读取中...')},
                        ensure_ascii=False,
                    )
                knowledge_loaded = knowledge_retriever.is_loaded
                logger.info(f"[文档生成] 知识库预加载完成: {knowledge_retriever.stats}")
            except Exception as e:
                logger.warning("知识库读取失败: %s", e)

        # 收集所有叶子章节（扁平化）
        leaf_sections = []
        self._collect_leaf_sections(outline, leaf_sections, parent_path=[])

        # 逐章节生成
        generated_sections: List[GeneratedSection] = []
        for idx, leaf in enumerate(leaf_sections):
            section_info = leaf["section"]
            section_title = section_info.get("title", f"章节{idx + 1}")

            yield json.dumps(
                {"status": "section_start", "section": section_title, "index": idx},
                ensure_ascii=False,
            )

            # 构建上下文
            parent_sections = leaf.get("parents")
            sibling_sections = leaf.get("siblings")
            target_word_count = section_info.get("target_word_count", 1500)

            # 按章节内容智能检索相关知识库片段
            knowledge_context = ""
            if knowledge_loaded:
                knowledge_context = knowledge_retriever.get_formatted_for_chapter(
                    chapter_title=section_title,
                    chapter_description=section_info.get('description', ''),
                    max_tokens=8000,
                )

            # 流式生成单章节内容
            section_content = ""
            async for chunk in self._generate_section_content(
                section=section_info,
                parent_sections=parent_sections,
                sibling_sections=sibling_sections,
                project_info=project_info,
                knowledge_context=knowledge_context,
                target_word_count=target_word_count,
            ):
                section_content += chunk
                yield json.dumps(
                    {"status": "streaming", "content": chunk, "section_index": idx},
                    ensure_ascii=False,
                )

            is_placeholder = "【待补充】" in section_content

            generated_section = GeneratedSection(
                index=idx,
                title=section_title,
                content=section_content,
                is_placeholder=is_placeholder,
            )
            generated_sections.append(generated_section)

            yield json.dumps(
                {
                    "status": "section_complete",
                    "section": section_title,
                    "content": section_content,
                },
                ensure_ascii=False,
            )

        # 构建完整文档
        outline_items = self._dicts_to_outline_items(outline)
        document = GeneratedDocument(
            id=str(uuid.uuid4()),
            template_id=template_id,
            outline=outline_items,
            sections=generated_sections,
            project_info=project_info,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        yield json.dumps(
            {"status": "completed", "document": document.model_dump(mode="json")},
            ensure_ascii=False,
        )

    def _collect_leaf_sections(
        self,
        sections: List[Dict[str, Any]],
        result: List[Dict[str, Any]],
        parent_path: List[Dict[str, Any]],
    ) -> None:
        """递归收集叶子章节，附带 parent 和 sibling 上下文。"""
        for section in sections:
            children = section.get("children") or []
            if not children:
                # 叶子节点
                result.append({
                    "section": section,
                    "parents": parent_path[:] if parent_path else None,
                    "siblings": [
                        s for s in sections if s.get("id") != section.get("id")
                    ] or None,
                })
            else:
                # 递归处理子节点
                new_parent = parent_path + [{
                    "id": section.get("id", ""),
                    "title": section.get("title", ""),
                    "description": section.get("description", ""),
                }]
                self._collect_leaf_sections(children, result, new_parent)

    # ── 单章节内容生成 ──

    async def _generate_section_content(
        self,
        section: Dict[str, Any],
        parent_sections: Optional[List[Dict[str, Any]]],
        sibling_sections: Optional[List[Dict[str, Any]]],
        project_info: ProjectInfo,
        knowledge_context: str,
        target_word_count: int,
        previously_generated: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """生成单个章节内容。

        注入 parent/sibling 上下文、知识库内容和项目信息，
        通过 stream_chat_completion() 流式输出。
        """
        section_title = section.get("title", "未命名章节")
        section_id = section.get("id", "")
        section_desc = section.get("description", "")
        fillable_fields = section.get("fillable_fields", [])

        # 构建上下文信息
        context_parts = []

        # 上级章节信息
        if parent_sections:
            context_parts.append("上级章节信息：")
            for parent in parent_sections:
                context_parts.append(
                    f"- {parent.get('id', '')} {parent.get('title', '')}: "
                    f"{parent.get('description', '')}"
                )

        # 同级章节信息
        if sibling_sections:
            context_parts.append("同级章节信息（请避免内容重复）：")
            for sibling in sibling_sections:
                if sibling.get("id") != section_id:
                    context_parts.append(
                        f"- {sibling.get('id', '')} {sibling.get('title', '')}: "
                        f"{sibling.get('description', '')}"
                    )

        # 前面已生成章节的上下文（避免重复 + 简称衔接）
        if previously_generated:
            # 1) 提取所有已定义的简称/术语
            import re
            abbreviations = []
            seen_abbrs = set()

            # 匹配模式：XX（以下简称"A"或"B"）或 XX（以下简称"A"）
            # 支持各种引号：""、""、「」、''
            block_pattern = re.compile(
                r'([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z\d]{1,40})'  # 全称
                r'[（(]\s*(?:以下简称|以下称|简称|下称)\s*'                   # 左括号+关键词
                r'((?:[\u201c\u201d\u201e\u201f""\'\u2018\u2019\u300c\u300d]'  # 开引号
                r'[\u4e00-\u9fa5A-Za-z\d]+'                                     # 简称内容
                r'[\u201c\u201d\u201e\u201f""\'\u2018\u2019\u300c\u300d]'  # 闭引号
                r'(?:\s*(?:或|、|，)\s*'                                         # 分隔符
                r'[\u201c\u201d\u201e\u201f""\'\u2018\u2019\u300c\u300d]'  # 开引号
                r'[\u4e00-\u9fa5A-Za-z\d]+'                                     # 简称内容
                r'[\u201c\u201d\u201e\u201f""\'\u2018\u2019\u300c\u300d])*'  # 闭引号
                r'))\s*[）)]'                                               # 右括号
            )
            # 从块中提取每个引号内的简称
            name_pattern = re.compile(
                r'[\u201c\u201d\u201e\u201f""\'\u2018\u2019\u300c\u300d]'
                r'(\s*[\u4e00-\u9fa5A-Za-z\d]+\s*)'
                r'[\u201c\u201d\u201e\u201f""\'\u2018\u2019\u300c\u300d]'
            )

            for prev in previously_generated:
                content = prev.get("summary", "")
                for block_match in block_pattern.finditer(content):
                    full_name = block_match.group(1).strip()
                    names_str = block_match.group(2)
                    for name_match in name_pattern.finditer(names_str):
                        short_name = name_match.group(1).strip()
                        if short_name and short_name not in seen_abbrs and len(short_name) <= 20:
                            abbreviations.append((full_name, short_name))
                            seen_abbrs.add(short_name)

            if abbreviations:
                context_parts.append("【严格禁止重复定义简称】前面章节已定义以下简称，本章节必须直接使用简称，绝对不允许再写'（以下简称…）'：")
                for full_name, short_name in abbreviations:
                    context_parts.append(f"- 「{short_name}」（全称：{full_name}，直接写「{short_name}」即可）")

            # 2) 最近章节的内容摘要（避免重复）
            recent = previously_generated[-5:]
            context_parts.append("以下是前面已生成章节的内容摘要，请避免重复这些内容：")
            for prev in recent:
                title = prev.get("title", "")
                summary = prev.get("summary", "")
                if title and summary:
                    context_parts.append(f"- {title}: {summary}")

        context_info = "\n".join(context_parts) if context_parts else ""

        # 项目信息
        project_text = (
            f"客户名称：{project_info.client_name}\n"
            f"审计期间：{project_info.audit_period}\n"
        )
        if project_info.key_matters:
            project_text += f"重要事项：{project_info.key_matters}\n"
        if project_info.additional_info:
            for k, v in project_info.additional_info.items():
                project_text += f"{k}：{v}\n"

        # 知识库内容
        has_knowledge = bool(knowledge_context.strip())
        knowledge_section = ""
        if has_knowledge:
            knowledge_section = (
                "========== 知识库参考资料（必须严格遵守） ==========\n"
                "以下是致同会计师事务所的真实资料，生成内容时必须优先使用这些信息。\n"
                "严禁编造任何不存在于以下资料中的案例、人员、制度、流程等具体信息。\n\n"
                f"{knowledge_context}\n\n"
                "========== 知识库参考资料结束 ==========\n\n"
            )

        # 填充字段提示
        fillable_hint = ""
        if fillable_fields:
            fillable_hint = (
                f"\n本章节需要填充的字段：{', '.join(fillable_fields)}\n"
                "请使用项目信息中的对应数据填充，缺失的标注【待补充】。\n"
            )

        if has_knowledge:
            knowledge_rule = "优先使用知识库中的真实信息填充，知识库未覆盖的部分结合审计专业知识撰写，仅具体数据（金额、日期、人名等）标注【待补充】"
        else:
            knowledge_rule = (
                "虽然没有知识库参考资料，但你必须根据客户名称、审计期间和章节主题，"
                "结合你的审计专业知识生成完整的实质性内容。"
                "审计程序、方法论、风险评估、内控描述等专业内容应直接撰写，"
                "只有确实需要客户具体数据的地方（如具体金额、合同编号、人员姓名）才标注【待补充】"
            )

        user_prompt = f"""请为以下审计文档章节生成内容：

项目信息：
{project_text}

{knowledge_section}{context_info + chr(10) if context_info else ""}当前章节信息：
章节编号: {section_id}
章节标题: {section_title}
章节描述: {section_desc}
{fillable_hint}
【生成要求】
1. {knowledge_rule}
2. 不要编造具体数字、具体案例、具体人员姓名，但审计方法、程序、框架等专业内容必须完整撰写
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 直接输出正文，不要输出章节标题或元信息
6. 不要使用Markdown标题格式（# ## ###），用中文序号组织层次
7. 内容要有实质性和针对性，结合客户所在行业特点展开，不要空泛罗列
8. 重要：如果前面章节已定义了简称（如"公司"、"一汽富奥"等），本章节必须直接使用简称，绝对禁止再次出现"（以下简称'XX'）"这样的表述，也不要再写全称"""

        messages = [
            {"role": "system", "content": _AUDIT_DOCUMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Token限制检查与截断
        context_limit = _get_context_limit(self.openai_service.model_name)
        max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
        total_tokens = sum(estimate_token_count(m["content"]) for m in messages)

        if total_tokens > max_input_tokens:
            logger.warning(
                "[Token限制] 章节 %s 输入约 %d tokens，超过限制 %d，将截断知识库内容",
                section_title, total_tokens, max_input_tokens,
            )
            overflow = total_tokens - max_input_tokens
            if knowledge_context:
                kb_tokens = estimate_token_count(knowledge_context)
                new_kb_max = max(kb_tokens - overflow - 500, 1000)
                truncated_kb = truncate_to_token_limit(knowledge_context, new_kb_max)
                # 重建 user_prompt with truncated knowledge
                knowledge_section = (
                    "========== 知识库参考资料（必须严格遵守） ==========\n"
                    f"{truncated_kb}\n"
                    "========== 知识库参考资料结束 ==========\n\n"
                )
                user_prompt = f"""请为以下审计文档章节生成内容：

项目信息：
{project_text}

{knowledge_section}{context_info + chr(10) if context_info else ""}当前章节信息：
章节编号: {section_id}
章节标题: {section_title}
章节描述: {section_desc}
{fillable_hint}
【生成要求】
1. 优先使用知识库中的真实信息填充，知识库未覆盖的部分结合审计专业知识撰写，仅具体数据标注【待补充】
2. 不要编造具体数字、具体案例、具体人员姓名，但审计方法、程序、框架等专业内容必须完整撰写
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 直接输出正文，不要输出章节标题或元信息
6. 内容要有实质性和针对性，结合客户所在行业特点展开
7. 重要：如果前面章节已定义了简称，本章节必须直接使用简称，绝对禁止再次出现"（以下简称'XX'）"这样的表述"""
                messages[1]["content"] = user_prompt

        async for chunk in self.openai_service.stream_chat_completion(
            messages, temperature=0.7
        ):
            yield chunk

    # ── 章节修改 ──

    async def revise_section_stream(
        self,
        section_index: int,
        current_content: str,
        user_instruction: str,
        document_context: Optional[Dict[str, Any]] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        selected_text: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """AI对话式修改章节内容。

        支持全文修改和选中文本局部修改。
        若 selected_text 非空，仅对选中部分进行修改，其余内容保持不变。
        """
        if messages is None:
            messages = []

        system_prompt = _AUDIT_DOCUMENT_SYSTEM_PROMPT

        if selected_text:
            # 局部修改模式：仅修改选中文本
            revision_prompt = (
                f"以下是当前章节的完整内容：\n\n{current_content}\n\n"
                f"用户选中了以下文本要求修改：\n「{selected_text}」\n\n"
                f"用户的修改指令：{user_instruction}\n\n"
                "请仅输出修改后的选中部分文本（不要输出完整章节内容），"
                "保持与上下文的连贯性。"
            )
        else:
            # 全文修改模式
            revision_prompt = (
                f"以下是当前章节的完整内容：\n\n{current_content}\n\n"
                f"用户的修改指令：{user_instruction}\n\n"
                "请根据用户指令修改章节内容，输出修改后的完整章节内容。"
                "保持专业的审计文档风格，严禁编造事实性信息。"
            )

        # 构建对话消息列表
        chat_messages = [{"role": "system", "content": system_prompt}]

        # 添加历史对话
        for msg in messages:
            chat_messages.append(msg)

        # 添加当前修改请求
        chat_messages.append({"role": "user", "content": revision_prompt})

        async for chunk in self.openai_service.stream_chat_completion(
            chat_messages, temperature=0.7
        ):
            yield chunk

    # ── Word 导出 ──

    async def export_to_word(
        self,
        document: GeneratedDocument,
        template_id: str,
        font_settings: Optional[FontSettings] = None,
    ) -> bytes:
        """导出为Word格式。

        将 GeneratedDocument 的章节结构转换为 OutlineItem 格式，
        调用 WordExportService.build_document() 生成Word文档。
        字体设置统一由 WordExportService 处理，避免重复应用。
        """
        outline_data = self._build_export_outline(document)

        word_service = WordExportService()
        buffer = word_service.build_document(
            outline_data,
            project_name=f"{document.project_info.client_name} 审计文档",
            font_settings=font_settings,
        )

        return buffer.read()

    def _build_export_outline(
        self, document: GeneratedDocument
    ) -> List[TemplateOutlineItem]:
        """将 GeneratedDocument 转换为 WordExportService 可用的大纲格式。

        将 sections 的内容填充到 outline 的叶子节点中。
        """
        if document.outline:
            # 使用原始大纲结构，填充生成的内容
            outline_copy = [item.model_copy(deep=True) for item in document.outline]
            section_map = {s.title: s.content for s in document.sections}
            self._fill_outline_content(outline_copy, section_map)
            return outline_copy

        # 没有大纲结构时，直接从 sections 构建扁平大纲
        items = []
        for section in document.sections:
            items.append(
                TemplateOutlineItem(
                    id=str(section.index + 1),
                    title=section.title,
                    description="",
                    content=section.content,
                    children=[],
                )
            )
        return items

    def _fill_outline_content(
        self,
        items: List[TemplateOutlineItem],
        section_map: Dict[str, str],
    ) -> None:
        """递归将生成的内容填充到大纲叶子节点。"""
        for item in items:
            if item.children:
                self._fill_outline_content(item.children, section_map)
            else:
                # 叶子节点：尝试匹配 section 内容
                if item.title in section_map:
                    item.content = section_map[item.title]

    # ── 序列化 / 反序列化 ──

    def parse_document_to_structured(self, document: GeneratedDocument) -> dict:
        """将文档解析为结构化数据格式。"""
        return document.model_dump(mode="json")

    def structured_to_document(self, data: dict) -> GeneratedDocument:
        """从结构化数据重建文档对象。"""
        return GeneratedDocument.model_validate(data)

    # ── 辅助方法 ──

    def _dicts_to_outline_items(
        self, dicts: List[Dict[str, Any]]
    ) -> List[TemplateOutlineItem]:
        """将字典列表转换为 TemplateOutlineItem 列表。"""
        items = []
        for d in dicts:
            children = None
            if d.get("children"):
                children = self._dicts_to_outline_items(d["children"])
            items.append(
                TemplateOutlineItem(
                    id=d.get("id", ""),
                    title=d.get("title", ""),
                    description=d.get("description", ""),
                    target_word_count=d.get("target_word_count"),
                    fillable_fields=d.get("fillable_fields"),
                    children=children,
                    content=d.get("content"),
                )
            )
        return items
