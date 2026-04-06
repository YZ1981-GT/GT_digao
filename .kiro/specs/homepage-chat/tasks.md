# 任务清单：首页聊天功能

## 1. 后端基础设施

- [x] 1.1 创建 `backend/app/models/chat_schemas.py`，定义所有 Pydantic 模型（ChatMessage、ChatStreamRequest、ChatUploadResponse、SpeechToTextResponse、ExportWordRequest、NoteCreateRequest、NoteItem、NoteGroup、NotesListResponse、CleanupSuggestion、CleanupSuggestResponse、PolishRequest、KnowledgeMoveRequest）
- [x] 1.2 创建 `backend/app/services/chat_service.py`，实现 ChatService 类骨架（__init__、build_messages 框架、_truncate_messages、should_suggest_save_note、MODULE_DESCRIPTIONS 常量）
- [x] 1.3 创建 `backend/app/routers/chat.py`，注册 `/api/chat` 前缀路由，实现 POST `/api/chat/stream` 端点（调用 ChatService.build_messages → OpenAI_Service.stream_chat_completion → sse_with_heartbeat 包装，流结束后发送 meta 数据行）
- [x] 1.4 在 `backend/app/main.py` 中导入并注册 chat.router（在 report_review.router 之后）
- [x] 1.5 在 `backend/app/services/knowledge_service.py` 的 LIBRARIES 字典中新增 `'notes'` 分类（笔记库）

## 2. 前端基础设施

- [x] 2.1 安装前端新依赖：`react-markdown`、`remark-gfm`、`rehype-highlight`、`unified`、`remark-parse`、`remark-rehype`、`rehype-stringify`
- [x] 2.2 创建 `frontend/src/types/chat.ts`，定义 TypeScript 类型（ChatMessage、ChatAttachment、ChatSession、KnowledgeRef、QuickCommand、QUICK_COMMANDS、NoteItem、NoteGroup）
- [x] 2.3 创建 `frontend/src/utils/chatStorage.ts`，实现 IndexedDB 持久化（chat_current + chat_archive 两个 object store，saveChatSession、loadChatSession、archiveChatSession）
- [x] 2.4 在 `frontend/src/services/api.ts` 中新增 chatApi 模块（stream、upload、speechToText、exportWord、notes CRUD、polish、knowledge move/copy）
- [x] 2.5 创建 `frontend/src/utils/markdownToHtml.ts`，实现 Markdown→HTML 转换工具函数（unified + remark-parse + remark-gfm + remark-rehype + rehype-stringify），供富文本复制使用
- [x] 2.6 创建 `frontend/src/utils/copyRichText.ts`，实现富文本复制函数（ClipboardItem 同时写入 text/html + text/plain，回退纯文本）

## 3. 核心聊天功能（需求 1、2、5、6）

- [x] 3.1 创建 `frontend/src/components/ChatPanel.tsx` 主组件骨架（可折叠面板、状态管理：messages、isStreaming、abortController、chatOpen）
- [x] 3.2 实现 ChatPanel 的 SSE 流式对话（fetch + processSSEStream + AbortController 中断，发送时按钮变停止，流结束解析 meta 数据行）
- [x] 3.3 创建 `ChatMessageList.tsx`（消息列表渲染：用户消息右对齐、AI 消息左对齐 + react-markdown 渲染、自动滚动到底部）
- [x] 3.4 创建 `ChatInput.tsx` 骨架（输入框 + 发送/停止按钮 + Enter 发送）
- [x] 3.5 在 `App.tsx` 的 renderSelectMode 中集成 ChatPanel（传入 onSelectMode 回调），在 WorkModeSelector 首页右下角渲染
- [x] 3.6 实现多轮对话（前端维护 messages 数组，发送时传完整历史，后端 _truncate_messages 截断）
- [x] 3.7 实现 IndexedDB 持久化（消息变化时 saveChatSession，组件初始化时 loadChatSession 恢复）
- [x] 3.8 实现新建对话（archiveChatSession 归档当前会话，清空 messages）
- [x] 3.9 ChatPanel 顶部显示当前模型名称（调用 /api/config/active 获取）
- [x] 3.10 GT Design System 样式适配（主色、圆角、间距、字体、气泡颜色等按设计文档规范）

## 4. @ 知识库 RAG 检索（需求 3）

- [x] 4.1 在 ChatInput 中实现 @ 触发逻辑（检测 @ 字符，提取过滤关键词，弹出 KnowledgePopup 候选列表）
- [x] 4.2 实现 KnowledgePopup 组件（从 /api/knowledge/libraries 获取分类列表，模糊过滤，键盘上下导航 + Enter 选择）
- [x] 4.3 实现知识库标签 Tag 样式（选中后在输入框中显示带背景色的标签，可点击移除，记录 libraryId）
- [x] 4.4 发送消息时解析 @ 标签，提取 knowledge_library_ids 传入 /api/chat/stream 请求
- [x] 4.5 在 ChatService.build_messages 中填充 RAG 注入逻辑（根据 knowledge_library_ids 调用 knowledge_service.search_knowledge，结果注入 system prompt）
- [x] 4.6 前端解析 meta.knowledge_refs，在 AI 回复下方渲染"已参考：@XX库"标识

## 5. / 快捷指令（需求 4）

- [x] 5.1 在 ChatInput 中实现 / 触发逻辑（输入框为空或行首输入 / 时弹出 CommandPopup）
- [x] 5.2 实现 CommandPopup 组件（显示 QUICK_COMMANDS 列表，键盘导航 + Enter 选择，选中后调用 onSelectMode 跳转）

## 6. 文档上传（需求 9）

- [x] 6.1 后端实现 POST /api/chat/upload 端点（接收 multipart/form-data，限制 20MB，调用 ocr_service.smart_parse / docx_to_md / openpyxl 提取文本，返回 ChatUploadResponse）
- [x] 6.2 在 ChatInput 中实现 📎 上传按钮（点击选择文件，支持 PDF/Word/Excel/CSV/TXT/Markdown/图片格式）
- [x] 6.3 实现拖拽上传（ChatInput 区域 onDragOver + onDrop）
- [x] 6.4 上传后在对话区域显示文件卡片（文件名、大小、移除按钮、保存到笔记按钮）
- [x] 6.5 上传文档的文本内容存入 document_context 状态，发送消息时传入 /api/chat/stream

## 7. 截图上传与 OCR（需求 13）

- [x] 7.1 在 ChatInput 中实现 Ctrl+V 粘贴图片（onPaste 检测 image/* 类型，提取 Blob 生成缩略图 data URL）
- [x] 7.2 实现图片缩略图预览区（输入框上方，最多 5 张，可点击移除）
- [x] 7.3 发送时循环调用 /api/chat/upload 上传图片，合并 OCR 结果为 image_ocr_context
- [x] 7.4 对话区域中展示用户发送的图片（缩略图 300px，点击弹出全屏预览模态框）
- [x] 7.5 AI 回复中标注"已识别图片内容"标签

## 8. 语音输入（需求 10）

- [x] 8.1 后端实现 POST /api/chat/speech-to-text 端点（接收 audio multipart，调用 Whisper API 语音识别，返回 SpeechToTextResponse）
- [x] 8.2 在 ChatInput 中实现 🎤 语音按钮（检测 MediaRecorder 支持，不支持则隐藏）
- [x] 8.3 实现录音逻辑（getUserMedia → MediaRecorder → ondataavailable 收集 chunks → stop 合并 Blob）
- [x] 8.4 实现录音状态 UI（红色脉冲动画、录音时长计时器、120 秒超时自动停止）
- [x] 8.5 录音结束后调用 /api/chat/speech-to-text，识别结果填入输入框

## 9. 笔记功能（需求 11）

- [x] 9.1 后端 Knowledge_Service 扩展：实现 add_note 方法（按日期子文件夹保存，index.json 增加 date_folder 字段）
- [x] 9.2 后端 Knowledge_Service 扩展：实现 get_notes_grouped 方法（按日期分组返回笔记列表）
- [x] 9.3 后端实现 POST /api/chat/notes 端点（保存笔记）
- [x] 9.4 后端实现 GET /api/chat/notes 端点（获取笔记列表按日期分组）
- [x] 9.5 后端实现 DELETE /api/chat/notes/{doc_id} 端点（删除笔记）
- [x] 9.6 在 AssistantMessage 上实现 📌 保存到笔记按钮（单条 AI 回复保存，含用户提问作为标题）
- [x] 9.7 实现整段对话一键保存为笔记（"对话摘要 - 日期时间"为标题）
- [x] 9.8 创建 `NotesSidebar.tsx`（可展开/收起，按日期分组列表，默认展开最近 3 天，点击预览，删除确认）
- [x] 9.9 后端 ChatService 实现 should_suggest_save_note 本地规则检测，流结束后在 meta 中返回 suggest_save_note 标记
- [x] 9.10 前端解析 meta.suggest_save_note，在 AI 回复末尾显示"建议保存到笔记"提示标签

## 10. 笔记智能清理（需求 11.13-11.15）

- [x] 10.1 后端实现 POST /api/chat/notes/cleanup-suggest 端点（检查笔记数量/大小阈值，调用 LLM 分析生成清理建议）
- [x] 10.2 前端 ChatPanel 初始化时检查笔记库大小，超阈值显示清理提示
- [x] 10.3 实现清理建议列表 UI（创建时间、最后 RAG 引用时间、删除原因，逐条确认或批量删除）

## 11. 对话复制与导出（需求 12）

- [x] 11.1 在 AssistantMessage 上实现 📋 复制按钮（调用 copyRichText 富文本复制，显示"已复制"提示）
- [x] 11.2 在 AssistantMessage 上实现 📄 单条导出 Word 按钮（调用 /api/chat/export-word）
- [x] 11.3 后端实现 POST /api/chat/export-word 端点（调用 word_service 将 Markdown 渲染为 Word，返回文件流）
- [x] 11.4 实现多选导出模式（对话顶部"导出"按钮 → exportMode → checkbox → 全选/仅选 AI 快捷按钮）
- [x] 11.5 创建 `ExportPanel.tsx`（导出预览编辑面板：合并选中消息为 Markdown，支持手动编辑）
- [x] 11.6 后端实现 POST /api/chat/polish 端点（SSE 流式 AI 润色）
- [x] 11.7 ExportPanel 中实现"AI 润色"按钮（调用 /api/chat/polish，润色结果替换编辑区内容）
- [x] 11.8 ExportPanel 中实现"导出 Word"按钮（将编辑后内容调用 /api/chat/export-word 下载）

## 11b. 在线编辑器集成（需求 12.15-12.18）

- [x] 11b.1 安装前端依赖 `@ranui/preview`（ranuts/document 纯前端 OnlyOffice 编辑器）
- [x] 11b.2 创建 `DocumentEditorModal.tsx`（全屏模态框，嵌入 ranuts/document 编辑器，接收 Word Blob，提供下载和关闭按钮）
- [x] 11b.3 在 AssistantMessage 的单条导出中增加"在线编辑"按钮（调用 /api/chat/export-word 获取 Blob → 打开 DocumentEditorModal）
- [x] 11b.4 在 ExportPanel 中增加"在线编辑"按钮（将编辑后内容生成 Word Blob → 打开 DocumentEditorModal）

## 12. 欢迎引导与模块推荐（需求 14）

- [x] 12.1 创建 `ChatWelcome.tsx`（欢迎消息 + 四大模块快捷入口卡片 2x2 网格 + 使用提示文字）
- [x] 12.2 ChatPanel 在空对话或新建对话时渲染 ChatWelcome
- [x] 12.3 后端 ChatService 的 MODULE_DESCRIPTIONS 注入 system prompt，使 LLM 了解可用模块
- [x] 12.4 前端解析 AI 回复中的 `[推荐模块:xxx]` 标记，渲染为可点击的模块跳转按钮

## 13. 知识库文档移动复制（需求 15）

- [x] 13.1 后端 Knowledge_Service 扩展：实现 move_documents 方法（跨库移动，笔记库日期子文件夹处理，同名追加序号）
- [x] 13.2 后端 Knowledge_Service 扩展：实现 copy_documents 方法（跨库复制，规则同 move）
- [x] 13.3 后端实现 POST /api/knowledge/move 端点
- [x] 13.4 后端实现 POST /api/knowledge/copy 端点
- [x] 13.5 在 KnowledgePanel 和 NotesSidebar 中实现右键菜单/操作按钮（移动到.../复制到...）
- [x] 13.6 实现目标选择器弹窗（列出所有知识库分类 + 笔记库日期文件夹）
- [x] 13.7 实现多选批量移动/复制（checkbox 多选 + 批量操作按钮）
- [x] 13.8 笔记侧边栏支持整个日期文件夹的移动/复制操作
