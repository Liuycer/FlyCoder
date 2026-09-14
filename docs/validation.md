# 验证记录

v0.2 当前验证见 [本机神经后端说明](neural-local.md)：34 项项目测试、15 项上游测试通过；真实连接组与 BAI 已联调成功，已执行合成刺激/断连/重放对照。以下为 v0.1 历史记录。

本次实际环境：macOS、Python 3.9.6、Git 2.50.1。

已执行 `python3 -m flycoder demo`，结果 `done`。动作序列为 READ → EDIT → TEST → RETRY → EDIT → TEST → DONE；第一次候选未通过，第二次通过示例全部 5 项测试。

已执行 `python3 -m unittest discover -s tests -v`，18 项测试全部通过：覆盖端到端修复、直接成功、预算退出、非法 DONE、过期通过结果、受限文件修改、符号链接、零测试、全部跳过、超时、大量输出、子进程环境、状态编码、neural 分数契约、OpenAI 离线响应契约。

未执行真实 OpenAI 请求，未使用 API 密钥。OpenAI 响应解析通过模拟 HTTP 响应验证。

当前环境未安装 Docker，因此未实际构建镜像或运行 Compose；已提供 Linux CI 自动执行这些步骤。未部署到任何外部服务器，未加载真实 MaleCNS/FlyWire 数据，未运行 DOOMFLY。


DeepSeek/自定义接口更新：28 项测试全部通过，新增 Chat Completions 请求契约、配置与密钥隔离、非法响应/截断/超时、HTTP 错误脱敏、重定向拒绝，以及 deepseek 和 chat-completions 两种 CLI 入口的离线端到端验证。没有发起真实 DeepSeek 或其他供应商请求；Docker 环境仍未实测。

## 2026-09-14 发布收尾

- 当前源码在 Python 3.9.6 下运行 40 项项目测试，结果通过，2 项可选 NumPy 契约因依赖未安装而跳过。
- 当前源码在 Python 3.11.16 神经环境中运行 40 项项目测试，结果全部通过。
- 新增 LLM 重试测试：429/500/502/503/504 与网络错误/超时按指数退避重试后成功、4xx 鉴权/请求错误不重试、重试耗尽报错、零重试单次尝试，以及非法 `LLM_MAX_RETRIES`/`LLM_RETRY_BACKOFF` 被拒绝；测试 patch `time.sleep`，不产生真实等待。
- wheel 和 sdist 已在本机构建；wheel 包含内置 `calculator.py` 与测试资产。
- wheel 已在源码目录外的临时虚拟环境安装，`flycoder demo --mock-first-pass` 返回 `done`。
- 所有 Compose 与 workflow YAML 已通过本机 YAML 解析校验。
- Linux Actions 首次运行：`FlyCoder checks`（含 Python 3.9/3.11/3.12 测试、打包 job）通过；`FlyCoder neural Linux check` 在 `bash scripts/setup_neural.sh` 失败，原因是 runner 自带 pip 早于 25.0，不认识 `--build-constraint`（`no such option: --build-constraint`）。已在 `setup_neural.sh` 中把 venv 内 pip 固定为 `26.2.1` 后重跑。
- 本机未安装 Docker，因此 `Dockerfile.neural` 和 `docker-compose.neural.yml` 尚未实际构建。
- 已增加 GitHub Actions 手动 Linux 神经验证工作流；在它成功运行前，Linux/Docker 神经后端仍属于未验证状态。
