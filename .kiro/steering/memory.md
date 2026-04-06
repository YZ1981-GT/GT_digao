---
inclusion: always
---

# 持久记忆

这是 Kiro 的自动记忆文件。每次对话开始时自动加载，提供跨会话的上下文连续性。

## 用户偏好
- 语言偏好：中文
- 部署偏好：倾向本地部署、轻量方案，避免重依赖
- TTS 声音偏好：默认声音觉得难听，需要能自选男女声/角色，且支持自录音频替代 TTS
- PPT 生成偏好：必须用 ppt-generator skill 工作流（ppt_helpers.py 命令）生成，不要手写 JSON/HTML
- PPT 内容密度偏好：每页内容不要太少，要充实
- 审计报告复核 UI 偏好：问题列表需要按附注表格+问题类别两级折叠分组，支持组头 checkbox 批量操作，避免逐条勾选
- 附注表格标题识别偏好：紧邻表格的上一行段落就是表格标题（section_title），account_name 必须通过向上回溯编号标题确定，紧邻段落不能直接当 account_name，关键词提取只作兜底
- 聊天面板尺寸偏好：默认宽度页面1/4、高度页面4/5（最小380×450），支持拖动标题栏移动位置、右下角手柄缩放大小、最大化/还原切换；输入框默认3行（minHeight 64px）
- 聊天面板全局可见偏好：💬按钮需要在所有页面（首页+四大工作模块）都显示，不能只在首页；ChatPanel 已从 renderSelectMode 提升到 App.tsx 顶层所有 return 分支
- 聊天消息操作按钮布局偏好：📋📄✏️📌等按钮不能叠在气泡内右上角（会被文字遮挡看不清），必须放在气泡外下方显示
- 聊天面板窗口控制偏好：需要支持最大化/还原切换（⊞/⊡按钮），已实现 520×720 小窗 ↔ 全屏切换
- 聊天 AI 回复排版偏好：Markdown 渲染必须有清晰层次，不能一大段纯文本；system prompt 用「## 【重要】回复格式强制要求」+禁止性措辞+示例模板强制 LLM 分段输出（温和措辞会被忽略）；CSS 中 h1/h2 加底部分隔线、段落间距 10px、列表项间距 6px

## 项目上下文

### 基础环境
- Git 远程仓库：https://github.com/YZ1981-GT/GT_digao.git，全局 HTTP/HTTPS 代理 127.0.0.1:7897
- Python 3.12 虚拟环境 (.venv)，本地已安装 Docker 28.3.3、Ollama 0.11.10
- 使用 Kiro steering + hooks 机制管理工作流
- 四大模块统一架构：四/五步工作流 + SSE 流式通信 + LLM 驱动 + Word 导出

### 项目根目录文件
- `start.bat` — 开发模式一键启动（前后端分离，后端9980+前端3030）
- `build_exe.py` — PyInstaller EXE 打包脚本（含系统托盘、自动找端口、.env 加载）
- `pack_portable.py` — 绿色便携包打包（核心 .py 编译为 .pyc 保护源码）
- `README.md` — 项目说明文档
- `LICENSE` — MIT 许可证
- `.gitignore` — Git 忽略规则

### 后端文件清单 (backend/)

#### 入口与配置
- `backend/run.py` — 启动脚本（uvicorn 启动 FastAPI）
- `backend/app/main.py` — FastAPI 应用入口，路由注册，静态文件托管，CORS
- `backend/app/config.py` — 应用配置（CORS、文件上传限制等）
- `backend/app/__init__.py`
- `backend/.env.example` — 环境变量示例
- `backend/requirements.txt` — Python 依赖清单
- `backend/pytest.ini` — 测试配置

#### 数据模型 (backend/app/models/)
- `schemas.py` — 通用数据模型（ChapterContentRequest、ChapterRevisionRequest 等）
- `audit_schemas.py` — 审计相关数据模型（ReviewReport、ReviewFinding、StatementItem、NoteTable、NoteSection、ReportReviewFinding、ReportReviewSession 等 50+ 个 Pydantic 模型）
- `analysis_schemas.py` — 文档分析数据模型（AnalysisDocumentInfo、AnalysisProject、AnalysisChapter、AnalysisMode 等）
- `chat_schemas.py` — 聊天功能数据模型（ChatMessage、ChatStreamRequest、ChatUploadResponse、SpeechToTextResponse、ExportWordRequest、NoteCreateRequest、NoteItem、NoteGroup、NotesListResponse、CleanupSuggestion、CleanupSuggestResponse、PolishRequest、KnowledgeMoveRequest）

#### 路由层 (backend/app/routers/) — 16 个路由模块
- `review.py` — 底稿复核 API（/api/review，上传/批量上传/引用检查/补充材料/SSE复核/报告导出/状态更新/交叉引用）
- `generate.py` — 文档生成 API（/api/generate，大纲提取/确认/SSE逐章节生成/单章节生成/章节修改/Word导出）
- `analysis.py` — 文档分析 API（/api/analysis，上传解析含智能OCR/格式化/项目管理/大纲生成/章节生成/Word导出）
- `report_review.py` — 审计报告复核 API（/api/report-review，1300+行，上传/解析/科目对照/SSE复核/findings CRUD/批量操作/对话/追溯/导出/模板管理）
- `config.py` — AI 配置 API（/api/config，供应商CRUD/激活）
- `prompt.py` — 提示词管理 API（/api/prompt，列表/保存/Git同步推送冲突标签）
- `template.py` — 模板管理 API（/api/template，上传/列表/详情/删除/更新）
- `knowledge.py` — 知识库 API（/api/knowledge，库列表/文档CRUD/搜索）
- `project.py` — 项目管理 API（/api/project，创建/列表/详情/底稿关联/模板关联）
- `document.py` — 文档处理 API（/api/document，上传解析/SSE分析/Word导出）
- `outline.py` — 大纲 API（/api/outline，大纲生成）
- `content.py` — 内容生成 API（/api/content，知识库预加载/SSE章节生成/SSE章节修改）
- `search.py` — 搜索 API（/api/search，网络搜索辅助）
- `expand.py` — 扩展 API（文件上传）
- `chat.py` — 聊天 API（/api/chat，流式聊天/文档上传/语音识别/Word导出/笔记CRUD/AI润色）

#### 服务层 (backend/app/services/) — 29 个服务模块

**底稿智能复核相关：**
- `workpaper_parser.py` — 底稿解析器（支持 xlsx/xls/docx/doc/pdf，Excel 合并单元格处理，Word 标题样式解析，.doc 用 pywin32 COM，PDF 多引擎，自动识别底稿编号 B/C/D-M 类）
- `review_engine.py` — 复核引擎（review_workpaper_stream SSE 逐维度 LLM 复核，_review_dimension 构建 prompt，_parse_findings 解析 JSON，classify_risk_level 风险分级，check_required_references 关联底稿检查，analyze_cross_references B/C/D-M 交叉引用，_extract_entity_name 编制单位提取）
- `prompt_library.py` — 提示词库（从 TSJ/ 加载约70个预置提示词 Markdown，支持编辑/替换/追加/恢复，{{#sys.files#}} 占位符，Git 版本管理，usage_count 统计）
- `prompt_git_service.py` — 提示词 Git 版本管理（拉取/推送/冲突处理/标签管理）
- `report_generator.py` — 复核报告生成与导出（Word: 仿宋_GB2312+Arial Narrow 排版、页边距3/3.18/3.2/2.54cm、表格上下1磅边框无左右、高风险标红、页脚页码；PDF: WeasyPrint HTML→PDF）

**审计文档生成相关：**
- `document_generator.py` — 文档生成器（1400+行，extract_template_outline 大纲提取优先 Word 标题样式+中文序号检测+过滤目录页+统一阿拉伯数字编号，_match_preset_outline 预置大纲匹配，generate_document_stream SSE 逐章节生成注入父级/同级上下文，_generate_section_content 单章节生成，revise_section_stream AI 对话修改+选中文本局部修改+多轮历史，export_to_word Word 导出）
- `template_service.py` — 模板管理（5种预置类型：审计计划/审计小结/尽调报告/审计报告/其他，上传/存储/列表/详情）
- `word_service.py` — Word 导出服务（自定义中英文字体，Markdown 渲染到 Word 含标题/列表/表格/加粗斜体）

**文档分析相关：**
- `analysis_service.py` — 文档分析服务（1200+行，generate_outline AI 生成章节框架，generate_chapter_content 逐章节生成引用原文标注出处 `<source doc="" excerpt=""/>`，revise_chapter_content AI 修改，format_document_to_markdown 大文档分块格式化，export_to_word Word 导出复用审计报告复核排版风格）
- `ocr_service.py` — OCR 服务（Tesseract 中英文，MinerU GPU 加速 PDF→Markdown 可选，smart_parse 智能策略：检测 PDF 类型→文字层直接提取→扫描版/混合 OCR→质量检测→fallback，Word/Excel 嵌入图片 OCR 补充）
- `file_service.py` — 文件服务

**审计报告复核相关：**
- `report_parser.py` — 报告解析器（2000+行，parse_report_files 解析上传文件，classify_report_file 文件分类，extract_sheets Excel 报表提取含合并报表合并/母公司列识别，_detect_header_rows 表头检测，_detect_consolidated_columns 合并列检测，_merge_header_rows 多行表头合并，extract_statement_items 科目行提取，extract_note_tables 附注表格提取，extract_note_sections 附注章节提取，_find_table_heading 表格标题回溯，_detect_note_table_headers 附注表头检测，_merge_note_header_rows 附注多行表头合并含空列继承）
- `reconciliation_engine.py` — 对账引擎（8700+行，项目最大文件，30+种数值校验：check_amount_consistency 报表vs附注金额一致性，check_note_table_integrity 附注表格内部勾稽，check_balance_formula 期初+变动=期末，check_wide_table_formula 宽表公式，check_sub_items 子项合计，check_cross_table_consistency 跨表交叉含坏账/薪酬/存货/商誉/债权投资/合同资产/收入成本，check_cashflow_supplement_consistency 现金流量表补充资料，check_income_tax_consistency 所得税，check_equity_change_vs_notes 权益变动表，check_aging_transition 账龄衔接，check_ecl_three_stage_table 预期信用损失三阶段，check_book_value_formula 账面价值，check_data_completeness 数据完整性，check_ratio_columns 比例列，check_financial_expense_detail 财务费用明细，check_benefit_plan_movement 设定受益计划变动，check_equity_subtotal_detail 权益小计明细，check_restricted_asset_disclosure 受限资产披露LLM，check_text_reasonableness 文本合理性LLM，_make_finding 统一 finding 构造含≤40字截断）
- `report_body_reviewer.py` — 正文复核（LLM 辅助：check_entity_name_consistency 单位名称一致性，check_abbreviation_consistency 简称统一性，check_template_compliance 与致同模板逐段比对）
- `note_content_reviewer.py` — 附注内容复核（LLM 辅助：extract_narrative_sections 提取叙述性章节，check_expression_quality 表达通顺性，check_policy_template_compliance 会计政策与模板比对）
- `text_quality_analyzer.py` — 文本质量检查（_check_mixed_punctuation 本地规则中英文标点混用检测含行号页码定位，analyze_punctuation LLM 标点检查，analyze_typos LLM 错别字检查）
- `table_structure_analyzer.py` — 表格结构分析器（_find_preset_for_note 预设规则匹配，try_build_formula_from_preset 预设公式构建，analyze_table_structure 规则+LLM 分析，analyze_wide_table_formula 宽表公式 LLM 分析，is_wide_table_candidate 宽表候选判断，LRU 缓存）
- `report_template_service.py` — 报告模板服务（get_template/get_template_section/get_template_toc 模板读取，update_template 更新，import_from_word Word 导入，_parse_markdown_sections Markdown 章节解析，文件存储 ~/.gt_audit_helper/report_templates/）

**共享服务：**
- `openai_service.py` — LLM 服务（多供应商适配 OpenAI 兼容 API，支持 DeepSeek/通义千问/Kimi/MiniMax/智谱GLM/Ollama，stream_chat_completion SSE 流式，模型上下文限制管理 data/model_context_limits.json）
- `knowledge_service.py` — 知识库服务（9个审计专用分类：底稿模板库/监管规定库/会计准则库/质控标准库/审计程序库/行业指引库/提示词库/报告模板库/笔记库，LRU 缓存上限300文档，文件存储 ~/.gt_audit_helper/knowledge/）
- `knowledge_retriever.py` — 知识库智能检索（按章节标题关键词匹配，分批加载，token 预算控制，configure_for_model 按模型调整预算，get_formatted_for_chapter 格式化注入 prompt）
- `knowledge_vector_service.py` — 知识库向量服务
- `search_service.py` — 网络搜索服务
- `project_service.py` — 项目管理服务（4种角色：合伙人/项目经理/审计员/质控人员，按业务循环筛选）
- `session_store.py` — 会话存储（backend/data/sessions/{session_id}/session.json + findings.json）
- `chat_service.py` — 聊天服务（ChatService：build_messages RAG注入+上下文拼接、_truncate_messages 上下文窗口截断、should_suggest_save_note 本地规则检测、MODULE_DESCRIPTIONS 模块描述注入）
- `heading_utils.py` — 标题工具函数
- `account_mapping_template.py` — 科目映射模板
- `amount_check_presets.py` — 金额检查预设规则
- `statement_preset.py` — 报表预设
- `wide_table_presets.py` — 宽表预设规则
- `docx_to_md.py`（在 utils/ 下）— Word→Markdown 转换

#### 工具层 (backend/app/utils/)
- `config_manager.py` — 运行时配置管理（AI 供应商/模型配置，存储 ~/.gt_audit_helper/config.json）
- `prompt_manager.py` — 提示词模板管理
- `outline_util.py` — 大纲处理工具（编号规范化、层级调整）
- `json_util.py` — JSON 解析工具（容错解析 LLM 返回的 JSON）
- `docx_to_md.py` — Word→Markdown 转换
- `sse.py` — SSE 流式响应工具（sse_response、sse_with_heartbeat）

#### 测试 (backend/tests/) — 22 个测试文件
- `test_report_parser.py`、`test_report_review_engine.py`、`test_report_review_router.py`、`test_audit_report_review_models.py` — 审计报告复核测试
- `test_reconciliation_engine.py`、`test_change_threshold.py`、`test_gap_checks.py`、`test_new_checks.py`、`test_new_improvements.py`、`test_three_new_checks.py` — 对账引擎测试
- `test_note_table_headers.py`、`test_parent_scope.py`、`test_soe_column_swap.py`、`test_soe_income_statement.py` — 报表解析测试
- `test_table_structure_analyzer.py`、`test_wide_table_formula.py` — 表格结构测试
- `test_heading_utils.py`、`test_backend_services.py`、`test_template_structure_diff.py`、`test_template_type_presets.py` — 其他测试
- `_debug_formula.py` — 调试脚本

#### 数据目录
- `backend/data/model_context_limits.json` — 各模型上下文长度限制配置
- `backend/data/sessions/` — 审计报告复核会话数据（72个会话目录，每个含 session.json + findings.json）

### 前端文件清单 (frontend/src/)

#### 入口
- `App.tsx` — 主应用（工作模式路由：底稿复核/文档生成/文档分析/审计报告复核）
- `index.tsx` — React 入口

#### 组件 (frontend/src/components/) — 44 个组件

**工作模式选择：**
- `WorkModeSelector.tsx` — 工作模式选择首页（四大模式入口）
- `ConfigPanel.tsx` — AI 配置面板（供应商/模型/API Key 配置）
- `ModelSelector.tsx` — 模型选择器（章节编辑器内置）
- `StepBar.tsx` — 步骤指示器通用组件

**底稿智能复核（四步）：**
- `ReviewWorkflow.tsx` — 复核工作流容器（步骤管理、SSE 事件处理、IndexedDB 状态恢复）
- `WorkpaperUpload.tsx` — 底稿上传（单文件/批量，格式校验）
- `PromptSelector.tsx` — 提示词选择（从 TSJ 加载，按科目分类筛选）
- `ReviewDimensionConfig.tsx` — 维度配置（5个标准维度 + 自定义维度）
- `SupplementaryUpload.tsx` — 补充材料上传（文件或文本）
- `ReviewConfirmation.tsx` — 复核确认（参数汇总、启动复核）
- `ReviewReport.tsx` — 复核报告展示（结构化报告、风险统计）
- `CrossReferenceGraph.tsx` — 交叉引用关系图

**审计文档生成（四步）：**
- `GenerateWorkflow.tsx` — 文档生成工作流容器
- `TemplateSelector.tsx` — 模板上传与配置（模板类型选择、项目信息、知识库关联）
- `TemplateOutlineEditor.tsx` — 大纲可视化编辑（增删改、调整层级和顺序）
- `DocumentEditor.tsx` — 文档编辑器（三种生成模式：批量3并发/逐章节/停止）
- `SectionEditor.tsx` — 章节编辑器（手动编辑、AI 对话修改、选中文本局部修改+高亮、内置模型选择器）
- `ExportPanel.tsx` — 导出面板（Word 导出、字体设置）
- `FontSettings.tsx` — 字体设置组件

**文档分析（四步）：**
- `AnalysisWorkflow.tsx` — 文档分析工作流容器（多文档上传、三种分析模式、章节框架、逐章节生成、出处标注悬停预览）

**审计报告复核（五步）：**
- `AuditReportWorkflow.tsx` — 审计报告复核工作流容器
- `AuditReportUpload.tsx` — 报告上传（Word 报告 + Excel 报表，模板类型选择 soe/listed）
- `AccountMatchingView.tsx` — 科目对照确认（报表科目与附注表格自动匹配）
- `AuditReportConfig.tsx` — 复核配置
- `FindingConfirmationView.tsx` — 问题确认（两级折叠分组 account_name→category，组头 checkbox 含 indeterminate 半选态，批量确认/驳回）
- `FindingDetailPanel.tsx` — 问题详情面板
- `AuditReportResult.tsx` — 复核报告展示与导出
- `SourceDocPreview.tsx` — 源文档预览
- `TemplateEditorView.tsx` — 模板编辑视图

**知识库与项目：**
- `KnowledgePanel.tsx` — 知识库面板（7个分类、文档管理）
- `KnowledgeSearchPanel.tsx` — 知识库搜索面板
- `ProjectPanel.tsx` — 项目管理面板
- `WebSearchPanel.tsx` — 网络搜索面板

**首页聊天（新增）：**
- `ChatPanel.tsx` — 聊天面板主组件（可折叠、SSE流式对话、IndexedDB持久化、文件/图片上传、笔记保存）
- `ChatMessageList.tsx` — 消息列表（Markdown渲染、图片预览、知识库引用标签、笔记保存按钮、建议保存提示）
- `ChatInput.tsx` — 输入区域（@知识库触发、/快捷指令、📎上传、🎤语音、Ctrl+V粘贴图片、拖拽上传）
- `KnowledgePopup.tsx` — 知识库候选列表弹窗（forwardRef+useImperativeHandle键盘导航）
- `CommandPopup.tsx` — 快捷指令候选列表弹窗（同上模式）
- `NotesSidebar.tsx` — 笔记侧边栏（按日期分组、展开/收起、预览、删除确认、移动/复制操作）
- `ChatExportPanel.tsx` — 聊天导出预览编辑面板（Markdown编辑、AI润色SSE流式、导出Word、在线编辑）
- `ChatWelcome.tsx` — 欢迎引导组件（2x2模块卡片网格、使用提示）
- `DocumentEditorModal.tsx` — 文档在线编辑模态框（三模式：👁预览、✏️左右分栏编辑+实时预览、✨AI润色；🔄同步编辑内容回对话消息、📌转存笔记、⬇下载Word用编辑后内容重新生成）
- `LibraryTargetSelector.tsx` — 目标知识库选择器弹窗（移动/复制文档时选择目标库+笔记库日期子文件夹）

#### 页面 (frontend/src/pages/)
- `DocumentAnalysis.tsx` — 文档分析页
- `OutlineEdit.tsx` — 大纲编辑页
- `ContentEdit.tsx` — 内容编辑页

#### 服务与工具
- `services/api.ts` — API 封装（reviewApi/generateApi/analysisApi/reportReviewApi/configApi/promptApi/templateApi/knowledgeApi/projectApi/chatApi）
- `hooks/useAppState.ts` — 全局状态管理
- `utils/auditStorage.ts` — IndexedDB 缓存（审计工作状态持久化）
- `utils/draftStorage.ts` — 草稿存储
- `utils/sseParser.ts` — SSE 流解析（processSSEStream）
- `utils/chatStorage.ts` — 聊天会话 IndexedDB 持久化（chat_current + chat_archive 两个 store）
- `utils/markdownToHtml.ts` — Markdown→HTML 转换（unified pipeline，供富文本复制使用）
- `utils/copyRichText.ts` — 富文本复制（ClipboardItem text/html + text/plain，回退纯文本）
- `types/audit.ts` — 审计相关 TypeScript 类型定义
- `types/analysis.ts` — 文档分析 TypeScript 类型定义
- `types/index.ts` — 类型导出
- `types/chat.ts` — 聊天类型定义（ChatMessage、ChatAttachment、ChatSession、KnowledgeRef、QuickCommand、QUICK_COMMANDS、NoteItem、NoteGroup）
- `styles/gt-design-tokens.css` — GT 设计系统 Token（主色 #4b2d77、辅助色、间距、圆角等）

### 资源目录
- `TSJ/` — 预置提示词库（约70个 Markdown 文件，按会计科目分类：货币资金/应收账款/存货/固定资产/无形资产/长期股权投资/短期借款/长期借款/应付账款/应付职工薪酬/应交税费/收入/成本/费用等）
- `GT_底稿/` — 审计底稿模板（D销售循环~M权益循环+Q关联方循环，致同底稿模板，审计实务操作手册.html，审计实务操作手册-框架.md，致同GT审计手册设计规范.md）
- `MinerU/` — MinerU PDF 解析工具（web_ui.py Web 界面，fix_md_tables.py 表格修复脚本，启动Web界面.bat）

## 技术决策
- AI 记忆方案：放弃 mem0 本地部署（太重6GB+），改用 Kiro 原生 steering + hook 轻量方案
- 记忆系统架构：memory.md (always steering) + auto-save-memory hook (agentStop 触发自动保存)
- UTF-8 BOM 防御：所有 Python 脚本读取 JSON/HTML 文件统一用 `utf-8-sig` 编码
- Word 导出统一排版规范：仿宋_GB2312+Arial Narrow、页边距3/3.18/3.2/2.54cm、表格上下1磅边框无左右、高风险标红、页脚页码
- 底稿复核编制单位提取：ReviewEngine._extract_entity_name() 从 content_text 前2000字符正则匹配
- account_name 长度防御：三层修复（report_parser 回溯增强+后端≤40字截断+前端≤30字截断），核心 _fix_note_table_account_names() 用层级树修正
- 多行表头合并单元格空列继承：_merge_note_header_rows 和 _extract_from_total_row 的 first_row_h 均需对第一行做空列继承
- check_data_completeness 小计行误报修复：_is_total_row 新增 _summary_label_kw 列表，跳过「减：坏账准备」「账龄一年以内/以上的…」「其中：」「加：」等分类汇总行，这些行不是明细行不适用"期末有数但文本列为空"的完整性规则
- 母公司vs合并口径误报修复：① PARENT_COMPANY_NOTE_KEYWORDS 扩展6个变体提高 ancestor_map 识别率 ② 母公司补充校验逻辑从「主动报错」改为「被动确认」——只确认母公司口径是否有匹配，不再用母公司余额去比对合并附注生成 finding，避免母公司报表数被错误匹配到合并附注表格做校对
- 带括号编号子项分组标题识别：table_structure_analyzer._analyze_with_rules 新增第四遍检测，当连续2+个「（1）（2）」编号行前面有非编号 data 行时，将其标记为 subtotal
- 中文序号段落标题识别放宽：第三遍条件从「有中文序号+有编号子项+有合计行」改为「有中文序号+有合计行」即可标记为 subtotal，解决长期股权投资明细表中「一、子公司/二、合营企业/三、联营企业」未被识别为 subtotal 的问题
- _get_data_rows_for_total subtotal覆盖方向修复：判断标准模式vs段落标题模式时，增加检测 subtotal 后面是否紧跟带括号编号行，如果是则强制为段落标题模式（subtotal覆盖后面的编号子项），避免前面的独立行被错误覆盖
- subtotal纵向校验：check_note_table_integrity 新增 subtotal 子项求和校验（如「按组合计提」=（1）+（2）+...），仅对 _SUBTOTAL_VERIFY_ACCOUNTS（其他应收款/应收账款/应收票据）生效，风险等级 LOW
- 发放贷款及垫款专项校验：新增 check_loan_and_advance 函数（reconciliation_engine.py），含4项校验：①报表数vs附注最终账面价值行（从最后一行往前找）②表内计算（总额+应计利息-损失准备=中间账面价值）③表内计算（中间账面价值-一年内到期-应收利息=最终账面价值）④多表交叉（各子表贷款总额一致性）；SKIP_INTEGRITY_KEYWORDS 加入「发放贷款」「贷款和垫款」跳过通用纵向校验；amount_check_presets 新增发放贷款白名单规则；report_review_engine 中调用
- 应收股利专项校验：新增 check_dividend_receivable 函数，含4项校验：①账龄一年以内=明细行之和 ②账龄一年以上=明细行之和 ③小计=一年以内+一年以上 ④合计=小计-坏账准备；SKIP_INTEGRITY_KEYWORDS 加入「应收股利」；report_review_engine 中调用
- 跨表交叉校验口径分离：check_cross_table_consistency 新增 note_sections 参数，分组时用 _is_parent_company_note 区分合并/母公司口径（key 加 ::parent 后缀），避免合并总表和母公司变动表/分类表混在一起做交叉比对；check_impairment_loss_consistency 新增 _parent_note_ids 过滤，_is_movement_table/_is_provision_balance_table 中排除母公司附注，避免母公司坏账准备变动表被算入合并口径的信用/资产减值损失交叉核对；check_equity_method_income_consistency 新增 note_sections 参数+ancestor_map，_is_parent_company_note 传入 ancestor_titles 正确识别母公司长期股权投资明细表并跳过
- _check_asset_summary_cross 子集表格排除：识别明细表时跳过「暂时闲置」「未办妥」「抵押」「出租」「担保」等标题的表格，避免固定资产的子集表格被误识别为完整明细表参与汇总表vs明细表交叉比对
- 续表处理改进：_check_bad_debt_cross 和 _check_asset_summary_cross 中续表不参与表格类型识别，但记录到 continuation_tables，遍历所有续表分别提取期末/期初的坏账准备和账面余额补充首表缺失值（支持宽表拆分：首表有期初末表有期末，或首表有期末续表有期初）
- 在建工程减值准备交叉比对排除「本期计提」：_check_asset_summary_cross 识别 impairment_movement_table 时排除标题含「本期计提」「计提情况」的表格，这些只有当期计提金额不是变动表
- _is_total_row 非合计行排除：table_structure_analyzer._is_total_row 新增 _not_total_labels 列表（工资总额/薪金总额/薪酬总额），这些是薪酬类别名称不是合计行，避免长期应付职工薪酬表中「工资总额」被误判为 total 导致纵向校验误报
- 金融机构特有科目跳过纵向校验：SKIP_INTEGRITY_KEYWORDS 加入「吸收同业及存放」「拆入资金」「卖出回购」「买入返售」「财务费用」
- 财务费用专项校验重写：check_financial_expense_detail 含 F64-3（利息费用-资本化=净额）和 F64-4（合计=顶层行求和）；行识别支持「利息费用/利息支出」「手续费及其他」等变体；有净额时合计=净额-利息收入+汇兑+其他（净额只扣资本化不含利息收入）；每行可选兼容用户删减
- SKIP_INTEGRITY_KEYWORDS 完整列表：主要财务信息/重要合营联营企业/作为承租人/处于第/分部利润/政府补助/发放贷款/贷款和垫款/应收股利/吸收同业及存放/拆入资金/卖出回购/买入返售/财务费用/其他综合收益各项目/长期应付职工薪酬（未加入，通过修复_is_total_row解决）
- 合计行后「其中」行处理（仅其他收益）：_analyze_with_rules 第二遍中，仅对「其他收益」表格，当「其中」行在最后一个 total 行之后时，标记为 sub_item 但不设 parent、不向后扫描，避免「其中：政府补助」被错误关联到前面的 data 行
- 三阶段ECL表纵向校验修复：_check_ecl_column_movement 区分阶段间转移行（转入第X/转回第X，数值已带正负号直接累加）和普通减项行（本期转回/转销/核销，需取反）；「其他变动」行双向校验（加法和减法都试，有一种匹配就通过，都不匹配按减法差异输出）
- 科目匹配关键词精确化：account_mapping_template 和 amount_check_presets 中「所得税费用」的关键词从 ['所得税费用','所得税'] 改为 ['所得税费用']，避免宽泛的「所得税」匹配到「递延所得税资产/负债」表格导致真正的所得税费用表格被遗漏
- 其他权益工具/优先股/永续债匹配修复：account_mapping_template 主映射表新增「优先股」「永续债」作为独立 key（关键词分别含'其他权益工具'+'优先股'/'永续债'），使 get_keywords 能找到它们走模板映射而非模糊匹配，正确匹配到「优先股、永续债等金融工具」附注表格，不再误匹配到「其他权益工具投资」（资产类）
- check_sub_item_detail 匹配优先级：查找附注表格时优先使用子项自身在 matching_map 中的直接匹配（sub.id），无则回退到父科目匹配（parent_id）；新增 _skip_sub_item_kw 排除「优先股」「永续债」不参与二级明细比对（它们是独立权益科目，由 check_amount_consistency 处理）
- FindingDetailPanel「数据下载」按钮：原「数据下钻」改为数据下载功能，点击后生成当前 finding 的详细计算过程文本（含科目/描述/分析过程/数值明细/关联附注表格数据/建议），优先复制到剪贴板，失败则下载为 txt 文件
- 其他综合收益列匹配修复：check_oci_vs_income_statement 优先匹配「税后净额」列（利润表OCI是税后净额），跳过「税前金额」列，三级优先级（税后净额→本期金额排除税前→任何税后净额列）
- 母公司口径白名单：should_verify_note_table 新增 is_parent_note 参数，check_amount_consistency 调整为先判断口径再做白名单过滤；母公司口径的子表（对子公司/对联营/对合营）仍然被排除不参与余额校对（因为子表只是明细不是汇总，单独比对会产生误报），_parent_skip_exclude_kw 预留为空列表供未来扩展
- 前端 tsconfig 不支持 Map 迭代需用 Record 代替
- 表头标准化换行符修复：reconciliation_engine.py 中12处表头标准化统一加上 .replace("\n","").replace("\r","")，解决多行表头合并后含换行符（如「账面\n价值」）导致关键词匹配失败的问题
- 单行其中项识别：table_structure_analyzer 第二遍扫描增加检测，仅对 _SINGLE_LINE_SUB_ITEM_ACCOUNTS（当前仅含"长期应收款"）生效，当「其中：XXX」后面有具体内容（非编号）且该行有数值时不向后扫描子项，避免后续独立行被错误标记为 sub_item
- 附注表格数据全空时抑制「未提取到附注合计值」警告：check_amount_consistency 在生成 NOTE_VALUE_NOT_FOUND_TAG finding 前检查所有匹配表格的数据行是否全为空（_safe_float 均为 None），全空时跳过不报（附注本身没填数值不是结构识别问题）
- 续表期末/期初值提取修复：_extract_from_total_row 的 _is_closing_group/_is_opening_group 增加 is_move 排除变动列（本期增加/本期减少），bv_cols 回退分配时剩余变动列不分配给 opening/closing，解决续表结构（如其他权益工具期初期末分两个表格）中变动列值被错误提取为期末/期初的问题
- PowerShell 5.x 编码陷阱：Python 写给 PS5 的 .ps1 必须用 utf-8-sig（带 BOM）
- 复核流错误信息增强：report_review.py 错误捕获现在输出最内层文件名+行号到前端；report_review_engine.py 第一轮本地校验循环加 try-except 打印 note_id/account_name/section_title 到后端日志，方便定位 NoneType.__format__ 等运行时异常
- NoneType.__format__ 防御：report_review_engine.py 中 _check_preset_missing 和变动分析的 f-string 格式化已加 None 防御（closing_balance/opening_balance/change_amount）
- 预付账款等无"账面价值"列的科目：_extract_from_total_row 的 closing_cols 分支和 _pick_from_range 分支增加"账面余额 - 坏账准备 = 净值"计算逻辑，优先取账面价值列→次选计算净值→回退第一列
- 财务费用F64-4增强：无净额时利息资本化作为减项；增加银行手续费/贴现利息/融资费用/租赁负债利息行识别；兜底策略把所有未识别行加入求和（识别"减："前缀作为减项），全量一致则不报错
- _extract_from_total_row 优先列扩展：bv_cols/_pick_from_range/_pick_net_or_first/单行表头 closing_bv_idx 均增加"税后净额"/"税后"关键词与"账面价值"同等优先，解决其他综合收益明细表取到税前金额而非税后净额的问题（国企版）
- gitpython 崩溃防御：prompt_git_service.py 在 import git 前设置 GIT_PYTHON_REFRESH=quiet，__init__ 中用 shutil.which("git") 检测可用性，_ensure_configured 返回友好提示；build_exe.py launcher 中同样设置该环境变量
- EXE 打包使用期限：build_exe.py launcher main() 最前面加过期检查，当前设为 2026-09-30，过期后弹 MessageBoxW 提示联系致同研究院获取新版本后 sys.exit(1)
- 笔记库架构：在 knowledge_service.py LIBRARIES 中新增 'notes' 分类，与现有8个知识库并列管理，复用知识库全套 CRUD/搜索/RAG 检索能力，聊天中的 AI 回复、上传文档、整段对话均可保存为笔记，笔记可被其他四大工作模块关联使用；笔记按日期子文件夹管理（`~/.gt_audit_helper/knowledge/notes/{YYYY-MM-DD}/`），侧边栏按日期分组展示
- 聊天框特殊字符交互模式：`/` 触发快捷指令跳转工作模块，`@` 触发知识库引用（弹出候选列表，支持模糊过滤，选中显示为标签），不带 `@` 的消息不走知识库检索
- 聊天 Markdown 渲染依赖：前端需新增 react-markdown + remark-gfm + rehype-highlight + unified + remark-parse + remark-rehype + rehype-stringify（后四个用于富文本复制时 Markdown→HTML 转换）；@ranui/preview 已弃用，改用 iframe + markdownToHtml 方案做在线预览
- 富文本复制内联样式：markdownToHtml.ts 中自定义 rehypeInlineStyles 插件，给 table/th/td/blockquote/pre/code/h1-h3/hr 注入内联 style 属性，确保剪贴板 HTML 不依赖外部 CSS，粘贴到 Word/邮件/飞书等任何富文本环境都能正确显示格式

## 待办 / 进行中
- 项目文件清理（2026-04）：已删除根目录 `__pycache__/`、`frontend/README.md`；`GT_底稿/审计实务操作手册-框架.md` 和 `致同GT审计手册设计规范.md` 待用户确认是否删除
- 用户计划对每个细分程序逐一打磨升级
- 首页聊天功能（全部60个子任务已完成）：spec 路径 .kiro/specs/homepage-chat/，待用户启动测试验收；复盘发现的优化点：①ChatPanel.tsx 超1000行，后续可拆分清理UI/导出逻辑为独立hook ②IndexedDB saveChatSession 流式输出时高频写入，可加debounce ③Whisper API 依赖供应商支持，不支持时需友好提示
- 在线文档编辑（第一步已完成）：homepage-chat 中已改用 iframe + markdownToHtml 方案（弃用 @ranui/preview，Web Component 加载不稳定且预览空白）；第二步单独开 spec 改造四大工作模块的导出流程
