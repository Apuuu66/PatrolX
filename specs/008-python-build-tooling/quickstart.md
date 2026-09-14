# 快速验证：统一 Python 构建工具

## 前置条件

1. 安装 Python 3.11+。
2. 克隆仓库并进入仓库根目录。
3. 不安装 GNU Make 和 uv，以验证标准流程不依赖它们。
4. 前端/端到端验证另需 Node.js/npm；端到端浏览器可由安装命令准备。

## 1. 安装后端环境

```bash
python build.py install
```

预期：

- `.venv` 由官方 Python 标准能力创建。
- 后端、测试和 lint 依赖按 `requirements-lock.txt` 精确安装。
- 不调用 uv，不读取 `uv.lock`。

## 2. 运行质量门禁

```bash
python build.py lint
python build.py test
python build.py contract
```

预期：

- 三个命令均零退出。
- Ruff、pytest 和 OpenAPI 校验结果与旧入口等价。
- 缺少 `.venv` 时提示先执行 `python build.py install`。

## 3. 生成前端 API 客户端

```bash
python build.py gen-web-api
```

预期：

- 命令调用现有前端生成流程。
- `web/src/api/client.ts` 的语义与 OpenAPI 契约保持一致。

## 4. 本地全流程巡检

将有效 `zip` 或 `tar.gz` 数据包放入 `uploads/` 后执行：

```bash
python build.py verify
```

预期：

- 本地巡检任务生成一个任务目录。
- 规则结果、执行日志和报告的业务语义与迁移前一致。
- 原始上传包不被修改。

## 5. 单规则重跑

以实际规则代码替换 `<rule_code>`：

```bash
python build.py verify-one --rule <rule_code>
```

预期：

- 只重跑目标规则。
- 目标规则 JSON、任务摘要和 HTML 报告按既有语义刷新。
- 缺失 `--rule` 时返回用法错误和帮助。

## 6. 在线服务启动

```bash
python build.py run
```

预期：

- 后端 API 与前端页面按现有默认地址启动。
- 缺少 Node/npm 时返回明确前置条件提示。
- Ctrl+C 停止语义保持可用。

## 7. 前端构建与端到端

```bash
python build.py web-install
python build.py web-build
python build.py e2e-install
python build.py e2e
```

预期：

- 前端依赖安装、构建和端到端检查由统一入口发起。
- npm/Playwright 的既有行为与输出保持等价。

## 8. 平台与旧入口看护

在 Windows、macOS 和 Linux 至少验证：

```bash
python build.py install
python build.py lint
python build.py test
```

同时确认：

- 仓库根目录不存在 `Makefile`。
- 仓库根目录不存在 `run-offline.sh`、`run-online.sh`。
- 仓库根目录不存在 `uv.lock`。
- 权威文档不要求 `make` 或 uv。
- 命令不依赖 Unix shell。
