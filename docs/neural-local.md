# 本机真实 MaleCNS 接入（FlyCoder v0.2）

已在 Apple M5 / 24 GB 内存 / macOS / Python 3.11.16 上完成本机接入。项目位置为 `~/Documents/ChatGPT/FlyCoder`。

## 直接运行

BAI 已配置在 `.env`。推荐用下面入口，它会自动读取本项目 `.env`，选择专用 Python 环境并强制使用真实 MaleCNS 后端：

```bash
cd ~/Documents/ChatGPT/FlyCoder
./run-neural.sh
```

不调用 BAI 的离线编程演示（仍运行真实连接组）：

```bash
./run-neural.sh --llm mock
```

自定义可信 Python 仓库：

```bash
./run-neural.sh run --repo /absolute/path/to/repo --task '修复具体问题' --editable module.py
```

底层等价调用为 `.venv-neural/bin/python -m flycoder demo --connectome malecns --llm chat-completions`，但底层命令仍需先加载 `.env`。`run-neural.sh` 不修改 `.env`，`CONNECTOME_ADAPTER=mock` 不影响这个专用入口。命令行 `--llm` 优先于配置；wrapper 将 `.env` 作为本项目配置，不执行其中的 shell 代码或展开变量。

## 实际接入内容

- 固定上游提交：`71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33`。
- 数据：MaleCNS v1.0，三个输入文件共 1,109,008,094 字节（约 1.11 GB），全部逐文件校验。
- 按上游保留规则导入 166,700 个节点、25,582,938 条边；原始输入中的其余分割对象及其连接由上游规则排除，不能将保留图描述为全部原始分割对象。
- 运行图完整保留弱连接和自连接；原生内核、数据转换、完整边审计均已运行。
- 使用固定权重近似 LIF 模型。没有运行学习或神经可塑性候选。
- BAI 负责语言/代码；14 项数值状态经人工亮度编码进入神经模拟，500 个校准读出神经元分为五组对应动作。

读出群体仅根据合成刺激的响应变化选择，排除直接刺激群体；动作分组由固定种子产生，没有利用编程任务成败来选神经元。平均放电率是动作分数，不是动作概率或编程理解程度。

## 如何确认是真实后端

运行目录 `summary.json` 包含 `policy: NeuralConnectome`，`last_neural_trace.backend` 指明 MaleCNS/DOOMFLY。每步 `events.jsonl` 记录：

- 刺激哈希、真实放电计数哈希、活跃神经元数。
- 五个动作的平均放电率、允许动作集合、选定动作。
- 模拟时间和实际内核耗时。
- 图与映射哈希，以及 `weight_learning: false`。

已完成的 BAI + MaleCNS 运行保存在 `runs/live-malecns-dfb475f8e4/`，序列 READ → EDIT → TEST → DONE，当前候选通过 5 项示例测试。该运行中 READ、EDIT、DONE 分别只有一个合法动作；TEST 是在 READ/EDIT/TEST 中根据神经分数选择的。不能把所有步骤都解释为不受约束的神经决策。

## 验证与小型对照

项目 34 项测试通过；上游 15 项连接组/数值参考测试通过。完整图重置后重放一致、屏蔽刺激改变输出、断开连接使读出归零、打乱读出改变动作分数。数值测试不等于生物学有效性。

同一个 average bug、同一 BAI 配置、同一 seed=0、12 步及 3 次修改预算：

| 控制器 | 结果 | 修改次数 | BAI 调用次数 | 总耗时（秒） |
| --- | --- | --- | --- | --- |
| mock | done | 1 | 2 | 17.97 |
| random | done | 1 | 3 | 26.7 |
| malecns | done | 1 | 2 | 27.59 |

三者都成功。连接组没有表现出更高成功率或更少调用；总耗时包含网络和模型响应波动。这里只有一个任务、一个随机种子，不能得出策略优劣结论。

离线 mock 编程执行器故意首次遗漏空输入处理时，连接组完成 READ → EDIT → TEST → READ → RETRY → EDIT → TEST → DONE；规则基线 7 步，随机基线 9 步，连接组 8 步。

## 资源测量

本机短刺激实验进程的峰值 RSS 约 384 MB；这只代表该次模拟探测，不包含数据导入/准备峰值，也不是长期运行上限。真实 BAI 联调中，每次推进 100 ms 神经时间，内核耗时约 64–86 ms。LLM 等待期间不推进神经时间，每个新任务重置神经状态。

已测磁盘占用：Python 环境约 786 MiB，输入及标准化数据约 1.3 GiB，上游运行产物约 249 MiB。先前上游“数 GB 内存”的说明较保守，本机短测结果不保证其他机器或更长刺激协议相同。

## 可复现安装与实验

另一台机器需要 Python 3.11、clang++、Git 和 curl。在源码根目录运行：

```bash
bash scripts/setup_neural.sh
```

脚本固定上游提交、把虚拟环境内的 pip 固定到 `26.2.1`（`--build-constraint` 仅存在于 pip ≥ 25.0，CI runner 自带 pip 常常更旧）、安装锁定依赖、下载并校验数据、构建内核、导入并审计数据、运行数值测试和校准。构建约束 `vendor/doomfly/neural-build-constraints.txt` 把构建期 setuptools 固定在 68.2.2，否则 Brian2 2.5.1 的 `setup.py` 会因新 setuptools 移除 `pkg_resources` 而失败。可用 `PIP_VERSION` 覆盖该 pin。现有 checkout 版本不匹配会停止，不会覆盖其他版本。安装和大文件下载需要联网，运行纯离线 demo 不需要。

```bash
.venv-neural/bin/python scripts/validate_neural.py
.venv-neural/bin/python scripts/compare_controllers.py
```

`compare_controllers.py --live` 会读取 `.env` 并产生真实 API 用量；默认不联网。对照只针对一个内置任务。

证据文件：`research/upstream-lock.json`、`neural-probe.json`、`neural-validation.json`、`comparison-offline.json`、`comparison-live.json`、各步骤日志。上游完整边审计在 `research/data-audit.log`，固定环境在 `requirements-neural.lock.txt`。Linux 实测由 `.github/workflows/neural.yml` 手动触发；`scripts/check_neural_run.py` 会逐个动作核验真实后端 trace，并把动作并列、读出静默或预算耗尽区分为策略结果而非基础设施故障。

## 当前边界

最高分并列、读出沉默、图或映射校验不一致时明确报错，不自动退回 mock。合法动作约束、DONE 测试门槛和预算仍由工程代码执行。奖励只是记录和状态输入，未证明学习。

FlyWire 未接入。基础 `Dockerfile` 不含神经环境。`Dockerfile.neural` 和 `docker-compose.neural.yml` 已完成静态配置，并于 2026-09-15 在本机 Docker 29.8.0/Linux arm64 上完整构建和实测。容器内真实 MaleCNS + mock demo 完成 8 个动作并进入 DONE；严格 `--require-done` 验收返回 `backend_verified=true, task_solved=true, outcome=task_solved`。镜像未发布到服务器。

Docker 证据的哈希化打包、复查命令和手动远程工作流见 [神经 Docker 验证](neural-docker-verification.md)。

Git sandbox 仍是可信仓库的文件副本隔离，不适用于执行陌生人上传的恶意代码。

数据、模型和许可署名见项目 `THIRD_PARTY.md` 与上游原始说明。
