# 契约：持续集成门禁（批次 A）

**日期**：2026-10-10 | **规格**：[../spec.md](../spec.md) | **计划**：[../plan.md](../plan.md)

## 触发条件

- 推送到 `main`；
- 任意合并请求（pull request）。

## Job 1：backend（ubuntu-latest，Python 3.12，timeout 15 分钟）

| 步骤 | 命令 | 通过条件 |
| --- | --- | --- |
| 安装 | `python build.py install` | 按 `requirements-lock.txt` 建立 `.venv` 并 `--no-deps -e .` 成功 |
| 静态检查 | `python build.py lint` | Ruff check 与 format check 无问题 |
| 测试 | `python build.py test` | pytest 全绿，含契约三条守卫 |
| 契约 | `python build.py contract` | FastAPI 生成结果与 `docs/api/openapi.yaml` 路径/方法/operationId 完全一致 |

## Job 2：frontend（ubuntu-latest，Node 22，timeout 15 分钟，工作目录 `web/`）

| 步骤 | 命令 | 通过条件 |
| --- | --- | --- |
| 安装 | `npm ci` | 按 `package-lock.json` 精确安装 |
| 客户端零漂移 | `npm run gen-api` + `git diff --exit-code -- src/api/client.ts` | 再生成后无差异 |
| 构建 | `npm run build` | `tsc -b && vite build` 成功 |
| 单测 | `npm test` | node --test 与 vitest 全绿 |

## 与 build.py 的关系

- 后端门禁统一走 `python build.py install/lint/test/contract`；
- 前端 job 的 `npm ci` / `npm run gen-api` / `npm run build` / `npm test` 与 `build.py` 调度的前端工具链同源同参（`build.py web-build` 即 `npm run build`、`build.py e2e` 即 `npm run e2e`），不引入第二套构建系统，也不改变前端工具链语义。

## 明确排除

- 不运行 `python build.py verify`（完整本地全流程）；
- 不运行 `npm run e2e`（Playwright）；
- 不做自动修复：门禁不写回契约、客户端或代码。

## 本地等价

本地按同序执行上述 8 条命令即可复现门禁结论；`quickstart.md` 给出逐步验证与预期结果。
