# 致同AI - 审计底稿智能复核与文档生成

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/React-19+-61dafb.svg" alt="React">
  <img src="https://img.shields.io/badge/FastAPI-0.116+-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
</p>

面向会计师事务所审计项目组的智能复核与文档生成平台。系统提供两大核心工作模式：对审计底稿进行多维度自动化复核，以及基于模板和知识库智能生成审计文档。

## 核心功能

### 底稿智能复核

四步骤工作流：底稿上传 → 提示词选择与维度配置 → 补充材料与确认 → 复核报告查看与导出

- 支持 Excel（.xlsx/.xls）、Word（.docx）、PDF 格式底稿上传与解析
- 自动识别底稿编号体系（B/C/D-M类），归类到对应业务循环
- 5个标准复核维度：格式规范性、数据勾稽关系、会计准则合规性、审计程序完整性、审计证据充分性
- 支持自定义复核关注点
- SSE 流式输出复核进度，实时展示当前分析维度
- 风险等级分类（高/中/低），同时使用颜色和文字标签确保可访问性
- 底稿间交叉引用分析，验证 B/C/D-M 类底稿结论一致性
- 结构化复核报告，支持导出 Word 和 PDF

### 审计文档生成

四步骤工作流：模板上传与配置 → 大纲识别与确认 → 逐章节生成与编辑 → 导出

- 支持上传 Word/Excel/PDF 格式模板
- 5种预置模板类型：审计计划、审计小结、尽调报告、审计报告、其他自定义
- 大纲快速提取：优先使用 Word 标题样式，无样式时通过中文序号模式（一、（一）等）智能检测，自动过滤目录页，秒级完成；仅在无法识别时回退到 LLM
- 统一阿拉伯数字层级编号（1, 1.1, 1.1.1），前后端一致
- 大纲可视化编辑：增删改章节、调整层级和顺序，确认后进入生成
- 三种生成模式：批量生成（3并发）、逐章节生成（顺序）、停止（中断所有）
- SSE 流式逐章节生成，注入父级/同级章节上下文保证连贯性
- 关联知识库，优先使用真实信息；无知识库时结合审计专业知识生成实质性内容（底线思维），仅具体数据标注【待补充】
- 每个章节支持：单独生成、手动编辑、AI 对话式修改（含选中文本局部修改和高亮）、参考文档上传辅助生成
- 章节编辑器内置模型选择器，支持切换 LLM 模型
- 全局重置与单章节重置，章节点击高亮选中
- 浮动导航按钮：滚动时一键返回顶部，顶部时跳转到生成中的章节
- 步骤间状态缓存：返回修改大纲后已生成内容按标题匹配自动保留
- Word 导出，支持自定义中英文字体设置

### 提示词库管理

- 从 TSJ/ 目录加载约70个按会计科目分类的预置提示词（markdown格式）
- 支持编辑、替换、追加自定义提示词，保留原始版本可恢复
- 来源四级标识：preset / user_modified / user_replaced / user_appended
- `{{#sys.files#}}` 占位符运行时替换为实际底稿文件列表
- Git 版本管理（关联远程仓库），支持拉取/推送/冲突处理/标签管理

### 知识库管理

7个审计专用知识库分类：底稿模板库、监管规定库、会计准则库、质控标准库、审计程序库、行业指引库、提示词库

- 支持 PDF、Word、Markdown、TXT、Excel 格式文档
- LRU 缓存策略，上限300个文档
- 按关键词搜索，结果按相关性排序

### 项目管理

- 按审计项目组织底稿和模板
- 4种用户角色：合伙人、项目经理、审计员、质控人员
- 复核进度概览（已复核/待复核/各风险等级统计）
- 按业务循环筛选底稿

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+

### 安装与运行

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动后端（端口 9980）
python run.py

# 另开终端，安装前端依赖并构建
cd frontend
npm install
npm run build
```

启动后访问 http://localhost:9980

## 技术架构

```
├── backend/                        # 后端 (FastAPI + Python)
│   ├── app/
│   │   ├── main.py                # 应用入口
│   │   ├── models/
│   │   │   ├── schemas.py         # 通用数据模型
│   │   │   └── audit_schemas.py   # 审计相关数据模型
│   │   ├── routers/
│   │   │   ├── review.py          # 复核 API (/api/review)
│   │   │   ├── generate.py        # 文档生成 API (/api/generate)
│   │   │   ├── prompt.py          # 提示词管理 API (/api/prompt)
│   │   │   ├── template.py        # 模板管理 API (/api/template)
│   │   │   └── project.py         # 项目管理 API (/api/project)
│   │   ├── services/
│   │   │   ├── review_engine.py       # 复核引擎
│   │   │   ├── report_generator.py    # 报告生成与导出
│   │   │   ├── document_generator.py  # 文档生成（大纲提取+章节生成）
│   │   │   ├── workpaper_parser.py    # 底稿解析
│   │   │   ├── template_service.py    # 模板管理（结构解析+标题检测）
│   │   │   ├── project_service.py     # 项目管理
│   │   │   ├── prompt_library.py      # 提示词库
│   │   │   ├── prompt_git_service.py  # 提示词 Git 版本管理
│   │   │   ├── openai_service.py      # LLM 服务（多供应商）
│   │   │   ├── knowledge_service.py   # 知识库服务
│   │   │   ├── knowledge_retriever.py # 知识库智能检索（按章节匹配）
│   │   │   └── word_service.py        # Word 导出
│   │   └── utils/                 # 工具层
│   └── requirements.txt
├── frontend/                      # 前端 (React + TypeScript)
│   └── src/
│       ├── components/
│       │   ├── WorkModeSelector.tsx        # 工作模式选择
│       │   ├── ReviewWorkflow.tsx          # 复核工作流
│       │   ├── GenerateWorkflow.tsx        # 文档生成工作流
│       │   ├── WorkpaperUpload.tsx         # 底稿上传
│       │   ├── PromptSelector.tsx          # 提示词选择
│       │   ├── ReviewDimensionConfig.tsx   # 复核维度配置
│       │   ├── SupplementaryUpload.tsx     # 补充材料上传
│       │   ├── ReviewConfirmation.tsx      # 复核确认
│       │   ├── ReviewReport.tsx            # 复核报告展示
│       │   ├── CrossReferenceGraph.tsx     # 交叉引用关系图
│       │   ├── TemplateSelector.tsx        # 模板选择
│       │   ├── TemplateOutlineEditor.tsx   # 大纲编辑
│       │   ├── DocumentEditor.tsx          # 文档编辑
│       │   ├── SectionEditor.tsx           # 章节编辑器
│       │   ├── ExportPanel.tsx             # 导出面板
│       │   ├── FontSettings.tsx            # 字体设置
│       │   └── ProjectPanel.tsx            # 项目管理
│       ├── types/audit.ts         # 审计类型定义
│       ├── services/api.ts        # API 封装
│       ├── utils/auditStorage.ts  # IndexedDB 缓存
│       └── styles/gt-design-tokens.css  # GT 设计系统
├── TSJ/                           # 预置提示词库 (~70个 markdown 文件)
└── .kiro/specs/                   # 功能规格文档
```

## API 端点

启动后访问 http://localhost:9980/docs 查看交互式 API 文档。

| 模块 | 端点前缀 | 说明 |
|------|----------|------|
| 复核 | `/api/review` | 底稿上传、发起复核、报告导出、问题状态更新、交叉引用 |
| 文档生成 | `/api/generate` | 大纲提取、逐章节生成、章节修改、文档导出 |
| 提示词 | `/api/prompt` | 提示词 CRUD、Git 同步/推送/冲突处理/标签 |
| 模板 | `/api/template` | 模板上传、列表、详情、删除、更新 |
| 项目 | `/api/project` | 项目创建、底稿关联、模板关联、进度概览 |

## 数据存储

- 项目数据：`~/.gt_audit_helper/projects/{project_id}/`
- 模板文件：`~/.gt_audit_helper/templates/{template_id}/`
- 自定义提示词：`~/.gt_audit_helper/prompts/`
- Git 仓库克隆：`~/.gt_audit_helper/prompt_git/`
- 浏览器端工作状态：IndexedDB

## UI 设计规范

遵循致同 GT 审计手册设计规范（GT Design System）：
- 主色调：GT核心紫色（#4b2d77）、亮紫色（#A06DFF）、深紫色（#2B1D4D）
- 辅助色：水鸭蓝（#0094B3）、珊瑚橙（#FF5149）、麦田黄（#FFC23D）
- 响应式布局：桌面端多列 → 平板端双列 → 移动端单列
- 可访问性：WCAG 2.1 AA 级，焦点样式、语义化 HTML、对比度达标
- 打印样式：A4 尺寸、黑白配色、防分页断裂

## 许可证

[MIT License](LICENSE)

---

<p align="center">Made with ❤️ by 致同研究院</p>
