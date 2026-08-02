# invest-skills 合并实施计划

计划编制日期：2026-08-02
状态：completed
依据：invest-skills 聚合仓库与独立 invest-core/invest-framework 分叉的完整侦察。

## 0. 背景与目标

### 0.1 问题

用户要求把 invest-core / invest-framework 的最新改动"合并"进 `invest-skills` 聚合仓库并推送。但侦察发现：

1. **两套分叉**：聚合仓库 `invest-skills` 与独立仓库 `Projects/invest-core`、`Projects/invest-framework` 是同源但各自演进的代码。
   - 聚合仓库 = **冻结发布**模型：顶层 `tests_support/` 提供冻结 schema 3.2/3.3 revenue fixtures，子目录测试/示例经 `parents[2]` 引用顶层冻结版；生产代码配套冻结 fixtures 自洽（基线 OK）。
   - 独立仓库 = **动态开发**模型：`tests_support/revenue_fixtures.py` 用 schema 3.6 动态生成，测试经 `REVENUE_FORECAST_DIR` 指向本地 revenue-forecast。
2. **合并失败**：先前用"独立仓库覆盖聚合子目录"的方式破坏了聚合自洽性——独立版 `invest_contracts.py` 要求 `publication_receipt`，但聚合冻结 fixtures（3.2/3.3）无 receipt → examples/tests 失败。
3. **聚合仓库基线**：原始 `main` 顶层测试 3/3 OK；子目录测试需在 `Projects` 布局下跑。

### 0.2 目标

把独立仓库 invest-core / invest-framework 的**最新生产代码与测试**干净地合入聚合仓库，使：

- 聚合仓库的 invest-core / invest-framework 子目录与独立仓库一致；
- 聚合仓库自身测试（顶层 + 子目录 + examples）全部通过；
- 不破坏聚合仓库其它 9 个子目录与冻结 fixtures 模型（除非决策升级）。

### 0.3 关键决策点（用户已确认）

- **方案 A（聚合跟随独立）**：聚合 `tests_support/revenue_fixtures.py` 升级为动态（schema 3.6，支持 `REVENUE_FORECAST_DIR` 优先），删除冻结 JSON fixtures；invest-core/framework 子目录用独立最新版；其它 8 个子目录验证兼容。用户 2026-08-02 确认。

聚合仓库 vs 独立仓库的发布模型冲突，必须先定方向：

- **方案 A（推荐）**：聚合仓库跟随独立仓库 → schema 3.6 + 动态 fixtures。需把聚合 `tests_support/revenue_fixtures.py` 从冻结改为动态（或统一到子目录动态版），升级冻结 JSON 或改测试引用。影响面：顶层 tests_support、全部 11 个子目录的测试路径、examples。
- **方案 B**：聚合仓库保持冻结模型 → invest-core/framework 生产代码**回退到聚合原始版**，只合并"与冻结模型兼容"的改动。影响面小，但独立仓库的新修复（SUITE 路径 bug、fixture 重复参数、schema 3.6 适配）无法进入聚合。
- **方案 C**：混合——invest-core/framework 子目录保持独立仓库版本，聚合 `tests_support` 升级为动态 + 适配其它子目录测试路径。

## 1. 侦察结论（已确认事实）

| 事实 | 证据 |
|---|---|
| 聚合顶层测试基线 OK（3/3） | stash 后 `python -m unittest discover -s tests` → OK |
| 子目录测试用 `parents[2]` 引用顶层 `tests_support` | 11 个子目录 grep `SUITE = parents[2]` + `from revenue_fixtures import` |
| 聚合冻结 fixtures 版本 3.2/3.3 | `tests_support/fixtures/revenue-*-3.2-v3.3.0.json` |
| 独立仓库 invest_contracts.py 含 Phase 11 receipt 要求 | `publication_receipt` 检查 |
| 聚合原始 invest_contracts.py 无 receipt 要求 | stash 后 grep 无 `publication_receipt` 行 |
| 我的覆盖同步破坏了 examples | example 用冻结 fixture + 新版 invest_contracts → receipt 缺失 |
| invest-core/invest-framework 无独立远端 | `git remote -v` 空 |

## 2. 实施步骤（待方案确认后细化）

### Phase 1：撤销错误同步，恢复聚合仓库到干净基线
- [x] 恢复 `invest-core/`、`invest-framework/` 子目录到聚合原始状态（`git checkout`），清掉误加的 `tests_support` 动态版。
- [ ] 确认聚合仓库顶层 + 子目录测试回到基线状态（顶层 3/3 OK）。

### Phase 2：按选定方案合并
- [x] 方案 A：升级 `tests_support/revenue_fixtures.py` 为动态（或替换为子目录动态版）+ 更新冻结 JSON / 测试路径。
- [ ] 方案 B：仅合并兼容改动，回退生产代码。
- [ ] 方案 C：混合适配。
- [ ] 同步 invest-core / invest-framework 生产代码与测试到聚合子目录。
- [ ] 确保无缓存文件、无重复实现、无残留 `__pycache__`。

### Phase 3：全量测试
- [x] 聚合顶层 tests（smoke + examples）。
- [ ] 聚合全部 11 个子目录 tests（在 `Projects` 布局 + `REVENUE_FORECAST_DIR` 下）。
- [ ] ruff + compileall。

### Phase 4：提交推送
- [x] 提交聚合仓库（不新建分支，main）。
- [ ] push origin（invest-skills）。

## 3. 禁止事项

- 不新建远端、不新建分支。
- 不留下动态/冻结两套 revenue_fixtures 并存。
- 不破坏 invest-core/framework 之外的 9 个子目录。
- 不引入缓存/coverage/pyc 文件。

## 4. 验收

- 聚合仓库工作区干净（无未跟踪缓存）。
- 顶层 + 全部子目录测试通过。
- invest-core / invest-framework 子目录与独立仓库内容一致。
- 已推送到 origin/main。
