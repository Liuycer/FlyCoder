# 本地 Docker 使用

本项目先在当前 Mac 上运行，不需要 SSH，也没有向外部服务器部署。它是按任务启动、结束后退出的 coding worker，不是网页服务，因此无需开放端口。

## 已有运行环境

`flycoder-neural-runtime:32b09ae16fcb` 是此前校验通过的完整 Linux/arm64 神经镜像，保留固定版本 DOOMFLY、连接组数据、神经环境和映射。`Dockerfile.local` 在其基础上更新项目代码并执行测试，避免每次修改代码都重新下载约 1.1 GB 数据。

```bash
docker compose -f docker-compose.neural.yml -f docker-compose.local.yml build
./run-local.sh --llm mock
```

如果换了一台没有这个基础镜像的机器，先按 `Dockerfile.neural` 构建完整运行环境，再设置 `NEURAL_BASE_IMAGE` 指向该镜像；不能仅复制源码就假设本地专用基础镜像存在。

## 使用已经配置的 BAI

`.env` 仍是配置来源，Compose 会读取模型和 API key。不要把 `.env` 复制进镜像。当前本机配置模型为 `qwen3.8-flash`，接口主机为 `api.b.ai`。

```bash
./run-local.sh
```

这会使用 `.env` 中的 LLM_ADAPTER。默认神经策略依旧并列停止。如需显式启用实验累计策略：

```bash
./run-local.sh --llm chat-completions --tie-extra-windows 2
```

LLM 负责代码理解和生成；神经连接组只做高层动作选择。实验成功不意味着果蝇理解代码。

## 指定一个可信的小仓库

默认挂载自带示例仓库到 `/workspace`，只读挂载；代码修改写入独立的运行卷。可用 `FLYCODER_TARGET_REPO` 指定项目路径：

```bash
FLYCODER_TARGET_REPO="$PWD/benchmarks/tasks/invoice/repo" ./run-local.sh \
  run --repo /workspace --editable invoice.py --editable money.py \
  --task 'Fix invoice totals and decimal half-up rounding; preserve tests.' \
  --llm chat-completions --tie-extra-windows 2
```

这不会直接改写挂载的源仓库。每次运行最后输出 `/data/runs/<id>`，其中包含 summary、events 和 changes.patch。

```bash
docker compose -f docker-compose.neural.yml -f docker-compose.local.yml run --rm \
  --entrypoint /app/.venv-neural/bin/python flycoder-neural \
  scripts/check_neural_run.py --runs /data/runs --require-done
```

验收针对最近一次运行，若要复核特定记录则使用 `--summary /data/runs/<id>/summary.json`。并列、沉默和预算停止不算任务成功。

容器以非 root 用户运行，根目录只读，神经缓存位于 `/tmp`，沿用 4 GiB 内存、2 CPU、256 PIDs 的限制。运行卷持久保存结果。本轮仅用于可信的小仓库；Git sandbox 的能力边界仍见 README。


## 本次已执行验证

- 最新本地镜像构建通过，镜像内与宿主神经环境均通过 70 项测试。
- 离线真实神经 demo 完成 8 个动作，严格验收通过。
- 容器内 BAI demo 完成 READ → EDIT → TEST → DONE，严格验收通过。该 smoke 在补充断连重试前执行，后续修复由重试单测覆盖。
- 更新镜像后，对只读挂载的 invoice 多文件仓库使用固定候选完成 8 个动作并严格验收通过，同时检查源文件字节未改变。
- 运行证据已导出到项目的 `research/local-bai-smoke/`、`research/local-multifile-smoke/`，检查报告为 `research/local-bai-check.json`、`research/local-multifile-check.json`。

这些验证在本机完成；没有部署外部服务器，也没有开启网页端口。
