# FlyCoder v0.2

实验性 Python 原型：**LLM 负责语言理解、代码分析和生成；连接组适配器仅负责高层动作选择。**

动作空间固定为 `READ`、`EDIT`、`TEST`、`RETRY`、`DONE`。默认演示仍使用确定性 mock 控制器和脚本化 coding mock。v0.2 已在本机接入 MaleCNS v1.0 + DOOMFLY 原生固定权重内核，可用真实连接组活动选择高层动作，并连接现有 BAI/其他兼容 LLM。它不证明果蝇理解代码，也不包含神经学习。FlyWire 尚未实现。

## 立即运行

需要 Git 和 Python 3.9+；Linux 部署镜像使用 Python 3.11。默认运行零第三方 Python 依赖、无需密钥、无需下载数据。在本项目根目录运行：

```bash
python3 -m flycoder demo
```

演示任务：修复 `average(values)` 的错误分母，并让空输入抛出 `ValueError`。

```text
01 READ  reward=-0.01 attempts=0 passed=False
02 EDIT  reward=-0.01 attempts=1 passed=False
03 TEST  reward=-0.30 attempts=1 passed=False
04 RETRY reward=-0.10 attempts=1 passed=False
05 EDIT  reward=-0.01 attempts=2 passed=False
06 TEST  reward=+1.00 attempts=2 passed=True
07 DONE  reward=+0.00 attempts=2 passed=True
```

首次 mock 修改故意遗漏空输入处理，第二次修改补齐。这个演示用于检验闭环和失败反馈，不用于评估编程能力或学习效果。运行前还会做一次 baseline 测试并写入日志。只演示一次成功可运行 `python3 -m flycoder demo --mock-first-pass`。

每次运行生成独立的 `runs/<随机ID>/`：

| 文件 | 用途 |
| --- | --- |
| `repo/` | 输入仓库的独立 Git 快照及候选修改 |
| `events.jsonl` | baseline、动作、输入状态、奖励、测试输出和错误 |
| `summary.json` | 最终状态、退出原因、适配器类型 |
| `changes.patch` | 相对输入快照的修改，可人工审阅 |

源目录不被修改。程序不自动提交候选补丁、不推送、不合并。Git 的初始提交仅发生在新建快照中，用来生成 diff。`DONE` 表示当前快照通过指定测试，不等于代码已被证明正确。

## Linux / Docker Compose

服务器安装 Docker Engine 与 Compose 插件后，上传整个项目目录：

```bash
cp .env.example .env
docker compose up --build --abort-on-container-exit --exit-code-from flycoder
```

这是运行一次后退出的 CLI worker，无需端口或常驻 HTTP 服务。容器以非 root 用户运行，根文件系统只读，输出保存在命名卷 `flycoder-runs`。默认限制 512 MiB 内存、1 CPU、128 个进程；这些限制仅针对 mock 原型，真实连接组需要另行配置资源。

查看及导出结果：

```bash
docker compose run --rm --entrypoint sh flycoder -c 'ls -1 /data/runs'
mkdir -p exported-runs
docker compose cp flycoder:/data/runs/. ./exported-runs/
```

`compose cp` 对上述 `compose up` 留下的容器执行。不要使用 `docker compose down -v`，除非确实要删除保存的运行记录。

## 启用真实 LLM

在 `.env` 设置 `LLM_ADAPTER=openai`、`OPENAI_API_KEY` 和 `OPENAI_MODEL`，然后重新运行 Compose。模型需支持 Responses API 和 JSON object 输出，并对你的账户可用；项目不硬编码模型名称。真实调用会发送输入仓库的文本上下文及测试反馈，并产生 API 费用。

本地 Python 不自动加载 `.env`，请先导出环境变量：

```bash
export LLM_ADAPTER=openai
export OPENAI_MODEL='your-available-model-id'
read -rs OPENAI_API_KEY
export OPENAI_API_KEY
python3 -m flycoder demo
```

上述 `read -rs` 适用于 Bash/Zsh，用于输入密钥。真实 LLM 的动作流程可能更早通过，也可能耗尽预算，结果不保证等同脚本化 demo。

接口依据：[OpenAI Responses API 官方参考](https://developers.openai.com/api/reference/python/resources/responses/methods/create)。使用 HTTPS `POST /v1/responses`、JSON object 输出与 `store: false`；逐项读取消息中的 `output_text`。不接受模型返回的命令，不执行模型选择的工具。HTTP/格式错误会记录为 `error` 并退出。可重试状态（429、500、502、503、504）和网络错误/超时会按指数退避重试 `LLM_MAX_RETRIES` 次；401/402/403/404 等鉴权或请求错误不重试，直接失败。

## 使用自己的小型 Python 仓库

仅对可信仓库运行；需已具备运行依赖，测试位于 `tests/`，支持标准库 `unittest discover`。默认镜像没有安装目标项目的额外依赖，可在自定义镜像中安装。

```bash
python3 -m flycoder run \
  --repo /absolute/path/to/repository \
  --task '修复平均值计算，并正确处理空输入' \
  --editable calculator.py \
  --llm openai \
  --runs /absolute/path/outside/repository/flycoder-runs
```

`--editable` 可重复指定。只允许替换显式列出的已有文件，不支持新增/删除/重命名。`tests/` 下文件及 `test_` 开头文件不能作为修改目标。mock coding adapter 仅适用内置 calculator 示例。

快照不复制原 `.git`、隐藏文件、虚拟环境、缓存、符号链接和常见密钥文件后缀；单文件上限 200 KB、仓库上限 5 MB。这些是小原型的限制，意味着依赖隐藏配置的项目需要扩展快照策略。它不是秘密检测器：请确认输入仓库内不含敏感资料。

**Git sandbox 只隔离文件副本，不是执行不可信代码的安全沙箱。** 本地测试可使用当前操作系统用户权限；Compose 提供基础容器隔离，但同容器内测试仍能访问容器可读资源。测试子进程不继承 API 密钥环境变量，这不构成针对恶意代码的密钥隔离。开放给他人提交任务前，应将测试放入无凭证、禁网、独立的短生命周期执行容器。

## 配置及退出状态

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_ADAPTER` / `--llm` | `mock` | `mock`、`openai`、`deepseek` 或 `chat-completions` |
| `CONNECTOME_ADAPTER` / `--connectome` | `mock` | 支持 `mock`、`random`、`malecns`、`doomfly`；`flywire` 未实现 |
| `MAX_STEPS` / `--max-steps` | 12 | 最多动作数，含 READ/RETRY/DONE |
| `MAX_ATTEMPTS` / `--max-attempts` | 3 | 最多 EDIT 次数 |
| `TEST_TIMEOUT` / `--test-timeout` | 15 | 每次测试超时，秒 |
| `FLYCODER_RUNS` / `--runs` | `runs` | 输出目录；容器默认 `/data/runs` |

退出码：`0` 为 `done`，`1` 为 `exhausted` 或运行错误，`2` 为参数/初始化错误。预算耗尽不会伪装为 DONE。测试零发现、测试超时、测试后又修改文件都不能作为成功。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
```

从源码目录运行是默认使用方式。可选 `python3 -m pip install -e .` 注册 `flycoder` 命令；wheel 和源码包会包含内置 demo，不依赖工作目录中的 `examples/`。

构建并验证发布包：

```bash
python3 -m pip install build
python3 -m build
python3 -m pip install --force-reinstall dist/flycoder-0.2.0-py3-none-any.whl
cd /tmp && flycoder demo --mock-first-pass
```

详见 [架构与适配器契约](docs/architecture.md)、[实际验证记录](docs/validation.md) 和 [发布流程](docs/releasing.md)。项目包含 Linux CI 配置，会执行测试、构建/安装 wheel 并运行容器演示；在 CI 平台实际运行前，不应把配置文件视为已通过的证据。


## DeepSeek 与自定义接口

已实现通用 `ChatCompletionsCodingAdapter`。`--llm deepseek` 使用 DeepSeek 默认地址，`--llm chat-completions` 使用你指定的地址；两者都调用 Chat Completions 协议。`--llm openai` 仍使用原有 OpenAI Responses 协议。

DeepSeek 示例（先在供应商平台创建 API Key，模型名以账户当前可用列表为准）：

```bash
cd ~/Documents/ChatGPT/FlyCoder
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-flash"
```

单独执行下面一行，粘贴密钥并回车（Bash/Zsh，不回显）：

```bash
read -rs LLM_API_KEY
```

然后启动：

```bash
export LLM_API_KEY
python3 -m flycoder demo --llm deepseek --connectome mock
```

模型名示例来自 [DeepSeek 官方 JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)，不假定你账户一定有该模型权限。程序不硬编码模型名称。真实调用会把代码上下文发送到配置的服务商，并使用其 API 额度。

自定义兼容服务只需调整配置：

```bash
export LLM_BASE_URL="https://your-provider.example/v1"
export LLM_MODEL="your-model-id"
python3 -m flycoder demo --llm chat-completions
```

请重新输入对应服务商的 `LLM_API_KEY`。不要把 OpenAI 密钥用于 DeepSeek，程序也不会自动复用 `OPENAI_API_KEY`。仅在 deepseek 模式下，可用 `DEEPSEEK_API_KEY` 作为 `LLM_API_KEY` 为空时的替代。

`LLM_BASE_URL` 可填写基址或完整的 `/chat/completions` 地址；代码会处理尾部斜杠，保留你指定的 `/v1` 等路径前缀。远程地址要求 HTTPS，本机 localhost/127.0.0.1/::1 允许 HTTP。重定向被拒绝，避免将密钥转发到其他地址。

| 环境变量 | 默认/用途 |
| --- | --- |
| `LLM_ADAPTER` | `mock`；可改为 `deepseek` / `chat-completions` |
| `LLM_BASE_URL` | deepseek 模式默认为 `https://api.deepseek.com`；通用模式必填 |
| `LLM_MODEL` | 必填，服务商提供的模型 ID |
| `LLM_API_KEY` | 对应服务商的密钥 |
| `LLM_TIMEOUT` | 60 秒 |
| `LLM_MAX_TOKENS` | 6000，输出 token 上限 |
| `LLM_JSON_MODE` | `json_object`；不支持该参数的服务可设 `text` |
| `LLM_MAX_RETRIES` | 2；对 429/5xx 与网络错误的额外重试次数（不重试 4xx 鉴权/请求错误） |
| `LLM_RETRY_BACKOFF` | 0.5 秒；指数退避基数，单次延迟上限 8 秒 |

`text` 仅省略 `response_format`，返回内容仍须是有效 JSON。空响应、截断响应、工具调用结果或错误结构均拒绝进入文件修改。接口兼容指 Chat Completions 请求/响应格式，不包含所有服务商的专有参数。

本地 Python 仍不自动加载 `.env`。若已在项目 `.env` 中填写配置，可在 Bash/Zsh 执行 `set -a`、`source .env`、`set +a` 后运行；Compose 会读取 `.env`，这些新变量也已加入容器配置。不要把真实 `.env` 提交或打包。


## 已接入的本机 MaleCNS 后端

最快运行：在项目目录执行 `./run-neural.sh`，会自动读取 `.env`。首次安装或换机器请阅读 [本机神经后端说明](docs/neural-local.md)。本机环境已准备完成，无需重复下载。使用你已填写的 BAI 配置：

```bash
cd ~/Documents/ChatGPT/FlyCoder
set -a
source .env
set +a
.venv-neural/bin/python -m flycoder demo --llm chat-completions --connectome malecns
```

务必使用 `.venv-neural/bin/python`。原来的 `python3` 环境未安装神经模拟依赖。`doomfly` 是相同 MaleCNS 后端的别名；`flywire` 会明确报未实现。

输出 `summary.json` 中应出现 `policy=NeuralConnectome` 和 `last_neural_trace`；`events.jsonl` 每步记录真实活动计数、五个动作分数、合法动作集合、数据/映射哈希及神经模拟耗时。参数 `--connectome malecns` 自动启用较宽的动作约束，允许在合法范围内选择 READ/EDIT/TEST。

现有 `Dockerfile` 是基础 LLM/mock worker，不含大数据、神经环境或 vendor，不能直接运行 malecns。`Dockerfile.neural` 是独立的重型镜像，会在构建时执行 `scripts/setup_neural.sh`，包含固定版本 DOOMFLY、锁定依赖、MaleCNS 数据、编译内核、校验和离线实测：

```bash
docker compose -f docker-compose.neural.yml build
docker compose -f docker-compose.neural.yml run --rm flycoder-neural --llm mock
```

该镜像会下载约 1.1 GB 输入并在镜像中保留标准化数据和 Python 环境，构建时间和磁盘占用显著高于基础镜像。GitHub Actions 的 `FlyCoder neural Linux check` 工作流已在 Ubuntu runner 上通过同一 `scripts/setup_neural.sh` 准备真实后端，并逐步核验 MaleCNS/DOOMFLY 运行记录；固定权重动作并列或预算耗尽会记录为策略结果，不会被误判为后端故障。该工作流不构建 `Dockerfile.neural`。本机已安装 Docker 29.8.0，但重型镜像此前进入导出阶段后因 Docker daemon 连接 EOF 失败，因此容器化神经镜像仍没有完整构建并运行实测。


## 验收与并列现场修复

已增加 v2 证据校验及当前失败现场记录，55 项神经环境测试通过；详见 [验收与诊断说明](docs/neural-evidence.md)。历史日志缺少新字段，严格验收需重新运行。相关修改已推送并通过远程 CI；受控重放已确认浮点收缩不是当前跨平台输出差异的根因。
