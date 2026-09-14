# 阶段 1 数据模型：解压与规则扫描解耦

日期：2026-09-14  
状态：已完成  
规格：[spec.md](spec.md)

## 模型总览

```text
UploadPackage
  1 ─ 1 ExtractionManifest（持久化）
  1 ─ 1 TaskWorkSite（持久化目录状态）
  1 ─ 1 TaskFileCatalog（执行期内存）
  1 ─ N MatchedFileSet（执行期内存）
  0/1 per owner ─ 1 PrepareState（执行期状态）
  0/1 per owner ─ 1 PreparedSite（持久化 owner 私有文件）
```

`TaskFileCatalog` 不持久化，也不是 API 契约的一部分。

## 1. 上传包与任务工作现场

### UploadPackage

- 路径：`uploads/<task_id>/<package_file>`。
- 不修改内容；每次解压前按文件计算 SHA-256。
- 一个上传包对应一个 `task_id` 和一个输出目录。

### TaskWorkSite

根目录：`output/<task_id>/`。

```text
output/<task_id>/
├── .main/                        # 主包原始解压证据现场
├── logs/                         # 最终日志工作现场
├── kpi/                          # 最终 KPI 工作现场
├── traffic/
├── alarm/
├── config/
├── resource/
├── other/
├── prepared/<owner_code>/        # owner 私有 prepared 数据
├── rules/<rule_code>.json
├── task.json
├── system.json
├── report.html
├── execution.log
└── .patrolx-extracted.json       # ExtractionManifest v3
```

不变量：

- `.main/` 只作为证据现场，不进入普通规则匹配。
- 七个 category 根目录是 catalog 的唯一扫描来源。
- `prepared/` 只能由 owner 私有 prepare 写入，不能被其他规则作为普通源文件读取。
- 原始上传包不参与 catalog 扫描。

## 2. ExtractionManifest v3

文件：`.patrolx-extracted.json`  
编码：UTF-8 JSON  
用途：记录解压事实、来源关系、幂等复用和局部失败。

### 顶层结构

```json
{
  "version": 3,
  "main": {
    "checksum": "string",
    "count": 0,
    "evidence_path": ".main",
    "reused": false
  },
  "subpackages": [],
  "log_gz": [],
  "rejected": []
}
```

### main

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `checksum` | string | 原始主包 SHA-256。 |
| `count` | int | `.main/` 中登记的文件数，非负整数。 |
| `evidence_path` | string | 固定为 `.main`。 |
| `reused` | bool | 本次结果是否来自复用检查后的既有现场。 |

### subpackages[]

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `source` | string | 证据现场或父工作现场中的子包来源路径。 |
| `parent` | string \| null | 父子包工作目录名；主包直连成员为 null。 |
| `category` | string | 分类工作根：`logs`/`kpi`/`traffic`/`alarm`/`config`/`resource`/`other`。 |
| `classification_reason` | string | `self:name`、`self:content`、`parent:category` 或 `fallback:other`。 |
| `depth` | int | 递归深度。 |
| `checksum` | string | 子包 SHA-256。 |
| `target` | string \| null | 成功时为分类工作现场目标相对路径。 |
| `status` | enum | `extracted`、`duplicate`、`failed`、`rejected`。 |
| `error` | string \| null | 非 extracted 时提供原因。 |

### log_gz[]

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `source_evidence` | string | 主证据现场中的原始 `.log.gz` 路径或等价证据标识。 |
| `source_relative_path` | string | 展开时的原始相对路径。 |
| `target` | string | 目标 `.log` 相对路径。 |
| `depth` | int | 递归深度。 |
| `status` | enum | `extracted`、`conflict`、`failed`、`rejected`。 |
| `error` | string \| null | 非 extracted 时提供原因。 |

### rejected[]

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `source` | string | 被拒绝文件的来源相对路径。 |
| `category` | string | 尝试分类。 |
| `reason` | string | 冲突、路径安全、预算或格式不适用等原因。 |
| `depth` | int | 递归深度。 |

### 状态与复用

- manifest 有效、`main.checksum` 与当前上传包一致、`.main/` 存在时复用。
- 损坏、版本不匹配、checksum 不一致或证据目录缺失时整体重建。
- 重建使用 `.main.staging/`，替换失败时恢复 `.main.previous/`。
- manifest 写入在解压与落位终态后执行。

## 3. TaskFileCatalog（执行期内存）

### 对象字段

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `root` | `Path` | 已解析的任务输出根目录。 |
| `_paths` | `tuple[Path, ...]` | 最终可巡检文件的相对路径，按 POSIX 字典序排序。 |

### 构建来源

只遍历存在的 category 根：

```text
logs/
kpi/
traffic/
alarm/
config/
resource/
other/
```

### 包含规则

1. 只包含常规文件。
2. 相对路径使用 `/` 表示层级。
3. 按 `path.as_posix()` 去重后升序排序。
4. 路径必须仍在 `root` 内。
5. 遇到符号链接或越界路径立即抛出带原因的校验异常。

### 排除规则

由于只扫描 category 白名单，以下内容天然排除：

- `.main/**`
- `.patrolx-extracted.json`
- `prepared/**`
- `rules/**`
- `task.json`
- `system.json`
- `report.html`
- `execution.log`

### 访问契约

| 方法 | 语义 |
| --- | --- |
| `build(data_dir: Path) -> TaskFileCatalog` | 解压终态后构建一次。 |
| `paths() -> list[Path]` | 返回稳定排序的相对路径副本。 |
| `match(source_patterns: list[str]) -> list[Path]` | 对 `paths()` 做防御校验和 `re.fullmatch()`，返回稳定排序匹配集。 |
| `resolve(relative: Path) -> Path` | 将相对路径解析到任务根内；拒绝越界。 |

## 4. RuleDeclaration 与 source_patterns

### RuleDeclaration

公共规则对象仍由 `Inspector` 表示，关键字段：

| 字段 | 语义 |
| --- | --- |
| `code` | 全局唯一规则代码。 |
| `category` | 业务分类，映射解压落位。 |
| `priority` | `P0` 隐藏基础规则、`P1` 基础检查、`P2` 综合分析。 |
| `hidden` | `pkg.extract.*` 为 true，prepare 不是规则。 |
| `source_patterns[]` | Python regex 列表，唯一声明普通源文件范围。 |
| `prepare` | 至多一个 owner 私有 prepare。 |

### source_patterns 不变量

- 使用 `re.fullmatch(pattern, posix_relative)`。
- 相对路径以 `/` 分隔，不以 `/` 开头。
- 禁止空值、首尾空白、绝对路径、路径穿越、`~` 展开和非法正则。
- 多个模式取并集；一个文件命中多个模式只出现一次。
- 匹配结果不是通过 `rglob()` 二次过滤得到，而是 catalog 内列表的声明式匹配结果。

## 5. MatchedFileSet

- 类型：有序 `list[Path]`。
- 内容：相对 `output/<task_id>/` 的最终文件路径。
- 排序：`path.as_posix()` 字典序。
- 写入位置：`RuleContext.files`。
- 解析：`RuleContext.resolved_files()` 只允许映射到任务根内文件。
- 普通规则和 owner prepare 对同一 owner 的匹配集合必须一致；prepare 缓存命中时也必须重新获得 catalog 匹配结果，不能沿用上一次执行的可变状态。

## 6. PrepareState 与 PreparedSite

### PrepareState

`PrepareState` 是执行日志和 `RuleContext.prepare_states` 中的内部状态，不是公共规则结果。

| 状态 | 语义 |
| --- | --- |
| `SKIP` | owner `source_patterns[]` 无匹配源文件。 |
| `HIT` | marker 中 SHA-256 等于当前 owner 规则文件 SHA-256，复用 prepared 数据。 |
| `REBUILT` | 清空并重建 owner prepared 目录后成功。 |
| `FAILED` | prepare 异常，owner inspect 返回 `skip`。 |

### PreparedSite

路径：`output/<task_id>/prepared/<owner_code>/`

| 文件/目录 | 语义 |
| --- | --- |
| 业务中间文件 | owner prepare 生成的数据，其他普通规则不得读取。 |
| `.prepare.sha256` | owner 规则 Python 文件 SHA-256。 |

不变量：

- `owner_code` 必须是单段文件系统安全名称，不得是 `.`、`..` 或包含路径分隔。
- prepare 缓存只校验 owner 规则文件内容，不使用手动刷新命令。
- prepare 失败或未就绪不会写入其他规则可见的普通源文件。
- prepare 不执行通用解压。

## 7. 公共输出契约视图

本功能不新增公共实体，不改变以下契约字段语义：

- `InspectionTask`
- `SystemInspection`
- `TaskSummary`
- `RuleResult`
- `Metric`
- `Finding`
- `LogEntry`
- 状态枚举：`pass`、`warn`、`fail`、`error`、`skip`

`TaskFileCatalog`、`MatchedFileSet`、`PrepareState` 和 manifest 内部状态只允许出现在执行日志或测试断言中，不新增 API 响应字段。
