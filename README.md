# 致同AI审计助手 - 智能复核与文档生成平台

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/React-19+-61dafb.svg" alt="React">
  <img src="https://img.shields.io/badge/FastAPI-0.116+-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/TypeScript-4.9+-3178c6.svg" alt="TypeScript">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
</p>

面向会计师事务所审计项目组的 AI 驱动智能复核与文档生成平台。提供四大核心工作模式：底稿智能复核、审计文档生成、文档分析、审计报告复核。

## 目录

- [核心功能](#核心功能)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [打包部署](#打包部署)
- [API 端点](#api-端点)
- [数据存储](#数据存储)
- [项目结构](#项目结构)
- [许可证](#许可证)

## 核心功能

### 🔍 底稿智能复核

四步骤工作流：底稿上传 → 提示词选择与维度配置 → 补充材料与确认 → 复核报告查看与导出

- 支持 Excel（.xlsx/.xls）、Word（.docx）、PDF 格式底稿上传与解析
- 自动识别底稿编号体系（B/C/D-M类），归类到对应业务循环
- 5个标准复核维度：格式规范性、数据勾稽关系、会计准则合规性、审计程序完整性、审计证据充分性
- 支持自定义复核关注点
- SSE 流式输出复核进度，实时展示当前分析维度
- 风险等级分类（高/中/低），使用颜色和文字标签确保可访问性
- 底稿间交叉引用分析，验证 B/C/D-M 类底稿结论一致性
- 结构化复核报告，支持导出 Word 和 PDF

### 📝 审计文档生成

四步骤工作流：模板上传与配置 → 大纲识别与确认 → 逐章节生成与编辑 → 导出

- 支持上传 Word/Excel/PDF 格式模板
- 5种预置模板类型：审计计划、审计小结、尽调报告、审计报告、其他自定义
- 大纲快速提取：优先使用 Word 标题样式，无样式时通过中文序号模式智能检测，自动过滤目录页
- 统一阿拉伯数字层级编号（1, 1.1, 1.1.1），前后端一致
- 大纲可视化编辑：增删改章节、调整层级和顺序
- 三种生成模式：批量生成（3并发）、逐章节生成（顺序）、停止（中断所有）
- SSE 流式逐章节生成，注入父级/同级章节上下文保证连贯性
- 关联知识库，优先使用真实信息；无知识库时结合审计专业知识生成实质性内容
- 每个章节支持：单独生成、手动编辑、AI 对话式修改（含选中文本局部修改和高亮）、参考文档上传辅助生成
- 章节编辑器内置模型选择器，支持切换 LLM 模型
- Word 导出，支持自定义中英文字体设置

### 📊 文档分析

- 文档上传与智能解析（PDF/Word/Excel）
- 科目匹配与对账分析
- 表格结构分析与数据提取
- OCR 图片文字识别（Tesseract）
- 文本质量分析

### 📋 审计报告复核

- 审计报告上传与模板配置
- 报告正文智能复核
- 附注内容复核
- 发现问题确认与跟踪

### 💡 提示词库管理

- 从 TSJ/ 目录加载约70个按会计科目分类的预置提示词（Markdown 格式）
- 支持编辑、替换、追加自定义提示词，保留原始版本可恢复
- 来源四级标识：preset / user_modified / user_replaced / user_appended
- `{{#sys.files#}}` 占位符运行时替换为实际底稿文件列表
- Git 版本管理（关联远程仓库），支持拉取/推送/冲突处理/标签管理

### 📚 知识库管理

7个审计专用知识库分类：底稿模板库、监管规定库、会计准则库、质控标准库、审计程序库、行业指引库、提示词库

- 支持 PDF、Word、Markdown、TXT、Excel 格式文档
- LRU 缓存策略，上限300个文档
- 按关键词搜索，结果按相关性排序
- 智能检索按章节匹配知识库内容

### 🗂️ 项目管理

- 按审计项目组织底稿和模板
- 4种用户角色：合伙人、项目经理、审计员、质控人员
- 复核进度概览（已复核/待复核/各风险等级统计）
- 按业务循环筛选底稿


## 技术架构

| 层级 | 技术栈 | 说明 |
|------|--------|------|
| 前端 | React 19 + TypeScript + Tailwind CSS 3 | SPA 单页应用，GT 设计系统 |
| 后端 | FastAPI + Uvicorn | 异步 API 服务，SSE 流式响应 |
| AI 引擎 | OpenAI 兼容 API（多供应商） | 支持 DeepSeek、通义千问、Kimi、MiniMax、智谱 GLM 等 |
| 文档解析 | python-docx / openpyxl / PyPDF2 / pdfplumber / PyMuPDF | 多格式文档读写 |
| PDF 高级解析 | MinerU（可选） | GPU 加速 PDF→Markdown 转换 |
| 导出 | python-docx / WeasyPrint | Word/PDF 报告导出 |
| 存储 | 文件系统 + IndexedDB | 服务端文件存储 + 浏览器端状态缓存 |

### 多 LLM 供应商支持

系统通过 OpenAI 兼容 API 接口支持多家 AI 供应商，在前端配置面板中可切换：

- SiliconFlow 硅基流动（推荐 DeepSeek-V3.2）
- DeepSeek 官方 API
- 通义千问（Qwen）
- Kimi / Moonshot
- MiniMax
- 智谱 GLM
- Ollama 本地模型

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- Git（提示词版本管理需要）

### 开发模式（前后端分离）

```bash
# 1. 克隆项目
git clone <repo-url>
cd GT_digao

# 2. 安装后端依赖
cd backend
pip install -r requirements.txt

# 3. 配置环境变量（可选）
copy .env.example .env
# 编辑 .env 设置 MINERU_HOME 等

# 4. 启动后端（端口 9980）
python run.py

# 5. 另开终端，安装前端依赖
cd frontend
npm install

# 6. 启动前端开发服务器（端口 3030）
npm start
```

前端开发服务器：http://localhost:3030
后端 API 文档：http://localhost:9980/docs

### 生产模式（前端构建后由后端托管）

```bash
# 构建前端
cd frontend
npm run build

# 复制构建产物到后端静态目录
# Windows:
xcopy /E /I /Y build ..\backend\static

# 启动后端（同时托管前端）
cd ..\backend
python run.py
```

访问 http://localhost:9980 即可使用全部功能。

### 一键启动（开发模式）

双击项目根目录的 `start.bat`，自动检测环境、安装依赖、启动前后端服务。

## 打包部署

### 方式一：绿色便携包（推荐分发给客户）

运行 `pack_portable.py` 生成免安装绿色便携包：

```bash
cd GT_digao
python pack_portable.py
```

产出 `dist/致同AI审计助手/` 目录，压缩为 zip 即可分发。客户需自行安装 Python 3.10+。

### 方式二：EXE 单文件打包（无需 Python 环境）

运行 `build_exe.py` 使用 PyInstaller 打包为独立 EXE：

```bash
# 确保已安装打包依赖
pip install pyinstaller

# 执行打包（自动构建前端、收集依赖、生成 EXE）
cd GT_digao
python build_exe.py
```

产出 `dist/致同AI审计助手.exe`，双击即可运行，无需安装 Python 或 Node.js。

详细说明见 [build_exe.py](build_exe.py) 文件头部注释。

## API 端点

启动后访问 http://localhost:9980/docs 查看交互式 API 文档（Swagger UI）。

| 模块 | 端点前缀 | 说明 |
|------|----------|------|
| 配置 | `/api/config` | AI 供应商/模型配置 |
| 复核 | `/api/review` | 底稿上传、发起复核、报告导出、问题状态更新、交叉引用 |
| 文档生成 | `/api/generate` | 大纲提取、逐章节生成、章节修改、文档导出 |
| 文档分析 | `/api/analysis` | 文档解析、科目匹配、表格分析 |
| 审计报告复核 | `/api/report-review` | 报告上传、正文复核、附注复核 |
| 提示词 | `/api/prompt` | 提示词 CRUD、Git 同步/推送/冲突处理/标签 |
| 模板 | `/api/template` | 模板上传、列表、详情、删除、更新 |
| 知识库 | `/api/knowledge` | 知识库文档管理、搜索、检索 |
| 项目 | `/api/project` | 项目创建、底稿关联、模板关联、进度概览 |
| 文档处理 | `/api/document` | 文档上传与解析 |
| 大纲 | `/api/outline` | 大纲提取与编辑 |
| 内容 | `/api/content` | 章节内容生成与编辑 |
| 搜索 | `/api/search` | 网络搜索辅助 |

## 数据存储

| 数据类型 | 存储位置 |
|----------|----------|
| 项目数据 | `~/.gt_audit_helper/projects/{project_id}/` |
| 模板文件 | `~/.gt_audit_helper/templates/{template_id}/` |
| 自定义提示词 | `~/.gt_audit_helper/prompts/` |
| Git 仓库克隆 | `~/.gt_audit_helper/prompt_git/` |
| AI 配置 | `~/.gt_audit_helper/config.json` |
| 知识库文件 | `~/.gt_audit_helper/knowledge/` |
| 浏览器端工作状态 | IndexedDB（浏览器本地） |


## 项目结构

```
GT_digao/
├── backend/                           # 后端 (FastAPI + Python 3.12)
│   ├── app/
│   │   ├── main.py                    # 应用入口，路由注册，静态文件托管
│   │   ├── config.py                  # 应用配置（CORS、文件上传限制等）
│   │   ├── models/
│   │   │   ├── schemas.py             # 通用数据模型
│   │   │   ├── audit_schemas.py       # 审计相关数据模型
│   │   │   └── analysis_schemas.py    # 文档分析数据模型
│   │   ├── routers/                   # API 路由层（15个路由模块）
│   │   │   ├── review.py              # 复核 API
│   │   │   ├── generate.py            # 文档生成 API
│   │   │   ├── prompt.py              # 提示词管理 API
│   │   │   ├── template.py            # 模板管理 API
│   │   │   ├── project.py             # 项目管理 API
│   │   │   ├── knowledge.py           # 知识库 API
│   │   │   ├── analysis.py            # 文档分析 API
│   │   │   ├── report_review.py       # 审计报告复核 API
│   │   │   ├── config.py              # 配置管理 API
│   │   │   ├── document.py            # 文档处理 API
│   │   │   ├── outline.py             # 大纲 API
│   │   │   ├── content.py             # 内容生成 API
│   │   │   ├── search.py              # 搜索 API
│   │   │   └── expand.py              # 扩展 API
│   │   ├── services/                  # 业务逻辑层（28个服务模块）
│   │   │   ├── openai_service.py      # LLM 服务（多供应商适配）
│   │   │   ├── review_engine.py       # 底稿复核引擎
│   │   │   ├── report_generator.py    # 报告生成与导出
│   │   │   ├── document_generator.py  # 文档生成（大纲提取+章节生成）
│   │   │   ├── workpaper_parser.py    # 底稿解析
│   │   │   ├── template_service.py    # 模板管理
│   │   │   ├── project_service.py     # 项目管理
│   │   │   ├── prompt_library.py      # 提示词库
│   │   │   ├── prompt_git_service.py  # 提示词 Git 版本管理
│   │   │   ├── knowledge_service.py   # 知识库服务
│   │   │   ├── knowledge_retriever.py # 知识库智能检索
│   │   │   ├── word_service.py        # Word 导出
│   │   │   ├── analysis_service.py    # 文档分析服务
│   │   │   ├── report_review_engine.py # 审计报告复核引擎
│   │   │   ├── ocr_service.py         # OCR 服务
│   │   │   └── ...                    # 其他服务模块
│   │   └── utils/                     # 工具层
│   │       ├── config_manager.py      # 运行时配置管理
│   │       ├── prompt_manager.py      # 提示词模板管理
│   │       ├── outline_util.py        # 大纲处理工具
│   │       ├── json_util.py           # JSON 解析工具
│   │       ├── docx_to_md.py          # Word→Markdown 转换
│   │       └── sse.py                 # SSE 流式响应工具
│   ├── data/templates/                # 内置模板
│   ├── requirements.txt               # Python 依赖
│   ├── run.py                         # 启动脚本
│   └── .env.example                   # 环境变量示例
├── frontend/                          # 前端 (React 19 + TypeScript + Tailwind CSS)
│   └── src/
│       ├── App.tsx                    # 主应用（工作模式路由）
│       ├── components/                # UI 组件（33个）
│       │   ├── WorkModeSelector.tsx   # 工作模式选择首页
│       │   ├── ConfigPanel.tsx        # AI 配置面板
│       │   ├── ReviewWorkflow.tsx     # 底稿复核工作流
│       │   ├── GenerateWorkflow.tsx   # 文档生成工作流
│       │   ├── AnalysisWorkflow.tsx   # 文档分析工作流
│       │   ├── AuditReportWorkflow.tsx # 审计报告复核工作流
│       │   ├── DocumentEditor.tsx     # 文档编辑器
│       │   ├── SectionEditor.tsx      # 章节编辑器
│       │   ├── KnowledgePanel.tsx     # 知识库面板
│       │   ├── ProjectPanel.tsx       # 项目管理面板
│       │   └── ...                    # 其他组件
│       ├── pages/                     # 页面组件
│       │   ├── DocumentAnalysis.tsx   # 文档分析页
│       │   ├── OutlineEdit.tsx        # 大纲编辑页
│       │   └── ContentEdit.tsx        # 内容编辑页
│       ├── hooks/useAppState.ts       # 全局状态管理
│       ├── services/api.ts            # API 封装
│       ├── types/                     # TypeScript 类型定义
│       ├── utils/                     # 工具函数
│       │   ├── auditStorage.ts        # IndexedDB 缓存
│       │   ├── draftStorage.ts        # 草稿存储
│       │   └── sseParser.ts           # SSE 流解析
│       └── styles/gt-design-tokens.css # GT 设计系统 Token
├── TSJ/                               # 预置提示词库（~70个 Markdown 文件）
├── MinerU/                            # MinerU PDF 解析工具（可选）
│   ├── mineru_env/                    # MinerU Python 虚拟环境
│   ├── web_ui.py                      # Web 界面
│   └── 启动Web界面.bat
├── GT_底稿/                            # 审计底稿模板与操作手册
│   ├── D销售循环/ ~ M权益循环/         # 各业务循环底稿模板
│   ├── Q关联方循环/
│   ├── 致同底稿模板/                   # 底稿模板文件
│   └── 审计实务操作手册.html           # 操作手册
├── start.bat                          # 一键启动脚本（开发模式）
├── pack_portable.py                   # 绿色便携包打包脚本
├── build_exe.py                       # EXE 打包脚本（PyInstaller）
└── LICENSE                            # MIT 许可证
```

## UI 设计规范

遵循致同 GT 审计手册设计规范（GT Design System）：

- 主色调：GT 核心紫色（#4b2d77）、亮紫色（#A06DFF）、深紫色（#2B1D4D）
- 辅助色：水鸭蓝（#0094B3）、珊瑚橙（#FF5149）、麦田黄（#FFC23D）
- 响应式布局：桌面端多列 → 平板端双列 → 移动端单列
- 可访问性：焦点样式、语义化 HTML、对比度达标
- 打印样式：A4 尺寸、黑白配色、防分页断裂

## 许可证

[MIT License](LICENSE)

---

<p align="center">Made with ❤️ by 致同研究院</p>
