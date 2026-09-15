# 神经 Docker 验证与证据打包

本文说明如何保存、复查和复现 `Dockerfile.neural` 的运行证据。证据校验器检查日志一致性；它不能证明外部提交的文件没有被恶意伪造，但可以防止把过期 trace、伪通过、预算停止或并列策略误报为成功。

## 成功条件

一次成功验收必须同时满足：

1. 容器退出码为 `0`，未被 OOM 杀死。
2. `scripts/check_neural_run.py` 返回 `backend_verified=true`。
3. 使用 `--require-done` 时返回 `task_solved=true`、`outcome=task_solved`。
4. `summary.json`、`events.jsonl`、神经 trace、镜像/容器配置和日志一起保存。
5. 并列分数、读出沉默、预算耗尽可作为策略结果记录，但不能在 `--require-done` 下计为任务解决。

## 证据打包

`scripts/package_neural_docker_evidence.py` 生成包含每个证据文件大小和 SHA-256 的 manifest，并可选择生成确定性 tar.gz 证据包：

```bash
python3 scripts/package_neural_docker_evidence.py \
  --run-dir research/docker-neural-runs/<run-id> \
  --check-report research/docker-neural-check.json \
  --compose-config research/docker-neural-config.yaml \
  --container-config research/docker-neural-container.json \
  --image-config research/docker-neural-image.json \
  --build-log research/docker-neural-build-current.log \
  --demo-log research/docker-neural-demo.log \
  --commit "$(git rev-parse HEAD)" \
  --output research/docker-neural-evidence-manifest.json \
  --archive research/docker-neural-evidence.tar.gz \
  --require-done
```

manifest 使用 schema `flycoder.neural-docker-evidence.v1`。它只保存路径、字节数、哈希、验收报告摘要和 GitHub 元数据；不保存密钥值。`research/` 仍被项目规则排除在源码提交之外。

复查压缩包时，先展开，再重跑严格验收器：

```bash
rm -rf /tmp/neural-docker-evidence && mkdir -p /tmp/neural-docker-evidence
tar -xzf research/docker-neural-evidence.tar.gz -C /tmp/neural-docker-evidence
python3 scripts/check_neural_run.py \
  --summary /tmp/neural-docker-evidence/neural-docker-evidence/run/summary.json \
  --require-done
```

## 本机已有实测

2026-09-15 的 Linux/arm64 本机运行记录保存在：

- `research/docker-neural-runs/a386714085444b3a948c806719cd7fd0/`
- `research/docker-neural-check.json`
- `research/docker-neural-run-provenance.json`
- `research/docker-neural-container.json`
- `research/docker-neural-image.json`
- `research/docker-neural-config.yaml`
- `research/docker-neural-demo.log`
- `research/docker-neural-build-current.log`
- `research/docker-neural-evidence-manifest.json`
- `research/docker-neural-evidence.tar.gz`

该运行完成 8 个动作并进入 `DONE`，严格验收结果为 `backend_verified=true, task_solved=true, outcome=task_solved`。

## 手动远程工作流

`FlyCoder neural Docker check` 是手动触发的重型检查。它不随普通 push 自动执行。工作流会：

1. 构建 `Dockerfile.neural`。
2. 导出 compose 配置和镜像 inspect 元数据。
3. 以非 root、只读根文件系统、drop capabilities、`no-new-privileges`、无网络、4 GiB 内存、2 CPU 和 256 PIDs 的限制运行 mock demo。
4. 从命名卷复制 run 记录。
5. 执行严格 `--require-done` 验收。
6. 生成 manifest 和 tar.gz 证据包。
7. 将全部证据上传为 workflow artifact。

这个工作流通过后，可以在目标 commit 的 artifact 中找到 `manifest.json` 与 `neural-docker-evidence.tar.gz`。
