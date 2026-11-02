# 契约：任务解压与分类清单 v5

**状态**：Plan 阶段冻结
**文件名**：`output/<task_id>/manifest.json`
**版本**：`5`
**消费者**：`pkg.extract.main`、`pkg.extract.classification`、`TaskFileCatalog`、执行器、准备页、CLI `explain-match`
**约束**：Manifest v5 是分类现场的唯一发布凭据；无效或不存在的 v5 不得被复用。

## 1. 顶层 JSON

```json
{
  "version": 5,
  "main": {
    "checksum": "df3d09eb065a407193b0178200f195cebf571e7ff1d8ef6266d98e5ccf459687",
    "count": 96,
    "evidence_path": ".main",
    "evidence_fingerprint": "64-lowercase-hex",
    "reused": false
  },
  "product": "UMF",
  "classification": {
    "config_fingerprint": "64-lowercase-hex",
    "profile": "UMF",
    "snapshot": {
      "package_kind": "inspection",
      "product": "UMF",
      "profile": "UMF",
      "ruleset": "UMF_ARCHIVE_V1",
      "config_fingerprint": "64-lowercase-hex",
      "extraction_policy_fingerprint": "64-lowercase-hex",
      "path_limit_fingerprint": "64-lowercase-hex",
      "scene_root": ".main/MKTHUHUMFW01_UMF Problem scene_331/331/UMF Problem scene",
      "target_roots": ["alarm", "basic", "chr", "debug", "host-debug", "host-system", "kpi", "logs", "mml", "operation-log", "other", "status"],
      "budgets": {
        "max_archive_depth": 8,
        "max_member_path_depth": 12,
        "max_archive_files": 100000,
        "max_task_files": 200000,
        "max_file_bytes": 2147483648,
        "max_total_bytes": 3221225472
      }
    }
  },
  "path_limit": {
    "enabled": false,
    "limit": null,
    "fingerprint": "64-lowercase-hex"
  },
  "entries": [],
  "ignored": [],
  "conflicts": [],
  "failures": [],
  "catalog": [],
  "summary": {
    "counts": {
      "landed": 0,
      "ignored": 0,
      "conflicts": 0,
      "failures": 0,
      "catalog": 0
    },
    "by_route": {},
    "by_category": {},
    "by_action": {},
    "by_status": {
      "landed": 0,
      "ignored": 0,
      "failed": 0
    }
  }
}
```

顶层键集合严格等于：

```text
version
main
product
classification
path_limit
entries
ignored
conflicts
failures
catalog
summary
```

未知顶层键、缺失键、错误类型、重复 JSON key 均使 manifest 无效。

## 2. main

`main` 键集合严格为 `{checksum, count, evidence_path, evidence_fingerprint, reused}`。

- `checksum`：原始上传包 SHA-256，64 个小写十六进制字符。
- `count`：`.main/` 内普通文件数，非负整数，不含目录和链接。
- `evidence_path`：固定为 `.main`。
- `evidence_fingerprint`：证据现场内容指纹，64 个小写十六进制字符。
- `reused`：本次执行是否复用了既有有效 `.main/`，boolean。

证据指纹算法：

1. 递归列出 `.main/` 下全部普通文件，拒绝任何 symlink、目录 symlink 和非普通文件。
2. 得到相对 POSIX 路径、文件字节数和文件 SHA-256。
3. 按相对路径的字节序升序排序。
4. 构造数组 `[{"path": "...", "size": 123, "sha256": "..."}, ...]`。
5. 使用 UTF-8、`sort_keys=True`、`separators=(",", ":")` 的 JSON 序列化。
6. 对序列化字节计算 SHA-256，输出 64 个小写十六进制字符。

证据指纹必须可由 `.main/` 内容重新计算并完全一致。任一文件内容、路径或大小变化都视为证据损坏。

## 3. product 与 classification

### 3.1 product

- 巡检包：只允许 `UMF`、`CSP`，必须与任务规范化 product 一致。
- 日志补充包：必须为 `null`。
- `classification.profile`：巡检包为 `UMF` 或 `CSP`；日志补充包为 `GENERIC`。
- 不允许从包名、真实目录或台账内容反推 product。

### 3.2 classification

`classification` 键集合严格为 `{config_fingerprint, profile, snapshot}`。

- `config_fingerprint`：当前已加载分类配置的语义指纹，必须等于 `snapshot.config_fingerprint`。
- `profile`：`UMF`、`CSP` 或 `GENERIC`，必须等于 `snapshot.profile`。
- `snapshot` 键集合严格为：

```text
package_kind
product
profile
ruleset
config_fingerprint
extraction_policy_fingerprint
path_limit_fingerprint
scene_root
target_roots
budgets
```

- `package_kind`：`inspection` 或 `log_supplement`。
- `ruleset`：对应 profile 的固定标识：
  - `UMF_ARCHIVE_V1`
  - `CSP_ARCHIVE_V1`
  - `GENERIC_LOG_V1`
- `extraction_policy_fingerprint`：当前代码内解压动作、预算、错误分类和原子发布语义的稳定 SHA-256。
- `path_limit_fingerprint`：必须等于顶层 `path_limit.fingerprint`。
- `scene_root`：`.main/` 内规范化的证据相对 POSIX 路径；GENERIC 为 `.main`。
- `target_roots`：本次配置可能写入的顶层分类根，去重并按字符串升序。
- `budgets` 是固定整数对象，必须与下方预算完全一致，不得由任务覆盖。

## 4. path_limit

`path_limit` 键集合严格为 `{enabled, limit, fingerprint}`：

- `enabled`：boolean。
- `limit`：`null` 或正整数。
- `enabled=true` 时 `limit` 必须为正整数；`enabled=false` 时必须为 `null`。
- `fingerprint`：对 `{"enabled": ..., "limit": ...}` 的 canonical JSON 做 SHA-256。

路径超限写为 `failures[].error_code=unsafe_path`，并保留 `path_length/path_limit` 详情。

## 5. entries

`entries[]` 只包含成功落位文件。每项键集合严格为：

```text
source_relative
member_relative
route_id
product
category
original_target
target
action
status
reason
error_code
sha256
size
```

字段约束：

- `source_relative`：原始 `.main/` 文件相对路径，`/` 分隔，不含 `.main/` 前缀。
- `member_relative`：普通文件为 `null`；归档成员为动作完成后的归档内相对路径。嵌套归档使用组合后的成员相对路径。
- `route_id`：命中的 route id。
- `product`：本次 profile 对应 product；GENERIC 为 `null`。
- `category`：配置声明的业务分类。
- `original_target`：未应用冲突消歧的目标相对路径。
- `target`：实际成功目标相对路径，`/` 分隔，必须位于任务目录且不属于保留内部路径。
- `action`：实际动作，只允许 `copy`、`expand`、`decompress`、`expand_recursive`、`select_and_decompress`、`fallback`。
- `status`：固定为 `landed`。
- `reason`：成功原因或 `null`；不得用于失败说明。
- `error_code`：必须为 `null`。
- `sha256`：实际落位文件的 SHA-256。
- `size`：实际落位文件字节数，非负整数。

同一 `(source_relative, member_relative)` 不得产生多个成功 entry，除非目标路径不同且配置显式声明多目的地；v1 不支持多目的地，因此该组合必须唯一。

## 6. ignored

`ignored[]` 记录配置拒绝、未选成员和 catch-all ignore。每项键集合严格为：

```text
source_relative
member_relative
route_id
product
category
original_target
target
action
status
reason
error_code
```

- `status` 固定为 `ignored`。
- `reason` 必须非空，例如 `route_ignored`、`member_not_selected`、`service_check_script`、`report_not_log`。
- `route_id` 可为 `null` 仅用于“无任何 route 命中”的防御性审计；正常 UMF/CSP/GENERIC profile 不得出现该情况。
- `category` 可为 `null`。
- `original_target`、`target` 可为 `null`。
- `error_code` 必须为 `null`。

ignore 不进入 catalog，也不得创建空目标文件占位。

## 7. conflicts

`conflicts[]` 记录目标重名及稳定消歧结果。每项键集合严格为：

```text
source_relative
member_relative
original_target
target
digest
status
```

- `status` 固定为 `resolved`。
- `digest` 是冲突消歧摘要，12 个小写十六进制字符。
- 原始 entry 同时存在于 `entries[]`，其 `original_target` 与 `target` 必须和 conflict 项一致。
- 任何无法消歧的情况必须写 `failures[]`，`error_code=target_conflict`，不得写入 conflict resolved。

消歧算法与 [classification-config.md](classification-config.md) 第 3.8 节完全一致。

## 8. failures

`failures[]` 记录无法成功处理的单文件或归档项。每项键集合严格为：

```text
source_relative
member_relative
route_id
category
action
error_code
reason
```

- `source_relative`：触发失败的原始证据文件。
- `member_relative`：失败发生在归档成员时为成员路径；否则为 `null`。
- `route_id`：命中 route；主包现场无法建立时由 `pkg.extract.main` 的规则结果记录，不写本数组。
- `category`、`action`：可为 `null`，但成功识别 route 后必须填写。
- `error_code`：只能来自第 12 节错误码集合。
- `reason`：非空中文错误说明，可附带路径、大小、预算等 details。

一个归档失败不应删除已成功落位的其他成员。失败项不得进入 catalog。

## 9. catalog

`catalog[]` 是普通规则唯一可见文件列表，只包含成功落位文件。每项键集合严格为：

```text
path
category
route_id
source_relative
sha256
size
```

- `path` 必须与某个 `entries[].target` 相同。
- 路径相对于 `output/<task_id>/`，以 `/` 归一化，不得绝对、不得含 `.` 或 `..`。
- `catalog` 必须按 `path` 字节序升序，去重。
- 每个 path 必须存在、是普通文件、不是 symlink，并重新计算 SHA-256 后与 entry 一致。
- `catalog` 不得包含：
  - `.main/`
  - classify 配置与审计 JSON
  - `manifest.json`、`manifest.json.*`
  - `prepared/`
  - `rules/`
  - 报告、`task.json`、`execution.log`
  - 任何临时/staging/backup 路径

catalog 构建失败时整个 classification 失败，不允许返回部分 catalog。

## 10. summary

`summary` 键集合严格为 `{counts, by_route, by_category, by_action, by_status}`。

- `counts` 键集合严格为 `{landed, ignored, conflicts, failures, catalog}`，值均等于对应数组长度。
- `by_route`：route id 到 landed + ignored + failed 项数。
- `by_category`：非 null category 到 landed + ignored 项数。
- `by_action`：action 到 landed + ignored + failed 项数。
- `by_status`：固定键 `{landed, ignored, failed}`。
- 所有 mapping key 按字符串升序序列化。
- 不可达 route 允许计数为 0；未命中防御项在 `ignored[]` 中有非空 reason。

## 11. 固定预算

| 预算 | 固定值 |
| --- | --- |
| 嵌套归档深度 | 8 |
| 成员路径深度 | 12 |
| 单归档文件数 | 100,000 |
| 任务累计文件数 | 200,000 |
| 单文件解压后大小 | 2 GiB / 2,147,483,648 bytes |
| 任务累计解压字节 | 3 GiB / 3,221,225,472 bytes |

定义：

- Main 外层包深度为 0；进入一层子归档或单文件 GZIP 后增加 1。
- `.tar.gz` 按一个 TAR 归档层计，不重复计 gzip 包装层。
- 成员路径深度是规范化 `/` 段数量，超过 12 即失败。
- 单归档文件数按非目录成员计。
- 任务累计文件数和解压字节跨 main、classification、所有嵌套动作累计。
- 预算超限只影响对应子归档或成员；主包无法建立 `.main/` 时任务失败。

## 12. 错误码

| error_code | 含义 |
| --- | --- |
| `archive_depth_exceeded` | 嵌套归档/GZIP 链深度超过 8 |
| `member_path_depth_exceeded` | 成员路径段数超过 12 |
| `file_count_exceeded` | 单归档文件数超过 100,000 |
| `task_file_count_exceeded` | 任务累计文件数超过 200,000 |
| `file_too_large` | 单个解压文件超过 2 GiB |
| `total_bytes_exceeded` | 任务累计解压字节超过 3 GiB |
| `archive_corrupt` | ZIP/TAR/GZIP 损坏或无法读取 |
| `unsafe_path` | 绝对路径、穿越、越界、非法 NUL、非法路径长度或不受支持的危险路径 |
| `link_rejected` | 符号链接、硬链接或其他链接成员 |
| `duplicate_member` | 同一归档规范化后重复成员；大小写不同也视为重复 |
| `target_conflict` | 无法通过稳定规则消除目标冲突 |
| `invalid_classification_config` | 配置 schema、route、target、overlap 或 fallback 校验失败 |

错误码是稳定契约。禁止通过解析中文异常文本推断错误类型。

## 13. 复用矩阵

分类器必须在任何复用判断前完成配置加载、schema 校验、overlap 校验和当前 snapshot 计算。

| 条件 | 主包 `.main/` | 分类工作现场 | 结果 |
| --- | --- | --- | --- |
| v5 有效，checksum、证据、product、package kind、snapshot、path_limit、catalog 全一致 | 复用 | 复用 | 返回有效 v5，`main.reused=true` |
| 仅注释/空白/route 顺序改变，config fingerprint 不变 | 复用 | 复用 | 语义指纹不变 |
| 配置有效但 config fingerprint 变化 | 复用 | 重建 | 从 `.main/` 重分类 |
| product 或 package kind 变化 | 复用 | 重建 | 使用新 profile |
| extraction policy、target roots、budgets 或 path limit 变化 | 复用 | 重建 | 不读取新外部输入 |
| manifest 缺失、损坏、v4 或 schema 不合法 | 复核 | 重建 | v4 内容不得迁移为 v5 entry |
| `.main/` 缺失、有链接、无法计算指纹或指纹不一致 | 重建 | 重建 | 先复核原始包 checksum |
| 原包 checksum 与任务首次接收 checksum 不同 | 禁止 | 禁止 | `package_checksum_conflict`，不信任任何现场 |
| 分类配置无效 | 可已有 | 禁止复用 | `invalid_classification_config`，classification=`ERROR` |

证据现场有效但分类配置变化时，不得再次读取原始压缩包。证据现场重建时，原始包只读打开，前后 checksum 必须一致。

## 14. 重建与原子发布

1. 在 `output/<task_id>/.classification.staging/` 构建全部目标根、entry、ignored、conflict、failure 和 catalog 候选。
2. 对 staging 内每个 catalog 文件重新核对 size 与 SHA-256。
3. 将 manifest 写入 `.manifest.staging.json` 并完整校验 schema。
4. 将旧 `manifest.json` 移出可见名称，使读取方不再看到旧 catalog。
5. 对本次 target roots、上一有效 target roots 和已知 v4 legacy roots 逐根 staging/backup 交换；失败时按逆序回滚。
6. 使用 `os.replace()` 将 staging manifest 发布为 `manifest.json`。
7. 只在发布成功后清理 backup 和 staging。

Target roots 交换不得触碰：

```text
.main/
.rules/
prepared/
reports/
rules/
task.json
execution.log
data/
任意非分类根路径
```

进程在步骤 4–6 之间中断时，有效 manifest 不存在或不完整；下一次执行必须视为分类现场无效并重建，不得依据残留目录构造 catalog。

## 15. 旧版本迁移

- v1–v4 manifest 一律不可复用。
- 不读取旧 `files/subpackages/log_gz/rejected/policy` 条目作为 v5 事实。
- 旧 `classify_content()`、`peek_*()`、通用扩展名 fallback 和 `extract_policy.yaml` skip/whitelist 不参与 v5。
- v4 已知分类根在 v5 成功发布后清理：`logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other`。
- 清理只能删除分类根，不得删除 `.main/`、原始包、规则结果、prepared、报告、任务元数据或数据库。
- 分类逻辑变化必须递增 `pkg.extract.classification.rule_version`；main 解压协议变化必须递增 `pkg.extract.main.rule_version`。

## 16. Catalog 消费契约

`TaskFileCatalog.build(data_dir)`：

1. 只读取 `manifest.json`。
2. 要求有效 `version=5` 和完整 catalog/summary 一致性。
3. 按 catalog 顺序返回相对路径。
4. 每个 path 解析时必须仍在任务根内，且存在于 catalog 集合。
5. 不扫描 `WORK_CATEGORIES`，不递归推断额外文件。
6. 任一 catalog path 缺失、类型错误、symlink 或摘要不符时抛出明确错误。

普通规则无匹配时返回 `skip`，`skip_reason` 至少包含：

```text
source_patterns 未匹配到分类清单文件: <patterns>; profile=<profile>; config=<fingerprint>; ignored=<N>; failures=<N>
```

隐藏 `pkg.extract.main` 或 `pkg.extract.classification` 返回 `ERROR` 时，执行器必须阻断 prepare 和 inspect。classification 返回 `WARN` 表示存在局部 failures，但有效 catalog 可继续巡检。
