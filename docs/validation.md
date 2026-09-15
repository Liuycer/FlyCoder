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
