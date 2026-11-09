---
inclusion: manual
---

# 服务边界速查（AI 入口 / 编辑锁）

> 用途：纠正"多实现并存=该删"的误判，明确各入口职责，防止后人误删现役实现或重复造轮子。
> 引用方式：`#service-boundaries`（按需加载，不常驻上下文）。

## AI 服务 5 个入口（各司其职，不可合并）

| 入口 | 层次 | 职责 | 调用约束 |
|------|------|------|---------|
| `llm_client.chat_completion()` | 客户端 | httpx 直连 vLLM + 熔断器；无 DB 依赖 | 多数 `wp_llm_prompts`/`role_ai`/`pm` 走这条；vLLM 拒多 system 消息（已 `_merge_system_messages()`） |
| `AIService(db)` | 底层抽象 | 屏蔽模型差异：`chat_completion`/`embedding`/`ocr_recognize`/`get_active_model`/`switch_model`/`health_check` | **需真实 DB session** 查 active model（OCR/knowledge/contract/wp_fill 用） |
| `UnifiedAIService(db)` | 门面 | 包 `AIService`(核心)+`AIPluginService`(插件)+`UnifiedOCRService`(OCR)；additive，不改原服务 | 需要"核心能力+插件管理"一站式时用；纯 LLM 调用别绕这层 |
| `WpAIService` | 底稿域 | 分析性复核 + 函证对象提取 + 审定表核对 + AI 内容溯源包装（`wrap_ai_content`/`wrap_ai_output` 供门禁 `AIContentMustBeConfirmedRule` 校验确认状态） | 底稿域 AI 内容必经此包装，否则门禁拦截 |
| `NoteAIAssistantService(db)` | 附注域 | `suggest_dynamic_rows`(辅助账→动态行建议) / `generate_paragraph_from_workpaper`(底稿摘要→段落) / `check_wp_tb_consistency`(wp_data↔TB 校核) | 附注专用，依赖 DB session + 可选 LLM client |

选用决策：
- 纯对话/无状态 → `llm_client`
- 需查激活模型/embedding/OCR → `AIService(db)`
- 要插件管理 → `UnifiedAIService(db)`
- 底稿/附注业务语义 → 对应域服务（输出必走溯源包装）

## 编辑锁（v2 统一，v1 已下线）

> ✅ 2026-06-13 完成 editing-lock-v1-v2-consolidation spec：v1 已删除（service/router/ORM/测试），底稿锁收口进 v2 `resource_type='workpaper'`。

| 维度 | 统一后（v2） |
|------|-------------|
| service | `editing_lock_service` |
| router | `editing_locks.py` 前缀 `/api/editing-locks` |
| 表/ORM | `editing_locks` / `EditingLock` |
| 锁维度 | `(resource_type, resource_id)`（通用，部分唯一索引保活跃锁≤1） |
| 前端 | `useEditingLock.ts` 所有 resourceType 统一走 `/api/editing-locks/{type}/{id}` |

V073 迁移了存量活跃锁；`workpaper_editing_locks` 表在 `KNOWN_ALLOWLIST` 中（V075 启动时 DROP）。

## schema 漂移自检 + 迁移弹性 — 是优点不是 bug

`main.py` lifespan 的 `_run_schema_drift_check`（ORM↔DB 漂移，60s timeout 不阻塞启动）+ `_run_migrations`（单文件失败隔离、写 `schema_migration_failures` 表、health 暴露 degraded）是有意的治理设计，**无需"修复"**。
