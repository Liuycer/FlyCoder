# 验证记录

v0.2 当前验证见 [本机神经后端说明](neural-local.md)：55 项项目测试在神经环境全部通过（基础环境运行 55 项，2 项可选 NumPy 契约跳过）、15 项上游测试通过；真实连接组与 BAI 已联调成功，已执行合成刺激/断连/重放对照。以下为 v0.1 历史记录。

本次实际环境：macOS、Python 3.9.6、Git 2.50.1。

已执行 `python3 -m flycoder demo`，结果 `done`。动作序列为 READ → EDIT → TEST → RETRY → EDIT → TEST → DONE；第一次候选未通过，第二次通过示例全部 5 项测试。

已执行 `python3 -m unittest discover -s tests -v`，18 项测试全部通过：覆盖端到端修复、直接成功、预算退出、非法 DONE、过期通过结果、受限文件修改、符号链接、零测试、全部跳过、超时、大量输出、子进程环境、状态编码、neural 分数契约、OpenAI 离线响应契约。

未执行真实 OpenAI 请求，未使用 API 密钥。OpenAI 响应解析通过模拟 HTTP 响应验证。

当时环境未安装 Docker，因此未实际构建镜像或运行 Compose；已提供 Linux CI 自动执行神经后端准备步骤。未部署到任何外部服务器。


DeepSeek/自定义接口更新：28 项测试全部通过，新增 Chat Completions 请求契约、配置与密钥隔离、非法响应/截断/超时、HTTP 错误脱敏、重定向拒绝，以及 deepseek 和 chat-completions 两种 CLI 入口的离线端到端验证。没有发起真实 DeepSeek 或其他供应商请求；Docker 环境仍未实测。

## 2026-09-14 发布收尾

- 发布收尾时源码在 Python 3.9.6 下运行 40 项项目测试，结果通过，2 项可选 NumPy 契约因依赖未安装而跳过。
- 发布收尾时源码在 Python 3.11.16 神经环境中运行 40 项项目测试，结果全部通过。
- 新增 LLM 重试测试：429/500/502/503/504 与网络错误/超时按指数退避重试后成功、4xx 鉴权/请求错误不重试、重试耗尽报错、零重试单次尝试，以及非法 `LLM_MAX_RETRIES`/`LLM_RETRY_BACKOFF` 被拒绝；测试 patch `time.sleep`，不产生真实等待。
- wheel 和 sdist 已在本机构建；wheel 包含内置 `calculator.py` 与测试资产。
- wheel 已在源码目录外的临时虚拟环境安装，`flycoder demo --mock-first-pass` 返回 `done`。
- 所有 Compose 与 workflow YAML 已通过本机 YAML 解析校验。
- Linux Actions 首次运行：`FlyCoder checks`（含 Python 3.9/3.11/3.12 测试、打包 job）通过；`FlyCoder neural Linux check` 在 `bash scripts/setup_neural.sh` 失败，原因是 runner 自带 pip 早于 25.0，不认识 `--build-constraint`（`no such option: --build-constraint`）。已在 `setup_neural.sh` 中把 venv 内 pip 固定为 `26.2.1` 后重跑。
- 当时本机未安装 Docker，因此 `Dockerfile.neural` 和 `docker-compose.neural.yml` 尚未实际构建。
- 后续提交 `741208a` 新增 `scripts/check_neural_run.py`，将“真实后端已运行但固定权重策略未解出玩具任务”的记录为可见警告，而不是基础设施失败；同时继续拒绝缺失 trace、异常后端、非有限分数或权重学习声明等错误。
- Linux 原生神经验证工作流 [run 34858263269](https://github.com/Liuycer/FlyCoder/actions/runs/34858263269) 在 `741208a` 上通过。实际后端完成 4 个动作并产生逐步 trace；第 5 步因合法 READ/TEST 动作分数并列而按设计停止，未回退到 mock。
- 推送后的 `FlyCoder checks` [run 34858236271](https://github.com/Liuycer/FlyCoder/actions/runs/34858236271) 通过。
- 该神经验证工作流仍未构建 `Dockerfile.neural`；当时本机未安装 Docker，因此 Linux 原生后端已验证，但容器化神经镜像仍属于未验证状态。


## 验收与并列现场修复

已增加 v2 证据校验及当前失败现场记录，55 项神经环境测试通过；详见 [验收与诊断说明](neural-evidence.md)。历史日志缺少新字段，严格验收需重新运行。相关修改已推送并通过远程 CI。

## 2026-09-14 受控重放诊断收尾

- `fa0ef3a` 的 checks [run 34864923088](https://github.com/Liuycer/FlyCoder/actions/runs/34864923088) 和神经工作流 [run 34864923823](https://github.com/Liuycer/FlyCoder/actions/runs/34864923823) 均通过。
- 神经制品中的受控重放显示：macOS/Linux 图与映射哈希一致，默认内核下放电仍有差异；no-contract 内核下放电与分数一致，但内部 `v/g` 仍有平台差异。
- Linux 默认内核与 `-ffp-contract=off` 诊断内核的受控结果完全一致；这不能排除 macOS 侧浮点收缩的影响。macOS 关闭浮点收缩后，三次完整放电数组和动作分数均与 Linux 一致，但内部电压 `v`、电导 `g` 仍有差异。结论仅适用于本次固定回放，不保证任意任务跨平台逐位一致。
- Linux 真实运行在第 5 步因合法 READ/TEST 并列停止，严格报告为 `backend_verified=true, task_solved=false, outcome=tied_scores`。
- 本机已检测到 Docker 29.8.0，此前神经镜像构建曾进入导出阶段后因 Docker daemon 连接 EOF 失败；容器化神经镜像仍没有完整构建并运行实测。
- 已从当前源码重建 v0.2.0 wheel/sdist；wheel 在源码外的独立虚拟环境安装并离线运行 `demo --mock-first-pass`，返回 `done`。

## 2026-09-15 神经 Docker 实测

- 在 Docker 29.8.0 的 linux/arm64 环境中完整构建 `flycoder-flycoder-neural:latest`；镜像 ID 前缀 `32b09ae16fcb`，大小约 5.41 GB。
- 为容器导入上游引擎时添加 `NUMBA_CACHE_DIR=/tmp/numba-cache`，配合只读根文件系统和 `/tmp` tmpfs。
- 容器以非 root 用户 `flycoder` 运行，drop 全部 capabilities、禁用 privilege escalation、根文件系统只读，限制 4 GiB 内存、2 CPU、256 PIDs，退出码为 0 且未被 OOM 杀死。
- 容器内真实 MaleCNS + mock demo 完成 8 个动作：READ → EDIT → TEST → READ → RETRY → EDIT → TEST → DONE；第二次 TEST 执行 5 项测试并通过。
- 严格日志验收返回 `backend_verified=true, task_solved=true, outcome=task_solved, completed_actions=8`。
- 本地证据保存在 `research/docker-neural-check.json`、`docker-neural-check.log`、`docker-neural-run-provenance.json`、`docker-neural-container.json`、`docker-neural-image.json`、`docker-neural-config.yaml`、`docker-neural-demo.log` 和 `research/docker-neural-runs/`；这些目录按项目规则不进入源码提交。
- 已新增 `scripts/package_neural_docker_evidence.py` 和 `FlyCoder neural Docker check` 手动工作流，用于生成哈希化证据包并在干净 Ubuntu runner 上复现构建、运行与严格验收；远程 Docker 工作流结果单独以 workflow artifact 为准。
- 本机证据已打包为 `research/docker-neural-evidence-manifest.json` 与 `research/docker-neural-evidence.tar.gz`；从压缩包内复跑 `--require-done` 仍返回 `task_solved=true`。

## 2026-09-15 远程 x86_64 神经 Docker 验证

- 提交 `0a0dda7b393e3067d19f632e16b6500b65208c97` 的 [Docker 工作流 34937809743](https://github.com/Liuycer/FlyCoder/actions/runs/34937809743) 通过。证据路径为 `run/<run-id>/summary.json`，工作流以 `--runs` 查找。
- 远程镜像架构为 amd64；容器用户 `10001:10001`、根文件系统只读，退出码 1，`OOMKilled=false`。
- 真实后端完成 4 个动作，第 5 次选择因分数并列停止；独立 checker 复跑返回 `backend_verified=true, task_solved=false, outcome=tied_scores`。这是后端验证通过，不是任务成功。
- 已重新下载证据包，核验 manifest 列出的全部 38 个文件大小和 SHA-256，并在独立目录复跑 checker；复核文件保存在 `research/review-0a0dda7/`。
- 本机 ARM64 的 8 步 DONE 与远程 x86_64 的并列停止分别记录，不能互相替代，也不代表已部署到外部服务器。
- 后续本地修复强制执行打包器的 `--require-done`，将 workflow 沉默结果名统一为 `silent_readouts`，并分开说明两种证据目录布局。以上远程运行发生在这些后续修复之前，不作为修复后 CI 的证明。
- 后续修复的本地验证：神经环境 61 项测试全部通过；使用真实 ARM64 扁平证据包和 x86_64 子目录证据包分别复跑 checker 与打包器。ARM64 严格模式通过，x86_64 策略模式通过，而添加 `--require-done` 后按预期拒绝打包。记录位于 `research/fix-evidence-review/`。


## 2026-09-15 策略评测与累计实验

- 项目 67 项测试通过，覆盖独立 bug/候选有效性、唯一最高分不追加窗口、并列解除、持续并列停止、沉默停止、窗口/累计证据篡改等情况。
- 本机与远程 x86_64 各完成 48 次离线四策略评测，共 96 次；48 份神经运行记录独立复验通过，未调用真实 LLM。
- 远程 [run 34939855824](https://github.com/Liuycer/FlyCoder/actions/runs/34939855824) 在 `24f557d` 上通过。原始神经策略 0/12 完成，均因并列停止；累计实验 12/12 完成。规则 mock 12/12，随机策略 11/12。
- 本机原始与累计策略均为 12/12，未触发并列；结果和统计限制见 [策略评测说明](policy-benchmark.md)。默认神经策略未启用累计功能。


## 2026-09-15 BAI、扩展任务与本地部署

- 真实模型为 BAI `qwen3.8-flash`。原四任务 × 三策略的 12 次真实运行全部成功；新增三类多文件任务 × 三策略共 9 次，8 次成功、1 次服务端断连失败，原始失败保留未重跑。
- 两组真实评测共 45 次 HTTP 请求，供应商已报告 input/output tokens 为 28,954 / 31,467；失败尝试可能缺 usage，费用金额未估算。额外容器 smoke 单独记录。
- 扩展离线评测共 36 次：mock、random、累计策略各 9/9 成功，原始连接组 3/9 成功、6 次并列停止。
- 新增共享 HTTP 请求预算（含重试）、token 记录和连接中断有限重试；70 项测试通过。
- 本地 Docker 使用已验证神经运行镜像更新代码，避免重下数据；已验证 BAI demo、多文件只读挂载与独立 Git 副本。真实 BAI 与多文件运行记录均导出并严格复验。
- 详见 [真实评测](live-evaluation.md)、[本地部署](local-deployment.md)。本轮按用户要求继续本地使用，没有外部服务器部署。


## 2026-09-15 远程镜像验收、用量记录与外部题库修复

- 远程 [run 34937809743](https://github.com/Liuycer/FlyCoder/actions/runs/34937809743) 在 `0a0dda7` 上通过：修复了工作流发现运行证据的路径（改用 `--runs`），产出 `tied_scores`，`backend_verified=true`，属 x86_64 合法策略停止而非故障。证据包 39 个文件的哈希与 tar.gz 内清单一致。
- `summary.json` 现在记录 `llm_calls`、`llm_http_attempts` 与逐次 `llm_usage`，缺失用量保持缺失不填零。
- 新增 `scripts/report_run.py`：输出结论、动作链、分文件 diff 统计、LLM 请求与 token、神经后端指纹、baseline 失败明细，并额外标记测试通过但仍需人工判断的改动（改测试文件、改参数签名、加未被测试引用的定义、删仍被引用的定义）。
- 外部题库 `llm-bug-bench` 两道题在本机 arm64 容器内以真实 BAI + MaleCNS 运行成功：001 四步 `task_solved`（单行比较符号修复），002 八步 `task_solved`（首次 EDIT 破坏导入后由 RETRY 恢复）。两次均通过 `check_neural_run.py` 严格复验，题库原件未改动，参考实现 `fixed.py` 排除在任务副本之外。
- 002 的运行 diff 触发两条审查标记（无关的 `average()`、`parse_json` 参数改名），按流程保留人工审查、未自动合并。
- 项目测试 82 项通过（基础环境 2 项可选 NumPy 契约跳过）。


## 2026-09-15 批次脚本、模型切换与 003–008 批次

- 新增 `scripts/run_task_bench.py`：一条命令串起任务副本准备（unittest 薄包装、排除 `fixed.py`、逐文件 SHA-256）、baseline 预检、批次内单次镜像构建、逐 (题目, seed) 容器运行、命名卷证据导出、`check_neural_run.py` 严格复验、`report_run.py` 审查报告与批次汇总。题库目录始终只读，生成的修复不自动合并。
- 首次真实批次暴露两个问题并已修复：导出证据时 `--volume` 用了相对路径（Docker 会当成命名卷而失败），现强制绝对路径；运行记录未写明模型，现 `summary.json` 记录 `llm_model`，审查报告与批次汇总一并展示，缺失时以 `llm_model_source` 标明取值来源。
- 真实模型由 `qwen3.8-flash` 换成 `deepseek-v4.1-flash`。旧模型下 003 的 3 次调用消耗 8 次 HTTP 尝试（5 次超时），容器创建后约 12 分钟以 `LLM connection failed or timed out` 结束；新模型下同一批六题约 1 分钟完成，每题 10–11 秒。超时尝试证据保留在 `research/bug-bench-runs/basic-003-008-attempt1-aborted/`。
- `basic-003-008` 批次六题全部 `backend_verified=true, outcome=task_solved`，各 4 个动作、2 次 LLM 调用，共 12 次 HTTP 请求（无重试）、input 16,601 / output 6,607 tokens。基线均为 FAIL，修复分别为边界条件、初始值、可变默认参数、异常处理、索引计算与分隔符解析。
- 005 的 diff 触发一条审查标记（`updates={}` → `updates=None`），即题目要求的标准修法，但仍按流程留待人工确认后才可合并。
- 项目测试 95 项通过（含新增的批次脚本、导出路径、模型溯源用例；基础环境 2 项可选 NumPy 契约跳过）。
