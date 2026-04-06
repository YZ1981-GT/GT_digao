# 需求文档：首页聊天功能

## 简介

在致同AI审计助手首页（WorkModeSelector）增加一个 AI 聊天面板，作为日常工作的对话界面。聊天功能复用已有的 openai_service SSE 流式对话和 knowledge_service RAG 知识库检索，支持快捷指令联动四大工作模块，并可在对话中调用知识库中保存的信息辅助回答。

## 术语表

- **Chat_Panel**：首页聊天面板前端组件（ChatPanel.tsx），嵌入 WorkModeSelector 页面
- **Chat_Router**：后端聊天路由模块（chat.py），提供 /api/chat 下的 API 端点
- **Chat_Service**：后端聊天服务，负责会话管理、消息处理、知识库检索注入和 LLM 调用
- **Knowledge_Service**：已有的知识库管理服务（knowledge_service.py），管理8个审计专用知识库
- **Knowledge_Retriever**：已有的知识库智能检索服务（knowledge_retriever.py），按关键词匹配和 token 预算控制注入上下文
- **OpenAI_Service**：已有的 LLM 服务（openai_service.py），支持多供应商 SSE 流式对话
- **SSE_Parser**：已有的前端 SSE 流解析工具（sseParser.ts）
- **Config_Manager**：已有的运行时配置管理（config_manager.py），管理 AI 供应商和模型配置
- **Quick_Command**：快捷指令，以斜杠开头的特殊命令（如 /复核、/生成），用于从聊天界面快速跳转到对应工作模块
- **Chat_Session**：一次聊天会话，包含完整的多轮对话历史
- **OCR_Service**：已有的 OCR 服务（ocr_service.py），支持 PDF/Word/Excel 文档文本提取
- **Whisper_API**：OpenAI 兼容的语音识别接口，用于将语音音频转换为文本
- **Notes_Library**：知识库下新增的"笔记库"分类（notes），用于保存聊天中上传的文档内容、对话记录摘要等用户笔记，可被 RAG 检索并联动其他工作模块

## 需求

### 需求 1：聊天消息发送与流式响应

**用户故事：** 作为审计项目组成员，我想在首页通过聊天框向 AI 提问，以便快速获得审计相关问题的解答。

#### 验收标准

1. WHEN 用户在 Chat_Panel 输入框中输入消息并点击发送按钮或按下 Enter 键，THE Chat_Panel SHALL 将消息发送至 Chat_Router 的 /api/chat/stream 端点
2. WHEN Chat_Router 收到聊天请求，THE Chat_Service SHALL 调用 OpenAI_Service 的 stream_chat_completion 方法，以 SSE 流式方式返回 AI 响应
3. WHILE Chat_Router 正在流式返回响应，THE Chat_Panel SHALL 使用 SSE_Parser 逐字实时渲染 AI 回复内容
4. WHILE Chat_Router 正在流式返回响应，THE Chat_Panel SHALL 将发送按钮替换为"停止"按钮（⏹ 图标），允许用户随时中断 AI 生成
5. WHEN 用户点击"停止"按钮，THE Chat_Panel SHALL 立即中断 SSE 连接，保留已接收到的部分回复内容显示在对话区域，并恢复发送按钮
6. IF Chat_Router 返回错误或连接中断，THEN THE Chat_Panel SHALL 在对话区域显示错误提示信息，并允许用户重新发送消息
7. THE Chat_Router SHALL 使用 sse_with_heartbeat 包装流式响应，防止长时间无数据时连接被断开

### 需求 2：多轮对话与会话管理

**用户故事：** 作为审计项目组成员，我想进行多轮连续对话，以便在上下文中深入讨论审计问题。

#### 验收标准

1. THE Chat_Service SHALL 为每次聊天会话维护完整的消息历史列表（包含 role 和 content 字段）
2. WHEN 用户发送新消息，THE Chat_Service SHALL 将完整的历史消息列表连同新消息一起传递给 OpenAI_Service，以保持对话上下文连贯
3. WHEN 用户点击"新建对话"按钮，THE Chat_Panel SHALL 清空当前对话历史并开始新的 Chat_Session
4. THE Chat_Panel SHALL 在对话区域按时间顺序展示用户消息和 AI 回复，用户消息右对齐、AI 回复左对齐
5. WHEN 对话历史的 token 总量接近当前模型的上下文窗口限制，THE Chat_Service SHALL 自动截断较早的消息以保持在上下文窗口范围内

### 需求 3：知识库 RAG 检索注入

**用户故事：** 作为审计项目组成员，我想在聊天中通过 `@` 符号快速引用知识库，以便获得基于专业知识的准确回答。

#### 验收标准

1. WHEN 用户在输入框中输入 `@` 字符，THE Chat_Panel SHALL 弹出知识库分类候选列表（包含所有知识库分类：底稿模板库、监管规定库、会计准则库、质控标准库、审计程序库、行业指引库、提示词库、报告模板库、笔记库）
2. THE Chat_Panel SHALL 支持在 `@` 后继续输入文字进行模糊过滤（如 `@会计` 过滤出"会计准则库"）
3. THE Chat_Panel SHALL 支持键盘上下方向键在候选列表中导航，Enter 键确认选择
4. WHEN 用户选择一个知识库分类后，THE Chat_Panel SHALL 在输入框中显示 `@会计准则库` 标签样式（带背景色可点击移除），光标自动跳到标签后继续输入消息
5. THE Chat_Panel SHALL 支持在一条消息中通过多次 `@` 引用多个知识库分类
6. WHEN 用户发送包含 `@知识库` 引用的消息，THE Chat_Service SHALL 调用 Knowledge_Service 的 search_knowledge 方法，仅在用户指定的知识库分类中检索相关内容
7. WHEN Knowledge_Service 返回检索结果，THE Chat_Service SHALL 将检索到的知识库内容作为系统提示词的一部分注入到 LLM 请求的 messages 中
8. IF 用户发送的消息不包含任何 `@` 引用，THEN THE Chat_Service SHALL 不进行知识库检索，直接调用 LLM 回答
9. IF Knowledge_Service 未检索到相关内容，THEN THE Chat_Service SHALL 正常调用 LLM 进行回答，不注入额外上下文
10. WHEN 知识库内容被注入到对话中，THE Chat_Panel SHALL 在 AI 回复下方显示"已参考：@XX库"标识，标明引用了哪些知识库

### 需求 4：快捷指令联动工作模块

**用户故事：** 作为审计项目组成员，我想通过聊天框中的快捷指令快速跳转到底稿复核、文档生成等工作模块，以便提高工作效率。

#### 验收标准

1. WHEN 用户在输入框中输入斜杠字符"/"，THE Chat_Panel SHALL 显示快捷指令候选列表，包含：/复核、/生成、/分析、/报告复核
2. WHEN 用户选择或输入完整的快捷指令（如"/复核"），THE Chat_Panel SHALL 触发 onSelectMode 回调，跳转到对应的工作模块
3. THE Chat_Panel SHALL 支持键盘上下方向键在快捷指令候选列表中导航，并通过 Enter 键确认选择
4. WHEN 用户输入的文本以斜杠开头但不匹配任何已定义的快捷指令，THE Chat_Panel SHALL 将该文本作为普通聊天消息发送

### 需求 5：模型配置联动

**用户故事：** 作为审计项目组成员，我想让聊天功能使用我在配置面板中设置的 AI 模型，以便统一管理模型配置。

#### 验收标准

1. THE Chat_Router SHALL 从 Config_Manager 读取当前激活的 AI 供应商和模型配置，用于聊天对话
2. WHEN 用户在 ConfigPanel 中切换 AI 供应商或模型，THE Chat_Service SHALL 在下一次对话请求中使用更新后的配置
3. THE Chat_Panel SHALL 在聊天区域顶部显示当前使用的模型名称

### 需求 6：聊天界面布局与交互

**用户故事：** 作为审计项目组成员，我想在首页方便地使用聊天功能，同时不影响工作模式选择的操作。

#### 验收标准

1. THE Chat_Panel SHALL 以可折叠面板的形式嵌入 WorkModeSelector 首页右下角区域
2. WHEN 用户点击聊天入口按钮，THE Chat_Panel SHALL 展开显示聊天界面；再次点击 SHALL 折叠隐藏
3. THE Chat_Panel SHALL 包含输入框、发送按钮、对话消息列表、新建对话按钮和知识库开关
4. WHEN 新的 AI 回复消息出现，THE Chat_Panel SHALL 自动滚动到对话区域底部
5. THE Chat_Panel SHALL 支持 Markdown 格式渲染 AI 回复内容（包括代码块、列表、表格、加粗等）
6. THE Chat_Panel SHALL 遵循 GT Design System 的设计规范（主色 #4b2d77、圆角、间距等）

### 需求 7：对话历史本地持久化

**用户故事：** 作为审计项目组成员，我想在刷新页面后仍能看到之前的聊天记录，以便继续之前的对话。

#### 验收标准

1. WHEN 用户发送消息或收到 AI 回复，THE Chat_Panel SHALL 将当前对话历史保存到浏览器 IndexedDB 中（复用 auditStorage 模式）
2. WHEN Chat_Panel 组件初始化加载，THE Chat_Panel SHALL 从 IndexedDB 中恢复最近一次的对话历史
3. WHEN 用户点击"新建对话"按钮，THE Chat_Panel SHALL 将当前对话归档并开始新的空白对话
4. IF IndexedDB 读取失败，THEN THE Chat_Panel SHALL 以空白对话状态启动，不阻塞聊天功能

### 需求 8：后端聊天路由

**用户故事：** 作为开发者，我想有一个独立的聊天 API 路由，以便前端聊天功能有清晰的后端接口。

#### 验收标准

1. THE Chat_Router SHALL 在 /api/chat 前缀下注册路由，并在 main.py 中完成路由挂载
2. THE Chat_Router SHALL 提供 POST /api/chat/stream 端点，接收 JSON 请求体（包含 messages 数组、knowledge_library_ids 可选数组）
3. THE Chat_Router SHALL 返回 SSE 流式响应，每个 data 事件包含一段 AI 生成的文本片段
4. WHEN 流式响应完成，THE Chat_Router SHALL 发送 data: [DONE] 事件标记流结束
5. IF 请求参数校验失败，THEN THE Chat_Router SHALL 返回 HTTP 422 状态码和错误描述

### 需求 9：聊天文档上传

**用户故事：** 作为审计项目组成员，我想在聊天中上传文档（PDF/Word/Excel/TXT），以便让 AI 基于文档内容回答问题。

#### 验收标准

1. THE Chat_Panel SHALL 在输入框旁提供文档上传按钮（📎 图标），支持点击选择或拖拽上传
2. THE Chat_Panel SHALL 支持上传以下格式的文档：PDF、Word（.docx/.doc）、Excel（.xlsx/.xls）、CSV、TXT、Markdown
3. WHEN 用户选择文档后，THE Chat_Panel SHALL 将文件上传至 Chat_Router 的 POST /api/chat/upload 端点
4. WHEN Chat_Router 收到上传文件，THE Chat_Service SHALL 参照文档分析模块的解析流程（OCR_Service 的 smart_parse 智能策略：PDF 自动检测类型→文字层直接提取→扫描版 OCR→质量检测→fallback；Word 用 docx_to_md 转换；Excel 用 openpyxl 提取）提取文档文本内容
5. WHEN 文档文本提取完成，THE Chat_Service SHALL 将文档内容作为上下文注入到后续对话的 system prompt 中
6. THE Chat_Panel SHALL 在对话区域显示已上传文档的文件名和大小，并提供"移除"和"保存到笔记"两个操作按钮
7. WHEN 用户点击"保存到笔记"按钮，THE Chat_Service SHALL 将文档解析后的文本内容保存到 Notes_Library 中
8. IF 文档解析失败或文件格式不支持，THEN THE Chat_Panel SHALL 显示错误提示并允许用户重新上传
9. THE Chat_Router SHALL 限制单个上传文件大小不超过 20MB

### 需求 10：语音输入

**用户故事：** 作为审计项目组成员，我想通过语音输入消息，以便在不方便打字时也能快速与 AI 对话。

#### 验收标准

1. THE Chat_Panel SHALL 在输入框旁提供语音输入按钮（🎤 图标）
2. WHEN 用户点击语音按钮，THE Chat_Panel SHALL 请求浏览器麦克风权限并开始录音，按钮变为录音中状态（红色脉冲动画）
3. WHEN 用户再次点击语音按钮停止录音，THE Chat_Panel SHALL 将录音音频发送至 Chat_Router 的 POST /api/chat/speech-to-text 端点进行语音识别
4. WHEN Chat_Router 收到音频数据，THE Chat_Service SHALL 调用 OpenAI_Service 的 Whisper API（或兼容的语音识别服务）将语音转换为文本
5. WHEN 语音识别完成，THE Chat_Panel SHALL 将识别结果填入输入框，用户可编辑后发送
6. IF 浏览器不支持 MediaRecorder API 或用户拒绝麦克风权限，THEN THE Chat_Panel SHALL 隐藏语音输入按钮并不影响其他功能
7. WHILE 录音进行中，THE Chat_Panel SHALL 显示录音时长计时器
8. THE Chat_Panel SHALL 限制单次录音时长不超过 120 秒，超时自动停止并提交识别

### 需求 11：笔记功能与智能管理

**用户故事：** 作为审计项目组成员，我想将聊天中有价值的对话记录和上传文档保存为笔记，并由 AI 辅助管理笔记内容，以便保持笔记库精简有用。

#### 验收标准

##### 笔记与对话联动

1. THE Knowledge_Service SHALL 在 LIBRARIES 中新增 'notes' 分类（笔记库），与其他知识库分类并列管理
2. THE Notes_Library SHALL 按日期自动创建子文件夹管理笔记文件，目录结构为 `~/.gt_audit_helper/knowledge/notes/{YYYY-MM-DD}/`，每天的笔记存放在对应日期文件夹中
3. THE Chat_Panel SHALL 在每条 AI 回复消息上提供"保存到笔记"操作按钮（📌 图标）
4. WHEN 用户点击 AI 回复的"保存到笔记"按钮，THE Chat_Service SHALL 将该条 AI 回复内容（含对应的用户提问作为标题）保存到当天日期文件夹的 Notes_Library 中
5. WHEN 用户点击上传文档的"保存到笔记"按钮，THE Chat_Service SHALL 将文档解析后的文本内容以原文件名为标题保存到当天日期文件夹的 Notes_Library 中
6. THE Chat_Panel SHALL 支持将整段对话（多轮问答）一键保存为一条笔记，以"对话摘要 - 日期时间"为标题
7. WHEN 笔记保存成功，THE Chat_Panel SHALL 显示"已保存到笔记库"的成功提示

##### 笔记侧边栏

8. THE Chat_Panel SHALL 提供笔记侧边栏（可展开/收起），按日期分组展示笔记列表（日期标题 → 该日笔记条目：标题、创建时间、大小）
9. THE 笔记侧边栏 SHALL 支持按日期折叠/展开，默认展开最近 3 天
10. THE 笔记侧边栏 SHALL 支持用户直接删除单条笔记，删除前需确认
11. THE 笔记侧边栏 SHALL 支持点击笔记标题预览笔记内容

##### AI 智能提示

12. WHEN AI 回复中包含关键审计结论、法规引用、数值校验结果等高价值内容，THE Chat_Service SHALL 在回复末尾附加"建议保存到笔记"的提示标签，用户可一键确认保存
13. WHEN Notes_Library 中的笔记数量超过阈值（默认 50 条）或总大小超过阈值（默认 5MB），THE Chat_Service SHALL 在用户下次打开聊天时提示"笔记库内容较多，建议清理"
14. WHEN 用户触发笔记清理，THE Chat_Service SHALL 调用 LLM 分析笔记库内容，识别重复、过时或低价值的笔记，生成清理建议列表供用户勾选删除
15. THE Chat_Panel SHALL 在清理建议列表中标注每条笔记的创建时间、最后被 RAG 引用时间和建议删除原因，用户可逐条确认或批量删除

##### 知识库集成与跨模块联动

16. THE Notes_Library SHALL 与其他知识库分类一样支持 RAG 检索，WHEN 用户在聊天中启用知识库检索且选中笔记库时，THE Chat_Service SHALL 检索笔记库中的内容作为上下文注入
17. THE Notes_Library SHALL 在 KnowledgePanel 中与其他知识库分类一起展示，支持查看、编辑和删除笔记
18. THE Notes_Library 中的笔记 SHALL 可被其他工作模块（底稿复核、文档生成、文档分析、审计报告复核）在关联知识库时选用

### 需求 12：对话内容复制与导出

**用户故事：** 作为审计项目组成员，我想复制或导出 AI 的回复内容到 Word 文档，并支持多选、编辑后再导出，以便在审计工作底稿或报告中直接使用。

#### 验收标准

##### 单条复制

1. THE Chat_Panel SHALL 在每条 AI 回复消息上提供"复制"按钮（📋 图标），点击后将该条回复内容以富文本（HTML）格式写入剪贴板，确保粘贴到 Word 中保留标题、列表、表格、加粗等格式
2. WHEN 复制成功，THE Chat_Panel SHALL 显示"已复制"的短暂提示（1.5秒后自动消失）
3. IF 剪贴板 Clipboard API 不可用或富文本写入失败，THEN THE Chat_Panel SHALL 回退到复制 Markdown 纯文本

##### 单条导出

4. THE Chat_Panel SHALL 在每条 AI 回复消息上提供"导出 Word"按钮（📄 图标），点击后将该条回复内容导出为 Word 文档下载
5. WHEN 用户点击单条回复的"导出 Word"按钮，THE Chat_Router SHALL 调用已有的 word_service 将 Markdown 内容渲染为 Word 文档（复用审计文档的排版风格：仿宋_GB2312 + Arial Narrow），返回文件供下载

##### 多选导出

6. WHEN 用户点击对话区域顶部的"导出"按钮，THE Chat_Panel SHALL 进入多选模式，每条消息（用户提问和 AI 回复）前显示 checkbox
7. THE Chat_Panel SHALL 在多选模式下提供"全选"和"仅选 AI 回复"快捷按钮
8. WHEN 用户勾选完毕并点击"确认导出"，THE Chat_Panel SHALL 弹出导出预览编辑面板

##### 导出前编辑

9. THE 导出预览编辑面板 SHALL 将用户多选的对话内容按时间顺序合并为一篇 Markdown 文档，用户消息标注"提问："、AI 回复标注"回复："
10. THE 导出预览编辑面板 SHALL 支持用户手动编辑合并后的文档内容（增删改文字、调整顺序）
11. THE 导出预览编辑面板 SHALL 提供"AI 润色"按钮，点击后调用 LLM 对合并内容进行整理润色（去除对话格式、统一行文风格、补充过渡语句），润色结果替换编辑区内容，用户可继续修改
12. WHEN 用户在编辑面板中点击"导出 Word"，THE Chat_Router SHALL 将编辑后的最终内容渲染为 Word 文档下载

##### 通用

13. THE 导出的 Word 文档文件名 SHALL 包含日期时间戳（如"聊天记录_20260406_143000.docx"）
14. WHEN 用户取消多选模式或关闭编辑面板，THE Chat_Panel SHALL 恢复正常对话视图

##### 在线编辑

15. THE 导出预览编辑面板和单条导出 SHALL 提供"在线编辑"按钮（除"导出 Word"外的第二选项）
16. WHEN 用户点击"在线编辑"按钮，THE Chat_Panel SHALL 调用后端生成 Word 文件，然后使用 ranuts/document 编辑器在浏览器内打开该 Word 文件进行在线编辑
17. WHEN 用户在 ranuts/document 编辑器中完成编辑，THE Chat_Panel SHALL 提供"下载"按钮将编辑后的文档下载到本地
18. THE ranuts/document 编辑器 SHALL 以模态框或全屏面板形式展示，提供关闭按钮返回聊天界面

### 需求 13：截图上传与识别

**用户故事：** 作为审计项目组成员，我想在聊天中粘贴或上传截图，以便让 AI 识别图片中的文字、表格或数据并基于内容回答问题。

#### 验收标准

1. THE Chat_Panel SHALL 支持用户通过 Ctrl+V（粘贴剪贴板图片）将截图直接粘贴到输入区域
2. THE Chat_Panel SHALL 在输入框旁的文档上传按钮（📎）中同时支持选择图片文件（.png/.jpg/.jpeg/.bmp/.webp）
3. WHEN 用户粘贴或选择图片后，THE Chat_Panel SHALL 在输入框上方显示图片缩略图预览，支持点击移除
4. WHEN 用户发送包含图片的消息，THE Chat_Panel SHALL 将图片上传至 Chat_Router 的 POST /api/chat/upload 端点
5. WHEN Chat_Router 收到图片文件，THE Chat_Service SHALL 调用 OCR_Service（Tesseract 中英文识别）提取图片中的文字内容
6. WHEN OCR 提取完成，THE Chat_Service SHALL 将识别出的文字内容作为上下文注入到 LLM 请求中，连同用户的文字消息一起发送
7. THE Chat_Panel SHALL 在对话区域中展示用户发送的图片（可点击放大查看），并在 AI 回复中标注"已识别图片内容"
8. IF OCR 未识别出任何文字，THEN THE Chat_Service SHALL 在回复中提示"未能从图片中识别出文字内容，请确认图片清晰度"
9. THE Chat_Panel SHALL 支持同时上传多张图片（最多 5 张），所有图片的 OCR 结果合并后注入上下文

### 需求 14：欢迎引导与智能模块推荐

**用户故事：** 作为审计项目组成员，我想在打开聊天时看到功能引导和问候，并在对话中获得相关工作模块的推荐，以便快速找到最合适的工具。

#### 验收标准

##### 欢迎引导

1. WHEN 用户首次展开 Chat_Panel 或开始新对话时，THE Chat_Panel SHALL 显示欢迎消息，包含问候语和四大工作模块的快捷入口卡片
2. THE 欢迎消息 SHALL 包含四个可点击的模块卡片：底稿复核（📋）、文档生成（📝）、文档分析（🔍）、审计报告复核（📊），每个卡片显示模块名称和一句话功能简介
3. WHEN 用户点击欢迎消息中的模块卡片，THE Chat_Panel SHALL 触发 onSelectMode 回调跳转到对应工作模块
4. THE 欢迎消息 SHALL 包含使用提示："输入 / 快速跳转模块，输入 @ 引用知识库，点击 📎 上传文档"

##### 智能模块推荐

5. THE Chat_Service SHALL 在 system prompt 中注入四大工作模块的功能描述，使 LLM 了解可用的专业工具
6. WHEN AI 判断用户的问题更适合使用某个专业工作模块处理时（如用户问"帮我检查这份底稿"），THE AI 回复 SHALL 在回答的同时建议使用对应模块，并附带可点击的模块跳转按钮
7. THE Chat_Panel SHALL 识别 AI 回复中的模块推荐标记（如 `[推荐模块:review]`），将其渲染为可点击的模块跳转按钮
8. THE 模块推荐 SHALL 仅作为建议，不阻断正常对话，用户可忽略推荐继续聊天

### 需求 15：知识库与笔记库文档移动复制

**用户故事：** 作为审计项目组成员，我想在知识库各分类和笔记库之间移动或复制文档，以便灵活整理和归类资料。

#### 验收标准

##### 单文档操作

1. THE KnowledgePanel 和笔记侧边栏 SHALL 在每个文档条目上提供右键菜单或操作按钮，包含"移动到..."和"复制到..."选项
2. WHEN 用户选择"移动到..."或"复制到..."，THE 界面 SHALL 弹出目标选择器，列出所有知识库分类和笔记库的日期文件夹供用户选择目标位置
3. WHEN 用户确认目标位置，THE Knowledge_Service SHALL 将文档移动（从源位置删除并添加到目标位置）或复制（保留源位置并在目标位置创建副本）

##### 批量操作

4. THE KnowledgePanel 和笔记侧边栏 SHALL 支持多选模式（checkbox），允许用户勾选多个文档后批量移动或复制
5. THE 批量操作 SHALL 支持跨知识库分类选择目标（如从"会计准则库"批量复制到"笔记库/2026-04-06"）

##### 文件夹操作（笔记库）

6. THE 笔记侧边栏 SHALL 支持对整个日期文件夹执行移动或复制操作，将该文件夹下所有笔记整体迁移到目标知识库分类
7. WHEN 移动整个日期文件夹到非笔记库的知识库分类时，THE Knowledge_Service SHALL 将文件夹内所有文档平铺添加到目标分类（因为其他知识库分类无日期子文件夹结构）

##### 通用

8. WHEN 移动或复制操作完成，THE 界面 SHALL 显示操作结果提示（如"已移动 3 个文档到会计准则库"）
9. IF 目标位置已存在同名文档，THEN THE Knowledge_Service SHALL 自动在文件名后追加序号（如"文档名_1"）避免覆盖
10. THE Chat_Router SHALL 提供 POST /api/knowledge/move 和 POST /api/knowledge/copy 端点，接收源文档 ID 列表、源知识库 ID 和目标知识库 ID
