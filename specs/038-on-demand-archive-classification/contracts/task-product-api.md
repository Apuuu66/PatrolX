# 契约：任务网元类型与上传 API（POST /api/v3/tasks）

**状态**：Plan 阶段冻结
**适用接口**：`POST /api/v3/tasks`
**权威源**：`docs/api/openapi.yaml`
**消费者**：在线上传 API、本地 CLI、任务服务、worker、分类配置、台账解析器与 Web 上传表单
**约束**：网元类型只来自上传时声明的任务元数据；不得从包名、目录、台账内容或压缩包成员反推。

## 1. 领域值

### 1.1 Product

```text
UMF
CSP
```

规范化规则：

1. 将输入转换为字符串后执行 `trim()`。
2. 统一转为大写。
3. 只接受 `UMF`、`CSP`。
4. 任务元数据、分类 profile、台账筛选、CLI 输出和 API 响应使用同一个规范化值。
5. `deploy/config/dicts.yaml` 的 product code 必须为 `UMF`、`CSP`。

`Product` 是巡检包专用元数据。日志补充包没有网元类型，值为 `null`。

### 1.2 PackageKind

```text
inspection
log_supplement
```

- `inspection`：巡检包，必须携带省份、运营商和网元类型。
- `log_supplement`：日志补充包，不得携带省份、运营商或网元类型。
- `package_kind` 是 multipart 必填字段。

## 2. 创建任务请求

`POST /api/v3/tasks` 使用 `multipart/form-data`。现有路径和字段名保持不变：

| 字段 | 类型 | 巡检包 | 日志补充包 | 说明 |
| --- | --- | --- | --- | --- |
| `package_file` | file | 必填 | 必填 | `zip`、`tar`、`tar.gz`、`tgz`；文件名长 255 字节以内 |
| `package_kind` | string | 必填 | 必填 | `inspection` 或 `log_supplement` |
| `name` | string | 可选 | 可选 | 任务展示名；缺省使用包名 |
| `province` | string | 必填 | 禁止 | 去首尾空白后不得为空 |
| `operator` | string | 必填 | 禁止 | 去首尾空白后不得为空 |
| `product` | string | 条件必填 | 禁止 | `trim().upper()` 后只允许 `UMF`、`CSP` |

为保持 OpenAPI 3.1 生成客户端的兼容性，`Body_createTaskV3.product` 在 OpenAPI 中继续声明为 optional nullable string；巡检包的条件必填由服务端运行时校验和接口描述共同冻结。`openapi.yaml` 的接口描述必须明确该条件，生成的前端客户端与手写 API 封装不得自行改写字段名。

### 2.1 巡检包校验

处理顺序固定为：

1. `package_kind` 必须是合法枚举值。
2. 文件名、扩展名和上传大小先通过现有上传前置校验。
3. `province.strip()` 为空时返回 `400 missing_province`。
4. `operator.strip()` 为空时返回 `400 missing_operator`。
5. `product` 缺失或 `product.strip()` 为空时返回 `400 missing_product`。
6. `product.strip().upper()` 不在 `{UMF, CSP}` 时返回 `400 invalid_product`。
7. 通过校验后，将规范化 product 写入 `TaskRecord.customer["product"]`，并随任务执行上下文传递。

`missing_product` 的 `detail` 至少包含 `package_kind=inspection`。`invalid_product` 的 `detail` 至少包含规范化前的非空输入值和允许值列表。

### 2.2 日志补充包校验

日志补充包：

- 不要求 province、operator、product。
- `province`、`operator`、`product` 任一字段去首尾空白后非空时返回 `400 metadata_not_applicable`。
- 空字符串或仅空白字段按未提供处理，不写入任务元数据。
- 分类 profile 固定为 `GENERIC`，台账解析器必须返回 `not_applicable`，不得执行 UMF/CSP 台账匹配。

## 3. 错误契约

| HTTP | `code` | 触发条件 |
| --- | --- | --- |
| `400` | `missing_product` | 巡检包缺少 product，或值为空白 |
| `400` | `invalid_product` | 巡检包 product 规范化后不是 `UMF`/`CSP` |
| `400` | `missing_province` | 巡检包缺少省份 |
| `400` | `missing_operator` | 巡检包缺少运营商 |
| `400` | `metadata_not_applicable` | 日志补充包携带非空 province/operator/product |
| `409` | `package_checksum_conflict` | 同名任务已存在，且上传包 checksum 与首次接收 checksum 不同 |
| `409` | `package_kind_conflict` | 同名任务、同一 checksum，但请求 `package_kind` 与既有任务不同 |
| `409` | `package_product_conflict` | 同名巡检包、同一 checksum 与 kind，但 product 不同，或历史任务没有 product |

错误响应继续使用统一结构：

```json
{
  "code": "invalid_product",
  "message": "巡检包网元类型仅支持 UMF 或 CSP",
  "detail": {
    "value": "XYZ",
    "allowed": ["UMF", "CSP"]
  }
}
```

错误码是稳定契约，调用方不得解析中文 `message` 判断类型。

## 4. 同名任务恢复与冲突矩阵

同名任务的判定必须使用“任务首次接收时记录的 checksum”，不得先比较 product 或 package kind。现场包存在时，现场包 checksum 必须与首次接收 checksum 一致；现场已清理时，使用数据库保存的首次接收 checksum 判断。固定顺序如下：

| 顺序 | checksum | 请求 kind vs 既有 kind | 请求 product vs 既有 product | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 不同 | 任意 | 任意 | `409 package_checksum_conflict` |
| 2 | 相同 | 不同 | 任意 | `409 package_kind_conflict` |
| 3 | 相同 | 都是 inspection | 不同 | `409 package_product_conflict` |
| 4 | 相同 | 都是 inspection | 既有任务缺 product | `409 package_product_conflict`，提示补充任务元数据后重试 |
| 5 | 相同 | 都是 inspection | 规范化后相同 | `202`，返回既有 task_id 与 `Location` |
| 6 | 相同 | 都是 log_supplement | 两者均无 product | `202`，返回既有 task_id 与 `Location` |

补充规则：

- 历史 `TaskRecord.package_kind` 缺失或不可解析时，按既有兼容读取语义视为 `inspection`；随后仍执行第 3、4 项 product 判定。
- 第 5、6 项为幂等恢复。磁盘现场被留存策略清理时，将上传包写回 `uploads/<task_id>/<stored_name>`，但不自动重跑任务、不改任务结果、不触发额外留存清理。
- 现场包 checksum 与首次接收 checksum 不一致时，不信任现场，按 `package_checksum_conflict` 拒绝。
- product 或 kind 冲突不得删除既有任务，也不得通过“覆盖确认”隐式绕过；覆盖流程必须先获得用户确认并删除旧任务后重新创建。

## 5. 任务写入模型

不新增 SQLite 列：

- `TaskRecord.package_kind` 继续保存 `inspection` 或 `log_supplement`。
- `TaskRecord.customer` 继续是 JSON 对象；巡检包写入 `{"province": ..., "operator": ..., "product": "UMF"}`。
- `TaskSummary.customer_product` 与任务详情继续从 `customer.product` 读取。
- product 不得写入 `system_id` 目录层，不得成为 `task_id` 或输出目录名。
- 历史巡检任务 product 为 null 时保持 null，不从真实目录自动回填。

## 6. 执行上下文传播

任务执行链必须保持同一值，不得在各层重新猜测或改变大小写：

```text
multipart product
  → normalized Product
  → TaskRecord.customer["product"]
  → TaskService._task_info()
  → run_task(product=...)
  → RuleContext(product=...)
  → UnitRequest(product=...)
  → pkg.extract.classification profile
  → ClassificationSnapshot.product
  → CatalogEntry.product / ManifestV5.product
  → inventory parser normalized_product
```

- `RuleContext` 增加 `product: Product | str | None` 和 `package_kind: PackageKind`。
- `UnitRequest` 增加可序列化的 `product: str | None` 与 `package_kind: str`；worker 只能从请求恢复，不得读取全局 product。
- `TaskService._execute()` 的单规则重跑与重建分支必须传递持久化 product 和 package kind。
- 分类器收到的巡检 product 必须精确等于 profile `UMF`/`CSP`，不得回退 `GENERIC`。
- 台账解析器收到的 product 必须先执行同一 `trim().upper()` 规范化，再与设备记录的网元类型比较。
- 日志补充包的 product 必须为 null，profile 必须为 `GENERIC`。

## 7. CLI 同构

`app/cli.py` 的 `run`、`run-one`、`explain-match` 增加同名字段：

| 参数 | `run` | `run-one` | `explain-match` | 默认/规则 |
| --- | --- | --- | --- | --- |
| `--product` | 条件必填 | 条件必填 | 条件必填 | `inspection` 时必须为 UMF/CSP |
| `--package-kind` | 可选 | 可选 | 可选 | 默认 `inspection`；日志补充包必须显式指定且禁止 product |

校验结果与 API 相同：

- `missing_product`、`invalid_product`、`metadata_not_applicable` 分别以非零退出码和稳定错误码输出。
- 同一包名生成相同 task_id。
- 只有 product/kind 参与分类 profile 和台账筛选，不改变 `source_patterns` 语义。
- CLI 不具备在线恢复矩阵时，仍必须拒绝“同一 task_id 的既有现场 product/kind 不一致”，并输出对应冲突码，不得覆盖既有任务。
- `explain-match` 返回 v5 manifest 的 classification snapshot、catalog 匹配和失败/忽略摘要，不读取旧分类目录。

## 8. Web 上传行为

`web/src/pages/TaskListPage.tsx` 上传表单必须：

- 巡检包将“网元类型”设为必填，并使用 product 字典选项。
- 日志补充包不显示省份、运营商和网元类型字段。
- 提交表单前把 product 执行 `trim().toUpperCase()`。
- 巡检包只在 product 规范化成功后才加入 FormData；日志补充包绝不追加 province/operator/product。
- 收到 `missing_product`、`invalid_product` 或三类同名冲突码时显示对应可操作错误，不把冲突静默转换为覆盖。
- 前端 API 调用以 `docs/api/openapi.yaml` 生成的客户端为准；不得手写与 OpenAPI 不一致的字段或错误码分支。

## 9. OpenAPI、Schema 与测试同步

实现本契约时必须同步：

- `docs/api/openapi.yaml`：补充 product 条件说明、错误响应说明和条件校验语义。
- `app/models/schemas.py`：Product/PackageKind 标准化与任务摘要字段。
- `app/api/router.py`：条件校验、恢复矩阵和错误码。
- `web/src/api/client.ts`：重新生成；若项目保留薄封装，只能转发已生成操作。
- `tests/test_api_robustness.py`、`tests/test_task_restore.py`、`tests/test_tasks_scene_missing.py`、`tests/test_online_identity.py`、`tests/test_cli_explain_match.py`、`web/src/pages/TaskListPage.test.tsx`：覆盖规范化、条件必填、恢复顺序、日志补充包禁用字段和前后端一致性。

## 10. 验收断言

- `product=" umf "` 创建巡检包后，存储和响应均为 `UMF`。
- 巡检包缺 product 返回 `missing_product`，非法值返回 `invalid_product`。
- 日志补充包携带 product、province 或 operator 返回 `metadata_not_applicable`。
- 同名同 checksum、同 kind、同 product 返回既有 task_id，`202`，不自动重跑。
- 同名同 checksum 但 kind 不同返回 `package_kind_conflict`。
- 同名同 checksum、同 inspection kind 但 product 不同返回 `package_product_conflict`。
- 同名不同 checksum 永远优先返回 `package_checksum_conflict`。
- CLI 与 API 对同一包、同一 product/kind 产生相同 profile、catalog 路径和 inventory 过滤结果。
- 准备页只显示 `pkg.extract.main` 与 `pkg.extract.classification` 两个隐藏解压单元。
