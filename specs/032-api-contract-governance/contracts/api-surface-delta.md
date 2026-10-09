# 契约增量：API 表面治理（批次 A）

**日期**：2026-10-10 | **规格**：[../spec.md](../spec.md)

## 1. 公共接口变更

| 变更 | 接口 | operationId | 说明 |
| --- | --- | --- | --- |
| 删除 | `POST /api/v2/tasks` | `createTaskV2` | 破坏性删除（用户明确批准）；替代入口为 `POST /api/v3/tasks`（`createTaskV3`），已交付且为前端现行调用 |
| 删除 | `/api/v4/**` | —— | v4 路由为空壳，无任何操作；删除路由注册并清除文档引用 |

**冻结不变**：`/api/v1/**`、`/api/v2/**`（除创建）、`/api/v3/tasks`、`/api/v5/**` 的全部现有路径、字段语义与行为保持不变。

**迁移要求**：契约（`docs/api/openapi.yaml`）先更新；后端路由随后删除；`web/src/api/client.ts` 再生成后与仓库零差异；8 个测试文件的 15 处创建调用迁移到 v3 并补齐 `package_kind=inspection`、`province`、`operator`。

## 2. 守卫规则（必须在 `tests/test_contract.py` 中以 pytest 固化）

| 编号 | 规则 | 判定 | 失败输出 |
| --- | --- | --- | --- |
| G-01 | operationId 唯一且非空 | 遍历全部 path × method 的 operationId，重复或缺失即失败 | 重复/缺失的 operationId 及涉及路径 |
| G-02 | 无空版本前缀 | `app.api.router` 中 `*_router` 的 prefix 集合与契约版本前缀集合相等，且每个前缀操作数 ≥ 1 | 空版本或孤儿版本的前缀名 |
| G-03 | 同一能力唯一当前入口 | 按 `(method, 去版本前缀路径)` 分组；多版本组中最大版本号入口必须未废弃，其余必须 `deprecated: true` 且描述含替代入口路径 | 分组、涉及版本、缺失的废弃/替代标注 |
| G-04 | 契约与生成客户端零漂移 | `npm run gen-api` 后 `git diff --exit-code -- src/api/client.ts` 为空 | git diff 原始输出（门禁步骤，不在 pytest 内） |

**当前违规基线**：G-03 在改造前会命中 `POST /tasks`（v2 + v3）——守卫先行落地应失败（红），删除 v2 创建后转绿。这是本批次唯一的既有违规组。

## 3. 验收命令

```bash
python build.py contract                 # 契约与实现一致，且无 /api/v2/tasks 创建、无 v4
python build.py test                     # 含 G-01/G-02/G-03 与迁移后的既有套件
cd web && npm ci && npm run gen-api && git diff --exit-code -- src/api/client.ts   # G-04
```
