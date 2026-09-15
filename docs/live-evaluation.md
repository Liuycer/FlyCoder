# BAI 真实评测与扩展任务

当前本机配置为 BAI 的 `qwen3.8-flash`，通过 `api.b.ai` 的 Chat Completions 接口调用。连接组负责动作选择，代码理解与生成由该 LLM 执行。

## 真实调用与预算

首轮采用原有四个任务、种子 0、mock/原始 MaleCNS/累计 MaleCNS 三种控制器，共 12 次运行。共享 12 动作、3 次编辑预算，HTTP 请求总上限 144；实际使用 25 次 HTTP 请求、24 次逻辑 READ/EDIT 调用。

```bash
.venv-neural/bin/python scripts/benchmark_policies.py --live \
  --controllers mock malecns accumulating --seeds 0 --max-http-requests 144
```

HTTP 重试也消耗总请求预算；到达上限后不会再发请求。报告中的 `http_attempts` 是实际发起请求次数，`llm_calls` 是逻辑 READ/EDIT 次数。`usage_records` 保存供应商返回的 input/output token 数；未返回的用量保持缺失，不当作零。HTTP 失败可能没有 usage，已知 token 总数不保证包含失败请求的供应商计费。

用户本轮没有设置金额上限。报告金额字段为 `null`：没有 BAI 的适用单价、缓存折扣与失败计费规则，不能仅用 token 数推断最终账单。

## 多文件与更长任务

`benchmarks/extended-tasks.json` 增加三类任务，每个仓库两个可编辑模块、四项测试：

- invoice：数量、税额与 Decimal 的 HALF_UP 金额舍入。
- retry_schedule：指数退避、上限、次数与负值边界。
- records：空行、字段解析、名称规范化和非法数据。

固定候选在第 2/4/3 次编辑分别完成修复，要求控制器处理更长的失败/重试链。参考修复仍位于 sandbox 源仓库外。使用 20 动作、4 次编辑预算运行扩展评测：

```bash
.venv-neural/bin/python scripts/benchmark_policies.py \
  --suite benchmarks/extended-tasks.json --max-steps 20 --max-attempts 4
```

加 `--live --controllers mock malecns accumulating --seeds 0 --max-http-requests 100` 可运行单次真实 LLM 对照。此时固定候选的“第几次修复”不再适用，LLM 可一次修复，也可能失败。

## 解释限制

本机 ARM64 上顺序运行、每种真实任务/策略仅一次；LLM 响应、服务延迟与网络失败都有随机性，控制器顺序也未随机化。这是联调与探索性对照，不是统计上可靠的优劣排名。coding 错误会记录为 `coding_error`，不会冒充合法神经策略停止；神经后端或证据结构异常仍会让评测脚本报错。

多文件真实评测中观察到一次 `Remote end closed connection without response`，保留为失败，不选择性重跑。随后为 ConnectionError（包括 RemoteDisconnected）补充了有限重试，并验证重试仍受同一请求预算约束；该修复不追溯修改已经完成的评测结果。

历史四任务的固定候选结果仍见 `policy-benchmark.md`，不能与真实 LLM 结果混算。

## 本轮结果

| 策略 | 原四任务真实 BAI | 三个多文件任务真实 BAI | 多文件固定候选（3 种子） |
| --- | --- | --- | --- |
| mock | 4/4 | 3/3 | 9/9 |
| 原始 MaleCNS | 4/4 | 2/3 | 3/9 |
| 累计 MaleCNS | 4/4 | 3/3 | 9/9 |

随机策略只参加扩展离线对照，结果 9/9。扩展离线中，累计策略解除 6 次并列，但比原始策略增加了动作、coding 调用与模拟时间。真实 BAI 大多一次 EDIT 就修复代码，没有触发并列；不能用本轮真实结果证明累计策略的优势。原始 MaleCNS 的唯一真实失败来自服务端断连，不能归因于其动作策略。

21 次真实 benchmark 运行共发起 45 次 HTTP 请求，记录到 28,954 个 input tokens 与 31,467 个 output tokens。共 41 份 usage，4 次 HTTP 尝试没有对应 usage；金额仍需以 BAI 账单为准。额外的本地容器 BAI smoke 不包含在这组请求/token 汇总中。

原始记录保存在 `research/benchmark-bai-live-v1/`、`research/benchmark-extended-bai/`、`research/benchmark-extended-offline/`。可提交的汇总与报告 SHA-256 在 `benchmarks/results/live-local-2026-09-15.json`。
