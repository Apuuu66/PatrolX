# 验收指南：API 契约治理与持续集成门禁

**日期**：2026-10-10 | **规格**：[spec.md](spec.md) | **契约**：[contracts/api-surface-delta.md](contracts/api-surface-delta.md)、[contracts/ci-gate.md](contracts/ci-gate.md)

## 前置条件

- 仓库根目录为工作目录；Python 3.11+（推荐 3.12）；Node.js 22；网络可用（首次安装依赖）。
- 不需要 GitHub 环境即可完成本指南的场景 1–4；场景 5 验证远端门禁。

## 场景 1：后端门禁本地复现

```bash
python build.py install
python build.py lint
python build.py test
python build.py contract
```

预期：四条命令全部通过；`build.py test` 中包含 G-01（operationId 唯一）、G-02（无空版本前缀）、G-03（同一能力唯一当前入口）三条守卫与迁移后的既有套件。

## 场景 2：API 表面与行为核对

```bash
# 1) 契约中旧创建入口与 v4 均已消失
grep -n '^  /api/v2/tasks:' docs/api/openapi.yaml || echo "OK：v2 创建路径已移除"
grep -n '^  /api/v4' docs/api/openapi.yaml || echo "OK：契约无 v4"

# 2) 后端回归断言（随 tasks 落地的测试用例；build.py test 不透传参数，直接调 pytest）
.venv/bin/python -m pytest -k "operation_ids_unique or empty_version_prefix or single_current_entry or v2_create_entry_removed or v4_prefix_not_registered"

# 3) 运行服务做冒烟
python build.py run &
.venv/bin/python tests/fixtures/make_real_package.py /tmp/patrolx-uploads
curl -s -o /dev/null -w "v2 create -> %{http_code}\n" -X POST http://127.0.0.1:8000/api/v2/tasks
curl -s -X POST http://127.0.0.1:8000/api/v3/tasks \
  -F package_file=@/tmp/patrolx-uploads/ZZapp01BCN_app_Problem_scene_333.zip \
  -F package_kind=inspection -F province=江苏 -F operator=移动
```

预期：`v2 create -> 404`（或 405，取决于平台默认行为，非 2xx 即可）；v3 返回 `202` 与 `task_id`；v2 的列表/详情/重跑/日志等既有命令不受影响（由场景 1 的既有套件覆盖）。

## 场景 3：前端客户端零漂移与构建

```bash
cd web
npm ci
npm run gen-api
git diff --exit-code -- src/api/client.ts   # G-04：预期无输出、退出码 0
grep -n "createTaskV2" src/api/client.ts || echo "OK：生成客户端无 v2 创建操作"
npm run build
npm test
```

预期：diff 为空；构建与单测通过。若 diff 非空，说明契约变更后未重新生成客户端，应重新生成并提交。

## 场景 4：文档与规格状态抽查

```bash
grep -rn "/api/v4" docs/architecture.md docs/roadmap.md docs/design/mechanisms.md docs/design/entrypoints.md \
  || echo "OK：当前系统文档无 v4 引用"
grep -m1 '已被替代' specs/015-kpi-dynamic-config/spec.md
for d in 016-ui-derived-metrics 025-kpi-cross-task-trend 026-kpi-device-version-compare 027-site-device-ledger 028-ledger-crud 030-alarm-flapping; do
  grep -m1 '^\*\*状态\*\*' "specs/$d/spec.md"; done
grep -rn "/api/v4" specs/016-ui-derived-metrics | head
```

预期：四份文档无 v4；015 显示"已被替代"并注明替代者；六个规格显示"已实现"；016 内残留的 v4 字样均带"历史设计/已替代"标注。

## 场景 5：CI 门禁

- 推送到 `main` 或发起合并请求后，GitHub Actions 出现 `backend` 与 `frontend` 两个 job，均在 15 分钟内结束；
- 两个 job 的步骤与 [contracts/ci-gate.md](contracts/ci-gate.md) 一致；不含 `verify` 与 E2E 步骤；
- 故意在 `docs/api/openapi.yaml` 或 `web/src/api/client.ts` 制造不一致后推送：对应 job 变红并阻止合入（需仓库已把检查配置为必需）。

## 完成定义

- 场景 1–4 在本地全绿；
- 场景 5 在远端门禁复现同样结论；
- 契约中 `(method, 去版本前缀路径)` 重复能力组为 0；仓库内对 `POST /api/v2/tasks` 的第一方调用为 0（历史规格记录除外）。
