# 神经 Docker 验证与证据打包

本文说明如何保存、复查和复现 `Dockerfile.neural` 的运行证据。证据校验器检查日志一致性；它不能证明外部提交的文件没有被恶意伪造，但可以防止把过期 trace、伪通过、预算停止或并列策略误报为任务解决。

## 本机任务成功条件

一次成功验收必须同时满足：

1. 容器退出码为 `0`，未被 OOM 杀死。
2. `scripts/check_neural_run.py` 返回 `backend_verified=true`。
3. 使用 `--require-done` 时返回 `task_solved=true`、`outcome=task_solved`。
4. `summary.json`、`events.jsonl`、神经 trace、镜像/容器配置和日志一起保存。
5. 并列分数、读出沉默、预算耗尽可作为策略结果记录，但不能在 `--require-done` 下计为任务解决。

固定权重策略的输出依赖平台浮点行为。远程 Ubuntu runner 是 x86_64，可能在本机 Linux/arm64 能完成的同一个 demo 上出现合法 READ/TEST 并列。因此远程干净环境检查区分两件事：`backend_verified=true` 只证明真实神经后端和证据链有效；`task_solved=true` 才证明容器内任务进入 `DONE`。

## 远程干净环境检查条件

`FlyCoder neural Docker check` 要求 `backend_verified=true`，并接受以下明确的 checker 结果：

- `task_solved`
- `tied_scores`
- `silent_readouts`
- `budget_exhausted`

后端错误、缺 trace、非法动作、伪通过、日志结构不一致或容器被 OOM 杀死仍会让工作流失败。manifest 会记录 `accepted_outcomes`，因此通过工件可以确认这次结果是否被当作策略结果而不是任务解决。

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

如果要把非任务解决结果也保存为策略证据，改用：

```bash
python3 scripts/package_neural_docker_evidence.py \
  --run-dir research/docker-neural-runs/<run-id> \
  --check-report research/docker-neural-check.json \
  --output research/docker-neural-evidence-manifest.json \
  --accepted-outcomes task_solved,tied_scores,silent_readouts,budget_exhausted
```

复查前先将可信证据包展开到项目内的新目录，再按包内布局选择参数。

上述本机打包命令传入单次运行目录，包内路径为 `run/summary.json`。使用明确的 `--summary` 并要求任务成功：

```bash
mkdir -p research/evidence-local-review
tar -xzf research/docker-neural-evidence.tar.gz -C research/evidence-local-review
python3 scripts/check_neural_run.py \
  --summary research/evidence-local-review/neural-docker-evidence/run/summary.json \
  --require-done
```

远程工作流传入运行目录的父目录，包内路径为 `run/<run-id>/summary.json`。将下载的远程 tar.gz 解压到 `research/evidence-remote-review` 后，使用 `--runs`：

```bash
python3 scripts/check_neural_run.py \
  --runs research/evidence-remote-review/neural-docker-evidence/run
```

远程命令允许有完整证据的并列、沉默或预算耗尽，并明确报告 `task_solved=false`。只有要求任务必须成功时才加 `--require-done`；本次远程 `tied_scores` 结果在该模式下应返回非零退出码。不要将本机的扁平目录与远程的 `<run-id>` 子目录混用，也不要在同一展开目录中混合不同证据包。

打包器的 `--require-done` 同样强制要求报告中 `task_solved=true` 且 `outcome=task_solved`，即使 `--accepted-outcomes` 包含策略停止也不会放行。打包器读取已有报告；独立复查仍需重新运行 checker。

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
5. 执行严格日志验收；远程 x86_64 上接受并列、沉默或预算耗尽等明确策略结果。
6. 生成 manifest 和 tar.gz 证据包。
7. 将全部证据上传为 workflow artifact。

这个工作流通过后，可以在目标 commit 的 artifact 中找到 `manifest.json` 与 `neural-docker-evidence.tar.gz`。
