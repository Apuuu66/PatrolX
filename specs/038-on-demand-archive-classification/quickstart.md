# 快速验证：按真实目录进行按需归档分类

**功能**：`038-on-demand-archive-classification`
**日期**：2026-11-02
**关联**：[spec.md](./spec.md)、[plan.md](./plan.md)、[data-model.md](./data-model.md)、[manifest-v5.md](./contracts/manifest-v5.md)

本指南用于实现完成后验证分类配置、按需展开、审计、重建和双模式一致性。所有真实输入必须只读；首次验收优先使用合成样例，确认通过后再对真实包做隔离验证。

## 1. 前置条件

```text
cd <repo-root>
.venv/bin/python build.py install
.venv/bin/python build.py lint
.venv/bin/python build.py test
```

真实包验收额外要求：

- 包路径：`DataCollect/ALL_20261031173253.zip`
- 预期 SHA-256：`df3d09eb065a407193b0178200f195cebf571e7ff1d8ef6266d98e5ccf459687`
- 输出目录：系统临时目录或已忽略的 `output/`
- 检查前后哈希一致；不移动、复制、重命名或重新压缩真实包

## 2. 合成包验证

生成固定结构的真实样例包：

```text
.venv/bin/python tests/fixtures/make_real_package.py /tmp/patrolx-038-input
shasum -a 256 /tmp/patrolx-038-input/ZZapp01BCN_app_Problem_scene_333.zip
```

样例包只用于本地合成验证，不得把生成目录提交到 Git。

### 2.1 UMF 分类与 catalog

使用本地 CLI 或 API 上传，显式指定 `--product UMF`。分类完成后检查 `output/<task_id>/manifest.json`：

```text
version == 5
product == "UMF"
classification.profile == "UMF"
classification.snapshot.config_fingerprint 存在
entries/ignored/conflicts/failures/catalog 均为数组
summary.counts.landed == len(entries)
summary.counts.catalog == len(catalog)
```

预期目标（以 fixture 为准）：

```text
alarm/<告警成员相对路径>
basic/<Basic Information 之后路径>
kpi/<PerfResult 成员相对路径>
other/MESH Application Metrics/<archive_stem>/<成员相对路径>
logs/<service>/<node_path>/<日志名>
chr/<...>.bil
host-debug/<...>
host-system/<...>
other/<未命中 fallback 路径>
```

检查 `catalog[]` 只包含成功落位文件，且路径均能在任务根内解析。不得出现 `.main/`、`prepared/`、`rules/`、`reports/`、`task.json` 或 `execution.log`。

合成包固定基准为：告警 2 个、KPI 73 个、MESH 14 个、Service Logs 98 个、CHR 3 个、Host Debug/System 各 2 个 `.log`。UMF Service Logs 的 98 个业务日志中，13 个为直接文件、85 个由 `.log.gz` 解压得到。

### 2.2 告警与 CSP

构造/使用包含以下路径的样例：

```text
.../Alarm Information/...
.../0/Problems/Alarm Data/...
.../some-wrapper/Alarm Data/...
.../0/其他非告警内容
```

预期：

- `Alarm Information/` 与 `Alarm Data/` 下文件全部进入 `alarm/`；
- 告警压缩包递归展开，0 字节、仅表头和零记录文件仍落位；
- `0/` 下非告警文件不进入 catalog；
- CSP 非告警内容不进入工作分类现场。

### 2.3 Service Logs 与 CHR

检查 `Service Logs (Problem)/ServiceLogs_*.zip`：

```text
logs/ 中恰好 98 个业务主日志
85 个 .log.gz 解压为 .log
RScheck、dblog、UFP、monitor、start/proxy、bbox、LocalLogReport.csv 不出现在 catalog
```

检查 `CHR Information/ServiceLogs_*.zip`：

```text
chr/ 中恰好有 3 个 .bil 文件
LocalLogReport.csv 及其他未选成员只出现在 ignored[]，不进入 catalog
```

检查 `Host Debugging Logs/DEBUG.tar.gz` 与 `Host System Logs/OS.tar.gz`：

```text
host-debug/ 中 2 个 DEBUG.log
host-system/ 中 2 个 OS.log
同包 README/uptime 等普通成员按 host 根路径保留
```

### 2.4 配置复用与重建

1. 连续执行两次相同分类，第二次应复用现场，manifest 的指纹相同。
2. 只修改 `deploy/config/classify_rules.yaml` 的注释或空白，再次执行应复用。
3. 修改任一有效 route、target、product 或 path limit，再次执行应触发重建；旧分类根残留不得进入 catalog。
4. 删除或损坏 `manifest.json`，再次执行应重建分类现场。
5. 删除或损坏 `.main/`，再次执行应复核原始包 checksum 后重建证据现场。

每次重建后确认原始包 checksum 未变化。

### 2.5 失败边界

构造损坏的子归档、超过深度/大小限制的归档、路径穿越成员和链接成员：

- 单个子归档失败只使 classification 为 `WARN` 并写 `failures[]`；
- 其他合法文件继续进入 catalog；
- 路径穿越、链接、重复成员和预算超限不得写入目标根；
- 配置无效或主包无法建立 `.main/` 时 classification 为 `ERROR`，prepare/inspect 不得执行。

## 3. API 验证

在线 API 上传巡检包时必须提供 `package_kind=inspection`、province、operator 和 product；product 先 trim，再统一大写。

预期：

```text
product=" umf " → 202，任务 customer.product == "UMF"
缺少 product → 400 missing_product
product="foo" → 400 invalid_product
log_supplement 携带 product/province/operator → 400 metadata_not_applicable
同名同 checksum 同 kind 同 product → 202 幂等返回既有 task_id
同名不同 checksum → 409 package_checksum_conflict
同名同 checksum 不同 kind → 409 package_kind_conflict
同名同 checksum 同 inspection 不同 product → 409 package_product_conflict
```

同步验证 `docs/api/openapi.yaml` 描述的响应与 `app/models/schemas.py`、生成客户端一致。

## 4. 前端验证

```text
cd web
npm run test
npm run build
```

并执行 Playwright：

```text
cd <repo-root>
.venv/bin/python build.py e2e
```

检查：

- 选择巡检包时网元类型必填；
- 选择日志补充包时省份、运营商、网元类型字段隐藏且不会提交；
- product 输入 `/` 显示为 `UMF` 或 `CSP`；
- 上传后准备页只显示 `pkg.extract.main` 与 `pkg.extract.classification`；
- 缺少 product、非法 product、kind/product 冲突显示稳定错误文案。

## 5. 真实包只读验收

**必须使用隔离运行目录**，不要让输出进入 Git 工作树：

```text
REAL_PACKAGE="$PWD/DataCollect/ALL_20261031173253.zip"
ISOLATED_ROOT="$(mktemp -d /tmp/patrolx-038-real.XXXXXX)"
shasum -a 256 "$REAL_PACKAGE"
```

通过测试入口或 `--product UMF --package-kind inspection` 对真实包运行分类，输出写入 `ISOLATED_ROOT`。完成后：

```text
shasum -a 256 "$REAL_PACKAGE"
```

两次哈希必须相同。按 [spec.md](./spec.md) 的成功标准核对：

```text
告警文件：共 2 个（UMF 1 个、CSP 1 个），进入同一个 alarm/
CSP 0/Problems/Alarm Data/ 告警：全部进入 alarm/，同树非告警进入 catalog：0
PerfResult_*.zip：73 个成员进入 kpi/
CollectExport*.zip：14 个 CSV 进入 other/MESH Application Metrics/
Service Logs：98 个业务主日志；85 个 .log.gz 解压
CHR：3 个 .bil 可读取
原始包 SHA-256：df3d09eb065a407193b0178200f195cebf571e7ff1d8ef6266d98e5ccf459687
```

如果任一项不满足，保留隔离输出用于诊断，不得修改真实包或把输出加入版本控制。

## 6. 完成判定

- lint、test、contract、gen-web-api、verify、web-build、e2e 全部通过；
- `contract` 与 `gen-web-api` 后生成客户端无未提交漂移；
- 合成包和真实包验收结果可重复；
- 原始包 SHA-256 前后一致；
- manifest v5 的 catalog 与物理文件一致；
- 分类日志可解释每条命中、忽略、冲突和失败；
- `git status` 不含真实包、解压输出、数据库、日志或临时验收目录。
