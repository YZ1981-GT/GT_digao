---
inclusion: always
---

# GT_digao 术语速查

> 本仓库专用术语。React 18 + TypeScript 前端，FastAPI 后端，四大工作模块 + 首页聊天。

## 模块与路由

| 术语 | 含义 / 位置 |
|------|------|
| 底稿复核 | `routers/review.py` + `services/review_engine.py`，SSE 逐维度 LLM 复核 |
| 文档生成 | `routers/generate.py` + `services/document_generator.py`，模板大纲 → 逐章节生成 |
| 文档分析 | `routers/analysis.py` + `services/analysis_service.py`，多文档 → 框架 → 章节（带出处） |
| 审计报告复核 | `routers/report_review.py` + `services/report_review_engine.py`，规则 + LLM + 人工确认 |
| 首页聊天 | `routers/chat.py` + `services/chat_service.py`，`@` 引用知识库，`/` 快捷指令 |

## 审计报告复核核心对象（`models/audit_schemas.py`）

| 术语 | 含义 |
|------|------|
| StatementItem | 报表科目（期初/期末，合并/母公司 `company_*`），余额按来源 Sheet 原单位保存 |
| NoteTable | 附注表格（headers / header_rows / rows），`rows` 保持原值 |
| ReportSheetData | Excel Sheet 解析结果（raw_data、column_map 合并/公司列） |
| NoteSection | 附注层级树，用于判定表格所属科目与合并/母公司口径 |
| TableStructure | 表格行列语义（data/total/subtotal/sub_item；opening/closing 列），规则优先、LLM 兜底 |
| MatchingMap | 报表科目 ↔ 附注表格映射，`confirm_matching` 后落盘 |
| finding | `ReportReviewFinding`，一条待确认问题；`_make_finding` 统一构造，account_name ≤40 字 |
| 口径 | 合并 vs 母公司；`_is_parent_company_note` + 祖先章节判定，冲突时提示不静默改判 |
| unit_label / unit_multiplier | 来源声明的金额单位与换算为元的倍率；`source_unit_multiplier` 在 StatementItem 上 |
| 单位折算 | 只在报表 vs 附注余额核对时两侧折算为元（`_item_in_yuan` / `_scale_note`）；跨表规则按原值比较 |
| 容差 | `TOLERANCE=0.5` 元；报表 vs 附注用 `_unit_tolerance = max(0.5, 0.005×倍率)` |
| SKIP_INTEGRITY_KEYWORDS | 跳过通用纵向勾稽的科目关键词，走专项校验 |
| session | `ReportReviewSession`，`services/session_store.py` 存 `backend/data/sessions/{id}/` |

## 共享能力

| 术语 | 含义 |
|------|------|
| SSE | `utils/sse.py` 的 `sse_response` / `sse_with_heartbeat`，事件 `data: {"status": ...}` |
| 快照 | `services/json_snapshot.py`，review/generate/analysis 状态存 `backend/data/snapshots/{ns}/`，原子写、90 天清理 |
| 知识库 | `services/knowledge_service.py`，9 个库（含 notes 笔记库按 `date_folder` 存放） |
| openai_service | 多供应商 OpenAI 兼容 LLM 调用，`stream_chat_completion` |
| Word 导出 | 仿宋_GB2312 + Arial Narrow，页边距 3/3.18/3.2/2.54cm |

## 常用命令

- 后端测试：`python -m pytest tests -q`（cwd=`backend`）
- 前端类型检查：`npx tsc --noEmit`（cwd=`frontend`）
- 开发启动：根目录 `start.bat`（后端 9980 / 前端 3030）
- 打包：`npm run build` → 复制到 `backend/static/` → `python build_exe.py --skip-frontend`
