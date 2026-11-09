---
inclusion: manual
---

# 领域边界与债务 burn-down

需要改 `backend/app` / `audit-platform/frontend/src` 跨模块 import 时用 `#domain-boundaries`（或先读本文件）。

## 硬规则

1. **先改 ownership，再写代码**：新跨域 import 之前，更新 `docs/architecture/domain-boundaries.json` 的 `paths` / `may_depend_on`。
2. CI / 本地：`python backend/scripts/check/check_domain_boundaries.py` 必须 exit 0（只拦 **新增** 边）。
3. 债务缩小后同一 PR 内 `--write-baseline`；**禁止**用 baseline 吞并发 WIP。
4. 现网 baseline **4761**（2026-09-08）；过程数字 ~5349 已作废。

真源：`docs/architecture/DOMAIN_DEBT_BURNDOWN.md` · PAC 移交：`.kiro/specs/platform-architecture-convergence/basis/T23-post-closure-followups.md`。
