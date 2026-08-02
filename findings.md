# 研究发现

## 2026-08-02 invest-skills 合并侦察

### F1：两套分叉
- `invest-skills` 聚合仓库 = 冻结发布模型（顶层 `tests_support/` 提供冻结 schema 3.2/3.3 revenue fixtures；子目录测试/示例经 `parents[2]` 引用顶层冻结版）。
- 独立 `Projects/invest-core`、`Projects/invest-framework` = 动态开发模型（schema 3.6 + 动态 fixtures + `REVENUE_FORECAST_DIR`）。
- 聚合原始 invest_contracts.py（1415 行，无 publication_receipt 要求）与独立版（1451 行，含 Phase 11 receipt 要求）diff 2866 行——非补丁关系，各自演进。

### F2：聚合基线在 schema 3.6 引擎下已脱节
- 聚合顶层 tests（CLI smoke + examples）原始 3/3 OK（不依赖 fixtures）。
- 聚合 invest-core 原始测试在 `REVENUE_FORECAST_DIR`=schema 3.6 下有 2 error（冻结 3.2/3.3 fixtures 与 3.6 引擎不兼容）。
- 聚合 invest-financials（冻结 fixtures）9/9 OK。

### F3：子目录测试路径约定
- 全部 11 个子目录测试用 `SUITE = parents[2]` + `from revenue_fixtures import load_revenue_fixture`。
- 在聚合布局 `invest-skills/invest-X/tests/`，`parents[2]` = `invest-skills` → `SUITE/tests_support` = 顶层 `tests_support`（冻结版）。
- 动态版 `revenue_fixtures.py` 顶部 `_REVENUE_FORECAST = parents[2]/revenue-forecast`，在聚合布局解析到 `invest-skills/revenue-forecast`（不存在）→ 需支持 `REVENUE_FORECAST_DIR` 优先。

### F4：动态 fixtures 可用性
- 动态版 `revenue_fixtures.py` 只要 `REVENUE_FORECAST_DIR`/`Projects` 在 path 上即可 import（已验证）。
- 独立版 invest-core/framework 测试全绿（36/36-1 skip、22/22）。

### F5：合并方案（用户已确认）
- **方案 A**：聚合跟随独立 → schema 3.6 + 动态 fixtures。把聚合顶层 `tests_support/revenue_fixtures.py` 升级为动态版（支持 `REVENUE_FORECAST_DIR`），删除冻结 JSON fixtures，invest-core/framework 子目录用独立最新版，其它 8 个聚合独有子目录验证兼容。

## 决策
- 采用方案 A（用户 2026-08-02 确认）。
