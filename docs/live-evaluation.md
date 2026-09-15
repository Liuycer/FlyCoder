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

## 外部题库：llm-bug-bench

`benchmarks/` 的任务由我们自己编写。为检验同一套控制器能否处理真实仓库风格的题目，改从外部题库 `llm-bug-bench` 取题，在本地容器内用真实 BAI + MaleCNS 运行。题库仓库保持只读，任务副本、日志与证据一律放在不入库的 `research/`：

```text
research/llm-bug-bench-<id>/input/            # 交给容器的只读任务副本
research/llm-bug-bench-<id>/input/tests/test_original.py   # pytest 风格 → unittest 薄包装
research/llm-bug-bench-<id>/source-manifest.json           # 三个源文件的 SHA-256，显式排除 fixed.py
research/llm-bug-bench-<id>/<run-id>/                       # summary.json / events.jsonl / changes.patch / repo 快照
```

FlyCoder 固定运行 `python -m unittest discover -s tests -v`，而题库测试是不带 `TestCase` 的 pytest 风格函数，因此薄包装用 `load_tests` 把原函数逐个包成 `unittest.FunctionTestCase`，并要求数量与题目声明一致（001 六个、002 五个），数量不符直接抛错。包装层不修改任何断言；参考实现 `fixed.py` 不进副本，避免模型抄答案。

构建与运行（`FLYCODER_TARGET_REPO` 指向任务副本，`LLM_TIMEOUT` 视 BAI 延迟上调）：

```bash
FLYCODER_TARGET_REPO=./research/llm-bug-bench-002/input \
  docker compose -f docker-compose.neural.yml -f docker-compose.local.yml build flycoder-neural
LLM_TIMEOUT=120 FLYCODER_TARGET_REPO=./research/llm-bug-bench-002/input \
  docker compose -f docker-compose.neural.yml -f docker-compose.local.yml run --rm \
  flycoder-neural --llm chat-completions --repo /workspace --editable buggy.py \
  --seed 0 --runs /data/runs/llm-bug-bench-002 --tie-extra-windows 2
```

本机 arm64 结果，两次均由 `scripts/check_neural_run.py` 判为 `backend_verified=true, outcome=task_solved`：

| 题目 | baseline | 动作链 | 修复 | LLM 调用 |
| --- | --- | --- | --- | --- |
| 001 排序比较符号反向 | 6 项 FAIL | READ → EDIT → TEST → DONE（4 步） | 单行 `<` 改 `>` | 2 |
| 002 `parse_json` 缺空值/异常处理 | 5 项 3 ERROR | READ → EDIT → TEST → READ → RETRY → EDIT → TEST → DONE（8 步） | 空串/空白返回 `None` + `try/except` | 4 |

002 第一次 EDIT 删掉了 `parse_json` 本身，TEST 报 `ImportError`，控制器选择 RETRY 后第二次 EDIT 才通过：这正是“测试证据驱动重试”而非法则回退或假装成功的例子。002 的一次前置尝试在默认 `LLM_TIMEOUT` 下以连接超时告终，记录保留在 `research/llm-bug-bench-002/c2e8b410ebf443748a5ba59f2fc9f786/`，与成功运行分开保存。

### 一条命令跑一批题目

上面那串手敲命令已固化成 `scripts/run_task_bench.py`：准备不可变任务副本（含 unittest 薄包装、`fixed.py` 排除、逐文件 SHA-256）→ 可选 baseline 预检 → 整个批次只 `docker compose build` 一次 → 逐 (题目, seed) 在容器内运行并把 stdout/stderr 落盘 → 从命名卷导出证据 → `check_neural_run.py` 严格复验 → `report_run.py` 渲染审查报告 → 写批次汇总。

```bash
python3 scripts/run_task_bench.py \
  --source ~/Documents/ChatGPT/llm-bug-bench/tasks/basic \
  --ids 003_fibonacci 004_max_value 005_dict_merge \
        006_file_reader 007_palindrome 008_url_parser \
  --seeds 0 --output research/bug-bench-runs --batch basic-003-008
```

批次产物：`batch.json`（参数、源文件清单、逐题结果、实际模型、HTTP 请求数、样本限制）、`summary.md`（通过 / 策略停止 / 需关注三档计数与逐题表格）、`logs/<task>-seed<n>.log`、`runs/<task>-seed<n>/<run-id>/`（原始证据 + `check.json` + `review.md`）。题库目录始终只读，只有 `inputs/` 下的副本会挂进容器；生成的修复只作证据，从不自动合并。

其它开关：`--dry-run` 只打印计划不调用 LLM，`--no-build` 复用已有镜像，`--max-http-requests` 在请求预算耗尽后停止启动新运行，`--limit` 截断题目×seed 组合，`--require-done` 让存在未解题的批次返回非零退出码。统计仍是单次运行的小样本：一条记录只说明“该题该 seed 在该模型与提示下的一次结果”，不代表该模型的总体能力。

本机 arm64 结果，六题全部 `backend_verified=true, outcome=task_solved`，每条 4 个动作、2 次 LLM 调用（共 12 次 HTTP 请求，无重试）：

| 题目 | baseline | 修复 | token 入/出 |
| --- | --- | --- | --- |
| 003 斐波那契边界 | 5 项 FAIL | `n == 1` → `n <= 1` | 2,397 / 1,297 |
| 004 负数取最大值 | 5 项 FAIL | `max_val = 0` → `numbers[0]` | 2,350 / 919 |
| 005 可变默认参数 | 5 项 FAIL | `updates={}` → `None` 哨兵 + 复制返回 | 2,817 / 1,203 |
| 006 文件读取异常 | 3 项 FAIL | `with open(...)` + `FileNotFoundError` 返回空列表 | 2,510 / 689 |
| 007 回文边界与索引 | 7 项 FAIL | `chars[n - i]` → `chars[n - 1 - i]`，空串返回 `True` | 3,626 / 1,190 |
| 008 无值查询参数 | 5 项 FAIL | `split("=", 1)`，无 `=` 时值为空串 | 2,901 / 1,309 |

005 触发一条审查标记：`merge_dicts(base, updates={})` → `merge_dicts(base, updates=None)`。这正是可变默认参数的标准修法（题目描述亦然），但签名变更仍按流程留给人工确认，报告不因测试全绿而自动放行。

### 模型选择

第一次 003 尝试用 `qwen3.8-flash`：3 次成功调用背后是 8 次 HTTP 尝试（5 次超时），容器创建后约 12 分钟仍以 `LLM connection failed or timed out` 结束。换用 `deepseek-v4.1-flash` 后，同一批六题从构建到导出共约 1 分钟，每题 10–11 秒、2 次调用 2 次 HTTP 尝试。超时尝试的证据单独保留在 `research/bug-bench-runs/basic-003-008-attempt1-aborted/`，未被覆盖或重写。

运行记录现在写明实际使用的模型：`summary.json` 记录 `llm_model`（适配器自报），审查报告与 `batch.json` 一并展示。`basic-003-008` 这批运行早于该字段，`batch.json` 因此用 `llm_model_source` 标明模型取自批次时的宿主 `LLM_MODEL`，而非逐次记录。

## 审查报告

`scripts/report_run.py` 把一份运行目录渲染成人可读的 Markdown，不必翻 `summary.json`：结论（✅ `task_solved` / ⚠️ 合法策略停止 / ❌ 证据不成立）、动作链、每个文件的 `−x / +y` 与完整 diff、Review flags、LLM 请求与 token、神经后端指纹、baseline 失败明细。

```bash
.venv-neural/bin/python scripts/report_run.py \
  --run-dir research/llm-bug-bench-002/<run-id> \
  --check-report research/llm-bug-bench-002/check-report.json \
  --output research/llm-bug-bench-002/review.md
```

测试通过只说明断言仍然成立，不说明改动可以合并，因此报告额外标记需要人判断的改动：编辑了测试文件（可能弱化断言）、改了已有函数的参数签名（关键字调用方会静默失败）、新增测试完全不引用的定义（可能超出题目范围）、删除仍被测试引用的定义。002 的 diff 触发了两条：多加了题目无关的 `average()`，并把 `parse_json(text)` 改名成 `parse_json(s)`——两条测试全绿但都不该直接合并。这类判断目前保留人工，合并仍需审查通过。

外部题库只证明流程可用，样本量仍是每题一次运行，不构成通过率结论。多题、多种子统计属于下一轮。
