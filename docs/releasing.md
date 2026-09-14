# 发布流程

目标版本：`0.2.0`。发布规范对应 Python 3.9+，基础镜像和神经后端使用 Python 3.11。

## 1. 代码与测试

```bash
python3 -m unittest discover -s tests -v
.venv-neural/bin/python -m unittest discover -s tests -v
```

第二个命令需要先完成 `bash scripts/setup_neural.sh`。基础 CI 还会在 Python 3.9、3.11、3.12 上重复测试。

## 2. 构建发行包

```bash
python3 -m pip install build
python3 -m build
```

产物位于 `dist/`：

- `flycoder-0.2.0-py3-none-any.whl`
- `flycoder-0.2.0.tar.gz`

wheel 必须包含：

- `flycoder/examples/buggy_repo/calculator.py`
- `flycoder/examples/buggy_repo/tests/test_calculator.py`

## 3. 从 wheel 验收

在源码目录之外安装并运行，避免误用工作区文件：

```bash
python3 -m venv /tmp/flycoder-release-check
/tmp/flycoder-release-check/bin/pip install --no-index --no-deps dist/flycoder-0.2.0-py3-none-any.whl
cd /tmp
/tmp/flycoder-release-check/bin/flycoder demo --mock-first-pass
```

输出必须为 `status=done`。

## 4. 神经后端发布证据

基础 CI 不下载 MaleCNS 数据。需要在 GitHub Actions 中手动触发 `FlyCoder neural Linux check`，它会：

1. 在 Linux 上安装编译工具；`setup_neural.sh` 会把 venv 内 pip 固定到 `26.2.1`，因为 `--build-constraint` 需要 pip ≥ 25.0。
2. 下载并校验 MaleCNS v1.0。
3. 构建 DOOMFLY 内核并运行上游数值测试。
4. 运行项目测试和离线真实连接组 demo。
5. 上传 `neural-validation.json`、运行日志和 summary。

只有该工作流在目标提交上通过，才能把 Linux 原生神经后端标记为已实测。

## 5. GitHub 发布

1. 确认基础 CI、package job 和手动神经工作流均通过。
2. 创建并推送与 `pyproject.toml` 一致的 tag，例如 `v0.2.0`。
3. 创建 GitHub Release，上传 `dist/` 中的 wheel 和 sdist。
4. 在 release notes 中明确：这是固定权重原型，不包含神经学习；FlyWire 未接入；神经 Docker 链路以手动工作流结果为准。

校验文件：

```bash
shasum -a 256 dist/*
```

不要把 `.env`、`vendor/`、`research/`、`runs/` 或 `*.zip` 加入发布提交。
