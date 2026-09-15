# 神经运行验收与失败诊断

本次修改只收紧验收与保存决策现场，不改变动作分数、图、读出映射或并列时停止的规则。

## 两种结果分开报告

新运行记录使用 `schema=flycoder.run.v2`。验收脚本输出两个不同结论：

- `backend_verified`：逐步神经运行记录通过一致性检查。
- `task_solved`：存在合法的完整动作链，当前候选通过真实测试并进入 DONE。

默认验收允许有完整证据的并列、沉默或预算耗尽，输出明确警告与 `task_solved=false`。执行以下命令可要求任务必须成功：

```bash
.venv-neural/bin/python scripts/check_neural_run.py \
  --summary /absolute/path/to/run/summary.json \
  --require-done --report research/neural-run-check.json
```

这不是防伪签名，也不会重新执行代码；它检查保存的记录是否相互一致。不能用一份人为伪造且自洽的日志证明真实神经执行。

## 成功必须具有哪些证据

验收不再仅相信 summary 的 `status=done`。它逐步核对：

1. 神经策略身份、事件顺序、预算和合法动作集合。
2. 输入 observation、动作分数和最终选择是否一致。
3. TEST 的退出码、超时、发现/跳过的测试数与 unittest 输出；零测试或全部跳过不得成功。
4. TEST 前后、DONE 与 summary 的代码指纹是否一致；READ/TEST/RETRY/DONE 不能悄悄更改候选代码。
5. 状态是否能由事件顺序重建，summary 是否匹配最后状态。
6. 每步的当前 trace、图/映射/内核身份、读出计数与放电率是否相符。

历史日志没有这些证据字段，验收会提示重新运行，不会将旧日志升级或补造字段。

## 并列、沉默和后端错误的现场

选择动作前清除上次 trace。无论选择成功还是拒绝选择，都会保留当前决策：

- `observation`：本次输入特征；`allowed`：合法动作。
- `scores_hz`：全部五个动作分数。
- `best_score_hz`、`top_margin_hz`、`tied_actions`。
- `status`、机器可读的 `reason` 与 `selected_action`；拒绝时不会声称选出了动作。

Controller 的 error 事件还包含失败阶段、当前状态、候选文件指纹和本次 `neural_trace`。summary 保存相同的最后现场，避免将上一步成功动作误当作本次失败的数据。

原生后端新增各读出群体的总脉冲数、群体大小，以及操作系统、CPU 架构、Python/NumPy 版本、内核源码与二进制哈希。沉默检查在这些数据保存之后执行。

只有错误原因、没有本次现场，或用上一步 trace 冒充本次现场的记录都会验收失败；普通后端异常不会因为错误文本碰巧以“分数并列”开头而通过。

## Mac/Linux 对比结果

已读取旧 Linux workflow `34859611142` 的产物，并与本次 Mac 离线运行记录比较：

| 项目 | 结果 |
| --- | --- |
| 图 SHA-256 | 相同，前缀 `346b8af85a11` |
| 读出映射 SHA-256 | 不同：Mac `f503ae431d3c`，Linux `3b25548a5476` |
| 首次刺激 SHA-256 | 相同 |
| 首次放电数组 SHA-256 | 不同 |
| 第 3 个动作 | Mac TEST，旧 Linux EDIT |
| 旧 Linux 第 5 步并列现场 | 未保存，不能从第 4 步 trace 反推准确分数 |

这说明差异不只是验收脚本的处理方式。映射不同影响动作评分，但不能单独解释完整放电数组的差异。相同图与当前刺激也不足以排除初始状态、运行时或数值执行差异；旧日志缺少环境/内核元数据，因此不能确定为某个 CPU 或编译器问题。

后续提交 `fa0ef3a` 增加了固定映射受控重放和独立的 `-ffp-contract=off` 诊断内核，用来把输入/映射差异与浮点数值执行差异分开。

## 受控重放与浮点收缩诊断

使用 [run 34864923823](https://github.com/Liuycer/FlyCoder/actions/runs/34864923823) 在 `fa0ef3a` 上传的受控重放证据，固定观察序列和 `diagnostics/reference-map.json`。此时 macOS 与 Linux 的图和读出映射哈希一致（均为 `346b8af85a11…` 与 `f503ae431d3c…`）。对比结果如下：

| 对比 | 输入 | 放电 | 分数 | 内部状态差异 |
| --- | --- | --- | --- | --- |
| macOS 默认内核 vs Linux 默认内核 | 一致 | 不一致 | 第 1 次一致，第 2/3 次不一致 | `v`、`g`、`refractory`、队列/活动状态等 |
| Linux 默认内核 vs Linux no-contract 内核 | 一致 | 一致 | 一致 | 无 |
| macOS no-contract vs Linux no-contract | 一致 | 一致 | 一致 | 仅 `v`、`g` |

Linux 默认内核与诊断内核记录的二进制哈希同为 `b46d3c318f7a…`；关闭浮点收缩没有改变本次 Linux 上的放电、分数或数组。这只说明该编译选项在本次 Linux 构建中没有产生差异，不能据此排除 macOS 侧浮点收缩的影响。

在图、初始数组、映射和刺激序列一致的对照中，macOS 默认内核与 no-contract 内核的三次放电数组均不同；macOS 关闭浮点收缩后，三次完整放电数组和动作分数均与 Linux 一致。因此，关闭 macOS 侧浮点收缩足以消除本次固定回放中的放电差异。

关闭收缩后，macOS/Linux 的内部电压 `v` 和电导 `g` 仍有差异，其具体来源尚未确定。该实验没有证明所有数值差异均已消除，也不保证更长序列或其他任务跨平台逐位一致。默认内核和策略没有因此改变，验收仍以同平台重放和逐步证据为准。

同一次 Linux 真实运行仍使用演示产生的映射 `3b25548a5476…`，第 5 步在合法 READ/TEST 并列处停止：两个分数均为 31.8 Hz，`top_margin_hz=0.0`。严格报告结论是 `backend_verified=true, task_solved=false, outcome=tied_scores`。

只读对比两次记录：

```bash
.venv-neural/bin/python scripts/compare_neural_runs.py \
  /absolute/path/to/mac/run/summary.json \
  /absolute/path/to/linux/run/summary.json \
  --output research/platform-comparison.json
```

对比工具会明确提示旧日志缺少失败现场，不会拿上一动作补位。

## 已执行验证

- 神经 Python 环境：55 项项目测试全部通过。
- 基础 Python 环境：55 项测试运行通过，其中 2 项可选 NumPy 测试跳过。
- 覆盖缺少 TEST/DONE、伪通过、全跳过、过期指纹、错误 summary、并列现场、沉默、过期 trace、伪装错误原因、预算耗尽、非有限值和不合法 JSON 结构等反例。
- 新版本真实 MaleCNS + mock coding demo 完成 8 个动作，严格 `--require-done` 验收通过。
- `fa0ef3a` 的 GitHub Actions checks 与神经工作流均通过；神经 run 34864923823 已上传受控重放、no-contract 重放、内核元数据和严格验收报告。
- 没有发起 BAI/API 调用，没有构建神经 Docker 镜像。
- 修改已推送到 GitHub 并在远程 CI 中复验；神经 Docker 镜像仍待完整构建和运行实测。

本地证据：`research/evidence-tests.log`、`evidence-base-tests.log`、`evidence-check.json`、`evidence-runs/`、`platform-comparison.json`。它们不进入普通源码提交。
