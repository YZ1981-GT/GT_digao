# 需求文档：审计底稿智能复核与文档生成程序

## 简介

审计底稿智能复核与文档生成程序是一个面向会计师事务所审计项目组的智能复核与文档生成工具。该系统基于现有AI标书写作助手的FastAPI + React前后端分离架构，提供两大核心功能：一是调用大语言模型对项目组上传的审计底稿进行多维度自动化复核；二是基于用户上传的底稿模板，结合知识库中的行业材料、公司自身要求、质控和技术标准、团队人员情况等信息，智能生成审计文档（包括审计计划、审计小结、尽调报告、审计报告等）。系统整合事务所底稿模板库、监管规定库、会计准则库和质控标准库等知识资源，在复核模式下从格式规范性、数据勾稽关系、会计准则合规性、审计程序完整性等维度对底稿进行智能复核，生成结构化的复核报告（含问题清单、风险等级、修改建议）；在文档生成模式下基于模板和知识库自动生成标准化审计文档。系统通过工作模式选择入口，帮助项目经理和合伙人灵活选择复核或文档生成工作流，全面提升审计工作效率与质量。

## 术语表

- **Review_System（复核系统）**: 审计底稿复核程序的整体系统，包含前端界面和后端服务
- **Workpaper_Parser（底稿解析器）**: 负责解析上传的审计底稿文件（Excel、Word、PDF等格式），提取结构化内容的后端服务模块
- **Review_Engine（复核引擎）**: 调用大语言模型，结合知识库对底稿进行多维度复核分析的核心后端服务
- **Knowledge_Manager（知识库管理器）**: 管理底稿模板库、监管规定库、会计准则库、质控标准库等知识资源的服务模块
- **Report_Generator（报告生成器）**: 将复核结果整合为结构化复核报告（含问题清单、风险等级、修改建议）的服务模块
- **Project_Manager（项目管理器）**: 按审计项目组织底稿、管理用户权限和复核流程的服务模块
- **Audit_Workpaper（审计底稿）**: 审计人员在执行审计程序过程中编制的工作文件，包括B类（业务层面控制）、C类（控制测试）、D-M类（实质性测试）等
- **Review_Dimension（复核维度）**: 对底稿进行复核的不同角度，包括格式规范性、数据勾稽关系、会计准则合规性、审计程序完整性等
- **Review_Report（复核报告）**: 复核引擎生成的结构化输出，包含问题清单、风险等级评定和修改建议
- **Risk_Level（风险等级）**: 复核发现问题的严重程度分类，分为高风险、中风险、低风险三个等级
- **Business_Cycle（业务循环）**: 审计底稿按业务性质的分类方式，如销售循环、货币资金循环、存货循环、投资循环等
- **Cross_Reference（交叉索引）**: 审计底稿之间的逻辑引用关系，如B类底稿引用C类底稿、C类底稿引用D-M类底稿等
- **GT_Design_System（GT设计系统）**: 致同GT审计手册设计规范中定义的完整视觉设计体系，包括颜色系统、字体规范、布局系统、组件库和可访问性标准
- **GT_Component_Library（GT组件库）**: 基于致同GT设计规范的前端UI组件集合，所有CSS类名使用gt-前缀，采用BEM风格命名规范
- **Document_Generator（文档生成器）**: 基于用户上传的底稿模板和知识库内容，调用大语言模型生成审计文档的后端服务模块
- **Template_Manager（模板管理器）**: 管理用户上传的审计底稿模板的服务模块，负责模板的上传、解析、分类、存储和检索
- **Work_Mode（工作模式）**: 用户在系统入口选择的操作模式，包括"底稿复核"和"文档生成"两种
- **Review_Prompt（复核提示词）**: 复核引擎在调用大语言模型时使用的提示词模板，包括系统从TSJ文件夹加载的预置提示词和用户自定义提示词
- **Prompt_Library（提示词库）**: 作为Knowledge_Manager管理的知识库分类之一，负责管理和存储复核提示词模板的服务模块。预置提示词（默认版本）从项目TSJ/目录加载markdown文件，按会计科目分类（如货币资金、应收账款、存货、固定资产等）；支持用户对预置提示词进行修改、替换和追加补充；通过Git仓库（YZ1981-GT/GT_digao）实现提示词的版本管理和同步
- **Prompt_Git_Repository（提示词Git仓库）**: 提示词库关联的远程Git仓库（YZ1981-GT/GT_digao），用于提示词的版本管理、变更追踪和团队间同步
- **TSJ_Directory（TSJ提示词目录）**: 项目中的TSJ/文件夹，包含约70个按会计科目分类的审计复核提示词markdown文件，每个文件包含完整的复核清单、审计认定要点、程序要点、风险评估等内容，提示词中使用{{#sys.files#}}占位符引用实际上传的底稿文件列表
- **Accounting_Subject（会计科目）**: 预置提示词的分类维度，包括货币资金、应收账款、存货、固定资产、长期股权投资、收入、成本等，每个会计科目对应TSJ文件夹中的一个或多个提示词文件
- **Review_Confirmation（复核确认）**: 用户在复核过程中对提示词选择、补充材料上传等配置进行确认后，系统才正式生成复核报告的交互流程
- **Section_Editor（章节编辑器）**: 文档生成模式下，支持用户对每个章节进行手动文本编辑和AI辅助修改的编辑组件，参照现有ContentEdit.tsx中的ManualEditState模式
- **Font_Settings（字体设置）**: 文档导出时的字体配置，包括中文字体、英文字体和字号设置，参照现有word_service.py中的DEFAULT_FONT_NAME和set_run_font机制

## 需求

### 需求 1：底稿文件上传与解析

**用户故事：** 作为审计项目组成员，我希望上传各种格式的审计底稿文件，以便系统对底稿内容进行解析和后续复核。

#### 验收标准

1. WHEN 用户上传Excel格式（.xlsx、.xls）的审计底稿文件，THE Workpaper_Parser SHALL 解析文件中所有工作表的内容，提取单元格数据、公式、合并单元格信息和工作表结构，并返回结构化的解析结果
2. WHEN 用户上传Word格式（.docx）的审计底稿文件，THE Workpaper_Parser SHALL 解析文件中的段落文本、表格数据、标题层级和批注内容，并返回结构化的解析结果
3. WHEN 用户上传PDF格式的审计底稿文件，THE Workpaper_Parser SHALL 提取文件中的文本内容和表格数据，并返回结构化的解析结果
4. WHEN 用户上传的文件大小超过50MB，THE Review_System SHALL 拒绝上传并向用户显示文件大小超限的提示信息
5. WHEN 用户上传的文件格式不在支持列表（xlsx、xls、docx、pdf）中，THE Review_System SHALL 拒绝上传并向用户显示不支持该文件格式的提示信息
6. IF 文件解析过程中发生错误（如文件损坏、加密文件），THEN THE Workpaper_Parser SHALL 返回包含错误原因的描述信息，并在界面上向用户展示该错误信息
7. WHEN 用户一次上传多个底稿文件（批量上传），THE Workpaper_Parser SHALL 按顺序解析每个文件，并为每个文件独立返回解析结果和解析状态
8. THE Workpaper_Parser SHALL 自动识别上传底稿的编号体系（B类、C类、D-M类），并将底稿归类到对应的业务循环类别

### 需求 2：多维度底稿复核

**用户故事：** 作为项目经理，我希望系统能从多个专业维度对审计底稿进行智能复核，以便快速发现底稿中的问题和不足。

#### 验收标准

1. WHEN 用户选择底稿并发起复核请求，THE Review_Engine SHALL 从格式规范性维度检查底稿是否符合事务所底稿模板的格式要求，包括编号规范、标题层级、必填字段完整性和签章要求
2. WHEN 用户选择底稿并发起复核请求，THE Review_Engine SHALL 从数据勾稽关系维度检查底稿中的数值数据是否满足逻辑一致性，包括加总关系、交叉引用数据一致性和与财务报表数据的勾稽关系
3. WHEN 用户选择底稿并发起复核请求，THE Review_Engine SHALL 从会计准则合规性维度检查底稿中涉及的会计处理是否符合中国企业会计准则和相关监管规定
4. WHEN 用户选择底稿并发起复核请求，THE Review_Engine SHALL 从审计程序完整性维度检查底稿是否覆盖了该业务循环所要求的全部审计程序步骤，包括穿行测试、控制测试和实质性测试的完整性
5. WHEN 用户选择底稿并发起复核请求，THE Review_Engine SHALL 从审计证据充分性维度检查底稿中记录的审计证据是否充分、适当，包括样本量是否合理、证据类型是否恰当
6. WHERE 用户选择自定义复核维度，THE Review_Engine SHALL 允许用户指定额外的复核关注点，并将自定义维度纳入复核分析范围
7. WHILE 复核引擎正在执行复核分析，THE Review_System SHALL 通过SSE（Server-Sent Events）流式输出复核进度和中间结果，使用户能够实时查看复核过程
8. THE Review_Engine SHALL 对每个复核发现标注Risk_Level（高风险、中风险、低风险），高风险表示可能导致审计意见错误的问题，中风险表示影响底稿质量但不影响审计结论的问题，低风险表示格式或表述方面的改进建议
9. WHEN 用户发起复核请求，THE Review_System SHALL 展示可选的预置Review_Prompt列表，用户可以从Prompt_Library中选择一个预置提示词作为复核依据
10. WHERE 用户选择使用自定义提示词，THE Review_System SHALL 提供文本输入区域，允许用户输入自定义Review_Prompt，Review_Engine在复核时使用用户输入的自定义提示词替代或补充预置提示词
11. WHEN 复核过程中Review_Engine识别到需要参考其他相关底稿（如交叉引用的底稿未上传），THE Review_System SHALL 暂停复核流程，向用户展示所需的相关底稿清单，并提供上传入口供用户补充上传所需底稿或手动输入补充信息
12. WHEN 用户完成补充材料的上传或输入后确认继续，THE Review_Engine SHALL 将补充材料纳入复核上下文，继续执行复核分析
13. WHEN 复核维度配置、提示词选择和补充材料上传全部完成后，THE Review_System SHALL 展示复核配置确认页面，汇总展示已选底稿、复核维度、所选提示词和已上传补充材料，用户确认后才正式生成复核报告

### 需求 3：知识库管理

**用户故事：** 作为质量控制部门负责人，我希望管理和维护复核所依据的各类知识库，以便复核引擎能够基于最新的准则和规定进行复核。

#### 验收标准

1. THE Knowledge_Manager SHALL 提供以下预配置知识库分类：底稿模板库、监管规定库、会计准则库、质控标准库、审计程序库、行业指引库、提示词库（Prompt_Library），其中提示词库作为知识库的一个分类，由Prompt_Library模块专门管理，遵循与其他知识库分类一致的文档管理和检索机制
2. WHEN 用户向知识库上传文档（支持PDF、Word、Markdown、TXT、Excel格式），THE Knowledge_Manager SHALL 解析文档内容并将解析后的文本存储到对应的知识库分类中
3. WHEN 用户删除知识库中的文档，THE Knowledge_Manager SHALL 从存储和缓存中同步移除该文档的内容
4. WHEN 复核引擎发起知识库检索请求，THE Knowledge_Manager SHALL 根据底稿的业务循环类别和复核维度，从相关知识库中检索匹配的参考内容，并返回检索结果
5. THE Knowledge_Manager SHALL 对已加载的知识库文档内容进行缓存，缓存上限为300个文档，采用LRU策略管理缓存淘汰
6. WHEN 用户查看知识库概览，THE Knowledge_Manager SHALL 展示每个知识库分类的文档数量、已缓存文档数量和知识库描述信息
7. THE Knowledge_Manager SHALL 支持按关键词在指定知识库中搜索文档内容，搜索结果按相关性排序并返回匹配的文档段落

### 需求 4：复核报告生成与导出

**用户故事：** 作为项目经理，我希望系统生成结构化的复核报告，以便我能够快速了解底稿问题并指导项目组成员进行修改。

#### 验收标准

1. WHEN 复核分析完成，THE Report_Generator SHALL 生成包含以下结构的复核报告：复核概要（底稿信息、复核时间、复核维度）、问题清单（按风险等级排序）、每个问题的详细描述和修改建议、复核结论
2. WHEN 复核报告生成完成，THE Report_Generator SHALL 按风险等级对问题进行统计汇总，展示高风险问题数量、中风险问题数量和低风险问题数量
3. WHEN 用户请求导出复核报告，THE Report_Generator SHALL 支持将报告导出为Word格式（.docx），导出的报告包含完整的问题清单、修改建议和复核结论
4. WHEN 用户请求导出复核报告，THE Report_Generator SHALL 支持将报告导出为PDF格式，导出的报告保持与页面展示一致的排版格式
5. THE Report_Generator SHALL 在复核报告中为每个问题提供具体的修改建议，修改建议包含问题定位（底稿位置）、问题描述、参考依据（准则条款或模板要求）和建议修改内容
6. WHEN 用户对复核报告中的某个问题标记为"已处理"，THE Review_System SHALL 记录该问题的处理状态和处理时间
7. THE Report_Generator SHALL 解析复核报告为结构化数据格式，WHEN 对同一底稿的复核报告进行解析后再重新生成，THE Report_Generator SHALL 产生与原始报告内容等价的结构化数据（往返一致性）

### 需求 5：项目管理与权限控制

**用户故事：** 作为合伙人，我希望按审计项目组织和管理底稿复核工作，并控制不同角色的访问权限，以便确保复核流程的规范性和信息安全。

#### 验收标准

1. WHEN 用户创建新的审计项目，THE Project_Manager SHALL 记录项目名称、客户名称、审计期间、项目组成员和项目状态信息
2. WHEN 用户将底稿上传到指定项目，THE Project_Manager SHALL 将底稿文件与该项目关联，并在项目视图中展示该项目下的所有底稿列表
3. THE Project_Manager SHALL 支持以下用户角色：合伙人（全部权限）、项目经理（项目内全部权限）、审计员（上传底稿和查看复核报告权限）、质控人员（查看所有项目的复核报告权限）
4. WHEN 审计员角色的用户尝试删除底稿或修改复核报告，THE Project_Manager SHALL 拒绝该操作并显示权限不足的提示信息
5. WHEN 用户查看项目列表，THE Project_Manager SHALL 仅展示该用户有权限访问的项目
6. THE Project_Manager SHALL 在项目视图中展示该项目的复核进度概览，包括已复核底稿数量、待复核底稿数量和各风险等级问题的汇总统计
7. WHEN 用户按业务循环筛选底稿，THE Project_Manager SHALL 根据底稿编号体系（B类、C类、D-M类）和业务循环分类（销售循环、货币资金循环等）过滤并展示匹配的底稿列表

### 需求 6：LLM集成与流式输出

**用户故事：** 作为系统管理员，我希望系统能够灵活配置和集成不同的大语言模型供应商，以便根据成本和性能需求选择合适的模型。

#### 验收标准

1. THE Review_System SHALL 支持通过配置界面设置LLM供应商的API密钥、Base URL和模型名称
2. WHEN 用户在配置界面修改LLM配置后，THE Review_System SHALL 使用新配置进行后续的复核请求，无需重启服务
3. THE Review_Engine SHALL 通过SSE（Server-Sent Events）协议向前端流式输出复核分析结果，前端实时渲染接收到的内容
4. THE Review_Engine SHALL 在调用LLM之前估算输入内容的Token数量，WHEN 输入内容超过模型上下文窗口限制时，THE Review_Engine SHALL 对知识库参考内容进行截断以确保请求不超过模型上下文限制
5. IF LLM API调用返回429（限流）错误，THEN THE Review_Engine SHALL 采用递增等待策略自动重试，最多重试5次
6. THE Review_Engine SHALL 在复核提示词中注入审计专业上下文，包括底稿所属业务循环、适用的审计准则条款和事务所质控标准
7. WHEN 用户在配置界面请求获取可用模型列表，THE Review_System SHALL 从LLM供应商API获取模型列表，IF API不支持列出模型，THEN THE Review_System SHALL 返回预配置的推荐模型列表

### 需求 7：前端交互与工作流

**用户故事：** 作为审计项目组成员，我希望通过直观的界面完成底稿上传、复核发起和报告查看的完整工作流，以便高效地完成复核工作。

#### 验收标准

1. THE Review_System SHALL 提供Work_Mode选择入口，"底稿复核"模式下提供四步骤工作流（底稿上传与选择 → 提示词选择与复核维度配置 → 补充材料与确认 → 复核报告查看与导出），"文档生成"模式下提供四步骤工作流（模板上传与配置 → 大纲识别与确认 → 逐章节生成与编辑 → 导出），工作流界面的所有步骤指示器、卡片和按钮组件均采用GT_Design_System中定义的gt-前缀组件（gt-card、gt-button、gt-flow-diagram等）
2. WHEN 用户处于底稿上传步骤，THE Review_System SHALL 支持拖拽上传和点击选择文件两种上传方式，并展示上传进度和解析状态，上传区域使用GT_Design_System中的gt-card组件样式，进度条使用GT核心紫色（#4b2d77）作为填充色
3. WHEN 用户处于提示词选择与复核维度配置步骤，THE Review_System SHALL 展示所有可用的复核维度（格式规范性、数据勾稽关系、会计准则合规性、审计程序完整性、审计证据充分性），用户可以勾选需要执行的维度，同时展示Prompt_Library中的预置提示词列表供用户选择，并提供自定义提示词输入区域
4. WHILE 复核引擎正在执行复核，THE Review_System SHALL 在界面上展示实时的复核进度条和当前正在分析的维度名称
5. WHEN 复核完成，THE Review_System SHALL 在报告查看步骤展示复核报告，报告按风险等级分组展示问题清单，高风险问题使用GT_Design_System功能色中的危险色（#DC3545）标识，中风险问题使用警告色（#FFC107）标识，低风险问题使用信息色（#17A2B8）标识，用户可以展开查看每个问题的详细信息和修改建议
6. THE Review_System SHALL 使用IndexedDB在浏览器端缓存用户的工作状态（已上传底稿列表、复核配置、所选提示词、补充材料、复核报告），WHEN 用户刷新页面或重新打开浏览器，THE Review_System SHALL 恢复上次的工作状态
7. THE Review_System SHALL 提供响应式布局，在桌面端（宽度≥1024px）采用GT_Design_System中的gt-grid多列网格布局，在平板端（宽度≥768px）自动折叠为单列或双列布局，确保所有功能均可正常使用
8. WHEN 用户处于补充材料与确认步骤，THE Review_System SHALL 展示复核引擎识别到的所需相关底稿清单，提供文件上传入口和文本输入区域供用户补充材料，并在底部展示完整的复核配置汇总（已选底稿、复核维度、所选提示词、已上传补充材料），用户点击"确认并开始复核"按钮后才正式发起复核

### 需求 8：底稿交叉引用与关联分析

**用户故事：** 作为项目经理，我希望系统能够识别和验证底稿之间的交叉引用关系，以便确保底稿体系的逻辑完整性。

#### 验收标准

1. WHEN 用户上传同一业务循环的多个底稿（如B类、C类和D-M类），THE Review_Engine SHALL 识别底稿之间的交叉引用关系，并验证引用的底稿是否存在
2. WHEN 底稿中引用了其他底稿的编号但该底稿未上传，THE Review_Engine SHALL 在复核报告中标注缺失的引用底稿，并将该问题标记为中风险
3. THE Review_Engine SHALL 验证同一业务循环内B类底稿（穿行测试）的结论是否与C类底稿（控制测试）的测试范围一致
4. THE Review_Engine SHALL 验证C类底稿（控制测试）的结论是否与D-M类底稿（实质性测试）的测试范围调整一致（如控制有效则实质性测试范围可缩小）
5. WHEN 用户查看某个底稿的复核结果，THE Review_System SHALL 展示该底稿与其他底稿的关联关系图，标注关联底稿的名称和引用方向

### 需求 9：UI/UX设计规范与致同GT品牌一致性

**用户故事：** 作为致同GT审计项目组成员，我希望复核系统的界面严格遵循致同GT审计手册设计规范，以便系统的视觉风格与事务所品牌形象保持一致，并提供专业、易用的操作体验。

#### 验收标准

##### 品牌视觉一致性

1. THE Review_System SHALL 使用GT_Design_System中定义的主色调体系：GT核心紫色（#4b2d77）作为主要操作色，亮紫色（#A06DFF）作为辅助高亮色，深紫色（#2B1D4D）作为悬停和强调色
2. THE Review_System SHALL 使用GT_Design_System中定义的辅助色系：水鸭蓝（#0094B3）、珊瑚橙（#FF5149）、麦田黄（#FFC23D）用于状态标识和视觉强调
3. THE Review_System SHALL 使用GT_Design_System中定义的文字颜色规范：主文字使用#2C3E50，次要文字使用#666666，紫色背景区域的文字使用白色（#FFFFFF）
4. THE Review_System SHALL 使用GT_Design_System中定义的字体族：中文使用方正悦黑系列（FZYueHei），英文使用GT Walsheim系列，并按规范配置回退字体链
5. THE Review_System SHALL 使用GT_Design_System中定义的模块化字体缩放系统（12px至36px），标题层级从h1（30px/700）到h4（18px/600）严格遵循规范定义的字号和字重

##### 组件库使用规范

6. THE Review_System SHALL 使用GT_Component_Library中以gt-前缀命名的CSS类名系统，包括布局类（gt-container、gt-section、gt-grid）、卡片类（gt-card、gt-card-header、gt-card-content）、表格类（gt-table）和按钮类（gt-button）
7. THE Review_System SHALL 使用GT_Design_System中定义的状态类（gt-active、gt-disabled、gt-loading、gt-success、gt-warning、gt-error）表达界面元素的交互状态
8. THE Review_System SHALL 使用GT_Design_System中定义的间距系统（基于4px基础网格，间距从4px到64px）和圆角系统（4px、8px、12px三级圆角）构建界面布局
9. THE Review_System SHALL 使用GT_Design_System中定义的阴影系统（基于GT核心紫色的三级阴影：sm、md、lg）为卡片和浮层元素提供层次感

##### 可访问性要求

10. THE Review_System SHALL 满足WCAG 2.1 AA级可访问性标准，正文文字（小于18px）与背景的对比度不低于4.5:1，大文字（18px及以上）与背景的对比度不低于3:1
11. THE Review_System SHALL 为所有交互元素（按钮、链接、表单控件）提供符合GT_Design_System规范的焦点样式：默认使用3px亮紫色（#A06DFF）轮廓线，紫色背景区域使用麦田黄（#FFC23D）轮廓线
12. THE Review_System SHALL 使用语义化HTML结构：表格包含caption和scope属性，装饰性图标使用aria-hidden="true"，导航区域使用nav标签并添加aria-label，章节使用aria-labelledby关联标题

##### 风险等级视觉表达

13. WHEN 复核报告展示高风险问题，THE Review_System SHALL 使用GT_Design_System功能色中的危险色（#DC3545）作为该问题的视觉标识色（左侧边框或背景色标）
14. WHEN 复核报告展示中风险问题，THE Review_System SHALL 使用GT_Design_System功能色中的警告色（#FFC107）作为该问题的视觉标识色
15. WHEN 复核报告展示低风险问题，THE Review_System SHALL 使用GT_Design_System功能色中的信息色（#17A2B8）作为该问题的视觉标识色
16. THE Review_System SHALL 在风险等级标识中同时使用颜色和文字标签（如"高风险"、"中风险"、"低风险"），确保色觉障碍用户能够区分风险等级

##### 打印样式支持

17. WHEN 用户打印复核报告页面，THE Review_System SHALL 应用GT_Design_System中定义的打印样式：页面设置为A4尺寸（页边距上下20mm、左右15mm），正文使用黑白配色，隐藏导航按钮等非打印元素
18. WHEN 用户打印复核报告页面，THE Review_System SHALL 确保卡片、表格和流程步骤组件不会在分页处断裂（使用break-inside: avoid），标题不会出现在页面底部（使用break-after: avoid）
19. WHEN 用户打印复核报告页面，THE Review_System SHALL 将章节头部的紫色渐变背景替换为白色背景加GT核心紫色下边框，表格头部替换为浅灰色背景加黑色文字，确保打印输出的专业性和可读性

##### 响应式设计

20. THE Review_System SHALL 在桌面端（宽度≥1024px）使用GT_Design_System中的多列网格布局（gt-grid-2、gt-grid-3、gt-grid-4），在平板端（宽度768px至1023px）将三列和四列网格折叠为双列布局
21. WHEN 屏幕宽度小于768px，THE Review_System SHALL 将所有多列网格折叠为单列布局，章节标题字号从30px缩小至24px，确保内容在小屏幕上的可读性


### 需求 10：工作模式选择与导航

**用户故事：** 作为审计项目组成员，我希望在系统入口处选择工作模式（复核底稿或生成文档），以便快速进入对应的工作流程。

#### 验收标准

1. THE Review_System SHALL 在系统首页展示Work_Mode选择界面，提供"底稿复核"和"文档生成"两个入口
2. WHEN 用户选择"底稿复核"模式，THE Review_System SHALL 导航至四步骤复核工作流（底稿上传与选择 → 提示词选择与复核维度配置 → 补充材料与确认 → 复核报告查看与导出）
3. WHEN 用户选择"文档生成"模式，THE Review_System SHALL 导航至四步骤文档生成工作流（模板上传与配置 → 大纲识别与确认 → 逐章节生成与编辑 → 导出）
4. WHILE 用户处于任一工作模式中，THE Review_System SHALL 在界面顶部或侧边栏提供Work_Mode切换入口，允许用户随时切换到另一工作模式
5. THE Review_System SHALL 使用GT_Design_System中的gt-card组件展示Work_Mode选择界面，每个工作模式以独立卡片形式呈现，卡片包含模式名称、功能描述和入口按钮

### 需求 11：审计文档模板管理

**用户故事：** 作为项目经理，我希望上传和管理审计底稿模板，以便系统基于模板生成标准化的审计文档。

#### 验收标准

1. WHEN 用户上传Word格式（.docx）、Excel格式（.xlsx、.xls）或PDF格式的底稿模板文件，THE Template_Manager SHALL 接收并存储该模板文件
2. THE Template_Manager SHALL 提供以下预置模板类型分类：审计计划模板、审计小结模板、尽调报告模板、审计报告模板、其他自定义模板
3. WHEN 用户上传模板文件后，THE Template_Manager SHALL 解析模板的结构信息，提取章节标题、表格结构和需要填充的内容区域（填写项），并将解析结果展示给用户确认
4. WHEN 用户查看模板列表，THE Template_Manager SHALL 展示所有已上传模板的名称、类型分类、上传时间和文件格式信息
5. WHEN 用户请求删除某个模板，THE Template_Manager SHALL 从存储中移除该模板文件及其解析数据
6. WHEN 用户请求更新某个模板（重新上传同名模板），THE Template_Manager SHALL 替换原有模板文件并重新解析模板结构
7. WHEN 用户将模板与审计项目关联，THE Project_Manager SHALL 记录模板与项目的关联关系，并在项目视图中展示该项目关联的模板列表
8. IF 模板文件解析过程中发生错误（如文件损坏、格式不支持），THEN THE Template_Manager SHALL 返回包含错误原因的描述信息，并在界面上向用户展示该错误信息

### 需求 12：基于模板的审计文档生成

**用户故事：** 作为审计项目组成员，我希望选择一个底稿模板，系统结合知识库自动生成审计文档，以便提高文档编制效率。

#### 验收标准

1. WHEN 用户选择一个底稿模板发起文档生成，THE Document_Generator SHALL 展示该模板的结构（章节列表、表格结构）和需要填充的内容区域
2. WHEN 用户进入文档生成配置步骤，THE Review_System SHALL 展示可关联的知识库列表（行业材料库、公司要求库、质控标准库、团队人员库等），用户可以勾选需要关联的知识库
3. WHEN 用户进入文档生成配置步骤，THE Review_System SHALL 提供项目特定信息的输入表单，包括客户名称、审计期间、重要事项等字段，用户可以补充填写
4. WHEN 用户确认配置并发起文档生成，THE Document_Generator SHALL 调用大语言模型，结合模板结构、所选知识库内容和用户填写的项目信息，生成文档内容
5. WHILE Document_Generator正在生成文档内容，THE Review_System SHALL 通过SSE（Server-Sent Events）协议向前端流式输出生成进度和已生成的内容片段，前端实时渲染展示
6. WHEN 文档生成完成，THE Review_System SHALL 以章节为单位展示生成的文档内容，每个章节提供"手动编辑"和"AI修改"两个操作入口，用户可以点击任意章节进入编辑模式
7. WHEN 用户点击某个章节的"手动编辑"按钮，THE Section_Editor SHALL 打开文本编辑区域，用户可以直接修改章节文本内容，支持选中部分文本后仅对选中部分发起AI辅助修改（参照现有ContentEdit.tsx中ManualEditState的交互模式）
8. WHEN 用户对生成文档的某个章节发起AI对话式修改请求，THE Document_Generator SHALL 根据用户的修改指令调用大语言模型重新生成该章节内容，并流式输出修改结果
9. WHEN 用户请求导出生成的审计文档，THE Document_Generator SHALL 将文档导出为Word格式（.docx），导出的文档保持模板定义的格式和排版
10. THE Document_Generator SHALL 支持生成以下类型的审计文档：审计计划、审计小结、尽调报告、审计报告，以及用户通过自定义模板定义的其他文档类型
11. THE Document_Generator SHALL 在生成文档内容时优先使用知识库中的真实信息填充模板，WHEN 知识库中未覆盖模板某个填充区域所需的信息，THE Document_Generator SHALL 在该区域标注【待补充】占位符
12. THE Document_Generator SHALL 在生成文档内容时严禁编造具体数字、具体案例、具体人员姓名等事实性信息，所有事实性内容来源于知识库或用户填写的项目信息
13. FOR ALL 有效的审计文档结构化数据，THE Document_Generator SHALL 确保将文档导出为Word格式后再重新解析，产生与原始文档内容等价的结构化数据（往返一致性）
14. WHEN 用户在文档生成工作流中进入导出步骤，THE Review_System SHALL 展示Font_Settings配置面板，允许用户设置导出Word文档的目标字体（中文字体名称和英文字体名称），默认使用系统预置字体（参照现有word_service.py中的DEFAULT_FONT_NAME配置）
15. WHEN 用户修改Font_Settings后请求导出文档，THE Document_Generator SHALL 使用用户指定的字体设置生成Word文档，对文档中所有段落和标题应用用户选择的字体（参照现有word_service.py中set_run_font和set_paragraph_font的字体设置机制）
16. THE Section_Editor SHALL 为每个章节独立维护编辑状态，包括手动编辑内容、AI修改对话历史和目标字数设置，章节之间的编辑操作互不影响
17. WHEN 用户上传底稿模板后，THE Document_Generator SHALL 调用大语言模型自动识别模板中的章节结构（标题、层级、内容摘要），生成模板大纲（TemplateOutlineItem列表），并在大纲确认界面展示给用户；用户可以对大纲进行调整（增删改章节、调整层级和顺序），确认后系统才进入逐章节生成阶段（参照现有OutlineEdit.tsx的大纲编辑交互模式和generate_outline_with_old_prompt的大纲提取逻辑）

### 需求 13：复核提示词管理

**用户故事：** 作为项目经理，我希望选择、修改、替换或追加复核提示词，以便根据不同底稿类型和复核场景灵活调整复核策略，并通过Git仓库实现提示词的版本管理和团队共享。

#### 验收标准

##### 预置提示词加载与展示

1. THE Prompt_Library SHALL 从项目TSJ_Directory中加载预置复核提示词作为默认版本，每个markdown文件作为一个独立的预置提示词，按Accounting_Subject（会计科目）分类，包括但不限于：货币资金、应收账款、存货、固定资产、长期股权投资、收入、成本、审计方案等
2. WHEN 用户查看提示词列表，THE Prompt_Library SHALL 展示每个提示词的名称、适用会计科目、提示词来源（预置/用户修改/用户追加）、提示词摘要和使用次数
3. WHEN 用户选择一个提示词，THE Review_System SHALL 在提示词预览区域展示该提示词的完整内容，用户可以确认使用或继续选择其他提示词
4. THE Prompt_Library SHALL 支持按会计科目筛选提示词，WHEN 用户已选择会计科目后，THE Prompt_Library SHALL 优先展示与所选会计科目匹配的提示词

##### 用户修改预置提示词

5. WHEN 用户选择一个预置提示词并点击"编辑"操作，THE Prompt_Library SHALL 打开提示词编辑器，展示该预置提示词的完整内容，允许用户对内容进行修改
6. WHEN 用户修改预置提示词内容并保存，THE Prompt_Library SHALL 将修改后的版本存储为该预置提示词的用户自定义版本，同时保留原始预置版本（从TSJ_Directory加载的默认版本）
7. WHEN 用户查看已修改的预置提示词，THE Prompt_Library SHALL 提供"恢复默认版本"操作，用户确认后将该提示词恢复为TSJ_Directory中的原始预置内容

##### 用户替换预置提示词

8. WHEN 用户选择一个预置提示词并点击"替换"操作，THE Prompt_Library SHALL 提供文件上传入口或多行文本输入区域，允许用户上传或输入新的提示词内容完全替换原有预置提示词
9. WHEN 用户替换预置提示词后，THE Prompt_Library SHALL 将替换后的版本标记为"用户替换"状态，后续复核使用替换后的版本，同时保留原始预置版本供恢复

##### 用户追加补充提示词

10. WHERE 用户选择追加新的提示词，THE Prompt_Library SHALL 提供多行文本输入区域和文件上传入口，用户可以输入或上传新的提示词内容，并指定适用的会计科目分类
11. WHEN 用户追加的提示词保存成功，THE Prompt_Library SHALL 将该提示词标记为"用户追加"来源，纳入提示词列表中与预置提示词统一管理
12. WHEN 用户输入自定义提示词后，THE Review_System SHALL 提供"保存为提示词"选项，用户可以将自定义提示词保存到Prompt_Library中供后续复用

##### 提示词在复核中的使用

13. THE Review_Engine SHALL 在构建复核请求时，将用户选择的Review_Prompt（预置、用户修改版或用户追加版）注入到LLM调用的提示词中，与审计专业上下文（业务循环、准则条款、质控标准）合并构成完整的复核提示词
14. WHEN 预置提示词内容中包含{{#sys.files#}}占位符，THE Review_Engine SHALL 在复核时将该占位符替换为用户实际上传的底稿文件列表信息（包括文件名和解析状态）

##### 提示词库自动发现与同步

15. THE Prompt_Library SHALL 在系统启动时扫描TSJ_Directory，自动发现并注册所有markdown格式的提示词文件，WHEN TSJ_Directory中新增或删除markdown文件，THE Prompt_Library SHALL 在下次加载时同步更新预置提示词列表
16. WHEN TSJ_Directory中的预置提示词文件内容发生变更，THE Prompt_Library SHALL 检测到变更并更新预置提示词的默认版本，IF 用户已对该提示词进行过修改或替换，THEN THE Prompt_Library SHALL 保留用户的自定义版本并提示用户预置版本已更新

### 需求 14：提示词库Git版本管理

**用户故事：** 作为质量控制部门负责人，我希望提示词库关联到Git仓库（YZ1981-GT/GT_digao），以便实现提示词的版本管理、变更追踪和团队间同步共享。

#### 验收标准

1. THE Prompt_Library SHALL 支持关联远程Git仓库Prompt_Git_Repository（YZ1981-GT/GT_digao），用于提示词的版本管理和同步
2. WHEN 系统管理员配置Git仓库关联时，THE Review_System SHALL 提供Git仓库URL、认证凭据（SSH密钥或Token）和目标分支的配置界面
3. WHEN 用户触发"同步提示词"操作，THE Prompt_Library SHALL 从Prompt_Git_Repository拉取最新的提示词文件，并更新本地TSJ_Directory中的预置提示词内容
4. WHEN 用户对提示词进行修改、替换或追加操作后，THE Prompt_Library SHALL 支持将变更提交到Prompt_Git_Repository，提交信息包含变更类型（修改/替换/追加）、变更的提示词名称和操作用户
5. WHEN 用户查看提示词详情，THE Prompt_Library SHALL 展示该提示词的Git版本历史，包括每次变更的提交时间、提交者和变更摘要
6. IF 从Prompt_Git_Repository拉取的提示词与本地用户修改版本存在冲突，THEN THE Prompt_Library SHALL 向用户展示冲突内容的差异对比，提供"保留本地版本"、"使用远程版本"和"手动合并"三个选项
7. THE Prompt_Library SHALL 支持按Git标签（tag）管理提示词版本快照，WHEN 用户创建版本标签，THE Prompt_Library SHALL 在Prompt_Git_Repository中创建对应的Git标签
