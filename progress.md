# 进度日志

## 2026-08-02 — invest-skills 合并（方案 A 升级 schema 3.6）

### 实施记录

- **侦察**（findings F1-F5）：聚合仓库与独立仓库两套分叉；聚合冻结 3.2/3.3 fixtures 已与 schema 3.6 引擎脱节（原始 invest-core 测试 2 error）。
- **用户确认**：方案 A —— 聚合跟随独立，升级 schema 3.6 + 动态 fixtures。
- **Phase 1**：撤销此前错误的覆盖同步，恢复聚合干净基线（顶层 3/3 OK）。
- **Phase 2 实施**：
  1. 聚合 `tests_support/revenue_fixtures.py` 升级为动态版（基于独立版），`_REVENUE_FORECAST` 解析支持 `REVENUE_FORECAST_DIR` 优先 + 多布局回退。
  2. 同步 invest-core / invest-framework 子目录为独立仓库最新版（scripts/tests/tests_support/references/agents/SKILL/.gitignore）。
  3. invest-core `tests_support/revenue_fixtures.py` 也用适配版；`test_cross_skill_conformance.py` 的 `_REVENUE` 解析加 `REVENUE_FORECAST_DIR` 优先（聚合布局 `parents[2]` 指向 invest-skills 而非 Projects）。
  4. 删除冻结 JSON fixtures（tests_support/fixtures/*）。
- **Phase 3 全量测试**（`REVENUE_FORECAST_DIR` 指向本地 revenue-forecast）：
  - 顶层 tests：3/3 OK
  - invest-core：36 tests / OK (skipped=1)
  - invest-framework：22/22 OK
  - invest-financials / valuation / sotp / moat / management / distribution / compare / psychology：全 OK
  - ruff：All checks passed
  - compileall：OK
- **Phase 4**：提交（不新建分支，main）+ push origin。

### 适配点（聚合布局必需）

- `tests_support/revenue_fixtures.py`：`_REVENUE_FORECAST` 支持 `REVENUE_FORECAST_DIR` + 多布局回退（独立/聚合均可）。
- `invest-core/tests/test_cross_skill_conformance.py`：`_REVENUE` 同样支持 `REVENUE_FORECAST_DIR`。

### 一致性

- invest-framework 子目录与独立仓库完全一致。
- invest-core 子目录与独立仓库仅 2 处预期差异（均为聚合布局必需的 env 适配）。

### 未提交

- 计划文件 task_plan.md / findings.md 新增。
