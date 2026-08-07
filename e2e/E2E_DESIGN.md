# 壁仞 invest E2E —— 对抗式审查与完善设计

日期：2026-08-07 ｜ 状态：设计定稿，harness 已实现（`run_biren_invest_e2e.py` + `expected/`）

## 对抗式审查：对当前"一次性手动运行"的拷问与回答

### Q1. 以后每次都能用吗？（可重复性）
**拷问**：`company_orchestrator.py --output-dir` **拒绝覆盖已存在目录**——同样的命令第二次运行
直接报错。且当前是手动 bash 运行，无标准入口、无退出语义。
**结论**：❌ 不可重复。
**修复**：harness 每次在全新临时运行目录（`.runs/<input_hash8>/<seq>/`）执行；成功/失败都有
明确退出码；同一输入重复运行结果必须逐字节一致（确定性复现检查）。

### Q2. 每次都能检验每一个步骤吗？（步骤覆盖）
**拷问**：当前只目测了 receipt pass + bundle 复核 + 几个数字。若某个中间步骤静默退化
（如 financials 的 revenue 不再等于预测的 effective_revenue、valuation 方法漂移、
report 丢失驱动章节），测试仍会"pass"。
**结论**：❌ 无步骤级断言。
**修复**：8 步显式断言（见 harness 设计）：
1. 输入 forecast 是有效 formal 产物（publication_receipt 结构 + result_sha256 一致性；
   可用 revenue-forecast 引擎强验证）
2. manifest 通过契约校验（invest-framework 的 manifest 校验器）
3. orchestrator 全链路运行成功（新临时目录）
4. financials：合规 receipt 存在 + terminal net_income ≈ 期望值
5. valuation：ps 方法 + equity 值 ≈ 期望值
6. SOTP：segment 覆盖 + equity 值 ≈ 期望值
7. bundle：module_counts + 上游哈希链完整
8. receipt：status=pass、freeform=false、formal_report_sha256 == sha256(report.md)；
   报告含关键章节（驱动/价值表）

### Q3. 目录内容变动时测试还有效吗？（抗变动性）
**拷问**：
- invest-skills 代码演化（orchestrator/manifest 契约变）→ 测试会怎样？
- revenue-forecast 重新生成预测 → 输入变化 → 测试会怎样？
- biren_forecast.json 被删/被改 → 测试会怎样？
**结论**：❌ 当前无防护——任何变动下测试都会"看起来能跑"但结果漂移不被察觉。
**修复**：golden 按**输入 forecast 的 sha256** 键控。输入变了 → 哈希变 → golden 查无此键 →
**显式失败**（提示"输入已变，请核对新预测后更新 golden"），而不是静默放行。
代码演化 → golden 哈希不匹配 → 显式失败（这正是要的信号：要么回归，要么有意更新 golden）。
文件缺失 → harness 启动时校验输入存在并给出明确错误。

### Q4. 需要 expected 结果目录吗？
**结论**：**需要**。golden（`expected/expected-<input_sha256>.json`）记录：bundle/report/receipt
哈希、各模块关键数值（terminal net_income / equity / sotp）、module_counts、运行时的
invest-skills 与 revenue-forecast 的 HEAD commit。目的是捕获"receipt pass 但数值/产物静默漂移"
的回归。golden 更新是**有意行为**（`--update-golden`），不是测试失败后随手改。

### Q5. 如何控制变量？
| 变量 | 控制方式 |
|---|---|
| 输入预测 | 默认 `biren_forecast.json`；可用 `--forecast <path>` 指定；记录输入 sha256 进 golden 键 |
| manifest | 提交为 fixture（`biren_manifest.json`），测试用同一份 |
| 仓库版本 | golden + 每次运行报告记录 invest-skills / revenue-forecast 的 HEAD commit |
| 输出目录 | 每次全新临时目录（`.runs/`），互不覆盖 |
| 环境 | `REVENUE_FORECAST_DIR` 必须指向 revenue-forecast（harness 校验并显式注入）；Projects 布局前置检查 |
| 确定性 | orchestrator 纯本地、无随机/时钟依赖 → 同输入同输出，哈希可比对（并做双跑一致性断言） |
| 外部依赖 | 无网络/无 dayu/无 worker——纯计算，可离线重复 |

### Q6. 测试失败时如何区分"回归"与"环境问题"？
harness 每一步的失败信息明确标注步骤名 + 期望/实际；输入校验失败（文件缺失/哈希漂移）与
计算失败（数值/哈希不匹配）分开报错。golden 不匹配时打印 diff 摘要。

### Q7. 如何证明这个测试真的能抓回归？（自证）
**变异测试**：故意改一个输入（如 manifest 的 net_margin base -0.845→-0.80，或改 forecast 一个数字），
测试必须**失败**；再改回 → 必须**通过**。已实测（见 progress.md）。

---

## 实现

- `run_biren_invest_e2e.py`：harness（8 步断言 + golden 比对 + 双跑确定性 + `--update-golden` + 版本记录）
- `expected/expected-<input_sha256>.json`：golden（首次由 `--update-golden` 生成）
- 运行：`python run_biren_invest_e2e.py`（exit 0=全绿；非 0=失败，带步骤定位）

## 使用约定

- 预测重新生成后：核对新预测 → `--update-golden` 刷新 → 提交 golden（与新预测一并版本化）。
- invest-skills 有意变更后：审查 diff → `--update-golden` 刷新。
- 任何"未预期"的失败：视为回归信号，先查原因，不直接更新 golden。
