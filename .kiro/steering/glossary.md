---
inclusion: manual
---

<!--
注意：本文件描述的是另一套审计平台（Vue + PostgreSQL，wp_code/render-config/Univer 等），
与本仓库 GT_digao（React + FastAPI，审计报告复核/底稿复核/文档生成/文档分析）不是同一项目。
改为 manual，仅在明确需要时用 #glossary 引用；本仓库术语见 project-glossary.md。
-->

# 领域术语速查（另一审计平台）

> 审计平台专用术语。对话中直接使用缩写/术语，无需每次解释。

| 术语 | 含义 |
|------|------|
| wp / 底稿 | working paper，审计工作底稿 |
| wp_code | 底稿编码（如 A1/D2-1/F3A），唯一标识底稿类型 |
| wp_index | 底稿索引表（wp_code 在此表，WorkingPaper 主表无 wp_code，需 JOIN） |
| componentType | 前端渲染类型（如 audit-sheet/a-program-console） |
| render-config | `GET /workpapers/{id}/render-config` 返回的渲染配置 |
| RENDERER_DISPATCH | 后端 componentType→render 策略函数映射（11 种） |
| htmlRendererRegistry | 前端 componentType→Vue 组件映射（37 种，单一来源） |
| _WP_CODE_OVERRIDE | wp_code→componentType 精确映射（wp_code_overrides.json，550+ 条，mtime 热重载） |
| 程序表 | 审计程序清单（每个循环的 xxxA 底稿） |
| 审定表 | 科目审定汇总（每个循环的 xxx-1 底稿，回写 trial_balance） |
| auto_data_source | 程序表步骤的自动取数标识（如 adjustment_count_aje） |
| resolver | `auto_data_resolvers._REGISTRY` 中注册的取数函数（35+ 个） |
| field_overrides | 用户对自动值的手动覆盖（per project/year/scope） |
| render schema | 底稿渲染 YAML 配置（`backend/data/.../wp_render_schema/`，441 个） |
| guidance | 底稿编制指导（`backend/data/wp_guidance/` 静态 JSON，343 个） |
| tb / 试算表 | trial_balance 表，各科目审定额汇总（v2 正数口径） |
| tb_balance | 余额表原始数据（v1 口径：借正贷负，前端方向列显示用） |
| tb_ledger | 序时账明细（损益类发生额从此取） |
| tb_aux_balance | 辅助维度余额表（按维度冗余存储，校验须 GROUP BY aux_type） |
| audited_amount | 审定数（报表/审定表取数权威字段） |
| unadjusted_amount | 未审数（trial_balance 列） |
| AJE | 审计调整分录 |
| RJE | 重分类调整分录 |
| direction | 科目借贷方向字段（SELECT tb_balance 返前端必带，漏查则备抵科目错） |
| EventBus | 进程内事件总线（publish=EventPayload 走 handlers+SSE / broadcast_raw=纯 SSE） |
| WORKPAPER_SAVED | 底稿保存事件（触发一致性检查+C/F/D~N 循环联动） |
| CCR / cross-ref | 跨底稿交叉引用（cross_wp_references，ref_index chip 可跳转） |
| address_registry | 地址坐标注册表 V1（5 域：tb/report/note/wp/aux；运行时动态目录，公式选址用） |
| address_registry_v2 | 地址坐标静态依赖图（l2 语义 / l3 依赖 / stale 影响分析） |
| ACNR | 地址坐标名称注册中心（Address Coordinate & Naming Registry）；平台级目录真源，收敛 classification/种子/I/E/labels/CCR；见 `docs/proposals/address-coordinate-name-registry-architecture.md` |
| addr_id | ACNR 稳定主键 `{wp_code}/{sheet_code}/{coordinate_key}`，不因 sheet 改名而变 |
| ledger_datasets | 数据集版本治理（staged→active→superseded，可见性靠 status 非 is_deleted） |
| get_active_filter | 四表查询统一入口（禁止裸写 `TbX.is_deleted==False`） |
| B15 | 重要性水平底稿（redirect 到 Materiality 模块） |
| A~S 循环 | 审计循环分类（A报表/调整 B计划 C控制 D~N实质性 S专项，14 大类） |
| d-form-* | D 类检查表 5 子模式（table/paragraph/qa/confirmation/review） |
| Univer | 前端 Excel 编辑组件（替代 OnlyOffice，复杂公式底稿用） |
| OnlyOffice | 文档编辑服务（docx/复杂 xlsx，secret 硬编码 onlyoffice-dev-2026） |
| migration_runner | 运行时 SQL 迁移（`backend/migrations/V*.sql`，非 alembic） |
| ResponseWrapperMiddleware | 包装所有 2xx JSON 为 `{code,message,data}` 信封 |
| codegraph | 代码知识图谱 MCP（搜符号/调用链/影响面，优先于 grep） |
| gt-plan MCP | 领域 MCP：wp_lookup/spec_status/migration_status（`tools/gt-plan-mcp/`） |
| MCP 铁律 | 选型阶梯见 memory.md §MCP 使用铁律；postgres/github/docker 默认只读 |
| RTK | CLI token 压缩代理（shell 命令加 `rtk` 前缀） |
| spec 三件套 | requirements.md + design.md + tasks.md |
| PBT | Property-Based Testing（hypothesis 框架，max_examples=5） |

## 审计 5 角色

| 角色 | 职责 |
|------|------|
| 审计助理 | 现场执行：底稿编制、取数、OCR、调整分录录入 |
| 现场经理 | 项目管理：进度把控、底稿一级复核、任务分派 |
| 业务合伙人 | 审计判断：重大事项决策、审计意见、签字 |
| 质量控制复核合伙人 | 质控：QC 28 条规则、独立质量复核（IRP） |
| EQCR 技术复核人 | 项目质量控制复核（Engagement Quality Control Review），技术层面独立复核 |

## 代码决策阶梯（ponytail 原则）

> 每次写代码前从第 1 步开始问，停在第一个能解决问题的层级。

1. **需要存在吗？** → 不需要就不写（YAGNI）
2. **标准库/内置能做？** → 用 Python stdlib / Web API / Vue 内置
3. **平台原生能力？** → 用 el-* 组件 / HTML 原生 / PG 内置函数
4. **已有依赖能做？** → 用项目已装的库（不引入新依赖）
5. **一行/一个配置能搞定？** → 写最少代码
6. **以上都不行** → 写最少够用的实现

底线：安全校验 / 错误处理 / 权限检查 / 数据验证 —— 永远不砍。少写的是业务代码，不是防御代码。
