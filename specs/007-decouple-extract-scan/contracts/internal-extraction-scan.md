# 内部边界契约：解压与规则扫描

日期：2026-09-14  
状态：草案，供 tasks 与实现遵循  
范围：仅内部 Python 模块边界；不是 OpenAPI 或前端契约。

## 1. 目标

固化 `EXTRACT`、任务文件扫描、`RuleContext`、规则私有 prepare 和普通规则执行之间的最小接口，防止职责再次混合。该契约不新增公共 API 字段。

## 2. 模块与所有权

| 模块 | 负责内容 | 禁止内容 |
| --- | --- | --- |
| `app/services/extraction/budget.py` | 任务级累计预算、递归深度协同 | 目录落位、manifest、规则感知 |
| `app/services/extraction/layout.py` | category 目录、目标相对路径、路径安全 | 递归解压、规则扫描 |
| `app/services/extraction/manifest.py` | v3 读取/写入/校验/复用 | 解压文件、分类决策 |
| `app/services/extraction/nested.py` | 子包和 `.log.gz` 有界递归展开 | 规则执行、prepared 数据 |
| `app/services/extraction/site.py` | 主包 staging、`.main/`、分类现场编排 | 直接读取规则 `source_patterns` |
| `app/services/scanning/catalog.py` | 最终文件白名单清单构建 | 解压、修改文件、持久化清单 |
| `app/services/scanning/matcher.py` | pattern 防御校验与 `re.fullmatch` | 文件系统遍历 |
| `app/services/prepare.py` | owner prepared 目录与缓存 marker | 通用扫描、通用解压、跨规则数据 |
| `app/services/executor.py` | 阶段屏障、catalog 注入、结果契约校验 | 业务规则分支 |

## 3. 稳定入口

### 3.1 Extraction facade

`app.services.extraction.__init__` 继续导出现有调用方需要的核心名称：

```python
extract_main_site(
    package: Path,
    data_dir: Path,
    checksum: str,
    log: ExtractionLogger | None = None,
) -> dict

category_failures(manifest: dict, category: str) -> list[dict]

manifest_path(data_dir: Path) -> Path
read_manifest(data_dir: Path) -> dict
write_manifest(data_dir: Path, manifest: dict) -> None
reusable_manifest(data_dir: Path, checksum: str) -> dict | None
```

也保留常量：

```python
MANIFEST_NAME = ".patrolx-extracted.json"
MAIN_EVIDENCE_DIR = ".main"
MANIFEST_VERSION = 3
CATEGORY_DIRECTORIES
WORK_CATEGORIES
```

`ExtractionLogger`、`ExtractionBudget` 继续由对应子模块 re-export。

### 3.2 Scanning 契约

```python
@dataclass(frozen=True)
class TaskFileCatalog:
    @classmethod
    def build(cls, data_dir: Path) -> "TaskFileCatalog": ...

    def paths(self) -> list[Path]: ...
    def match(self, source_patterns: list[str]) -> list[Path]: ...
    def resolve(self, relative: Path) -> Path: ...
```

简化签名如上；实现可使用内部字段或属性，但必须保持这三个只读操作语义。

### 3.3 Prepare 契约

```python
prepared_dir(ctx: PrepareContext, owner_code: str) -> Path
marker_path(ctx: PrepareContext, owner_code: str) -> Path
rule_python_path(rule: Inspector) -> Path
rule_file_sha256(rule: Inspector) -> str
```

`match_relative_files()` 从 prepare 模块移除；不允许为兼容而继续提供通用扫描 helper。

## 4. 阶段序列

### 4.1 全量执行

```text
1. Executor.extract_plan()
   - pkg.extract.main 最先
   - 其余 pkg.extract.* 按 code 排序

2. Executor.run_one("pkg.extract.main")
   - extraction.site.extract_main_site()

3. 主包 result.status == error
   - 阻断 PREPARE 与 INSPECT

4. 其余 pkg.extract.* 汇总 manifest 分类终态

5. Executor.ensure_catalog(ctx)
   - TaskFileCatalog.build(ctx.data_dir)
   - 一次构建，注入 ctx

6. PREPARE
   - registry.prepares() 排序
   - 对每个 owner 使用 catalog.match(owner.source_patterns)
   - 有匹配则执行/复用；无匹配 SKIP；失败 FAILED

7. INSPECT
   - registry.all() 中的非隐藏规则按 priority/code 执行
   - Executor 使用 catalog.match(rule.source_patterns) 注入 ctx.files
```

### 4.2 单规则重跑

```text
1. manifest 缺失、无效或 checksum 不一致时执行主包解压
2. ensure_catalog(ctx)
3. 若目标规则声明 prepare：执行或复用该 owner 私有 prepare
4. 执行目标 inspect
5. 不执行、不重算、不覆盖无关普通规则结果
```

## 5. 输入输出契约

### EXTRACT

- 输入：原始上传包路径、任务数据目录、主包 SHA-256、结构化日志回调。
- 输出：manifest dict；同时产出 `.main/` 和 category 工作现场。
- 失败：主包解压失败抛出 `ArchiveError` 并由隐藏规则包装为 `error`；局部失败写入 manifest 后继续。

### Catalog

- 输入：任务数据目录。
- 输出：只读相对路径集合和匹配结果。
- 不修改文件系统；不记录执行时间戳；不持久化。
- 只扫描 `WORK_CATEGORIES` 对应的七个根目录。
- 构建失败异常必须包含路径和原因。

### Matcher

- 输入：catalog 与 `source_patterns[]`。
- 输出：稳定排序的相对 `Path` 列表。
- 语义：对 catalog 中每个 POSIX 相对路径执行 `re.fullmatch()`。
- 错误：非法正则、绝对路径、路径穿越、越界匹配或链接路径立即抛出 `ValueError`。

### Prepare

- 输入：owner 规则、`PrepareSpec`、注入了 `ctx.files` 的 `RuleContext`。
- 输出：owner 目录内的中间数据与 marker。
- 状态：`SKIP`、`HIT`、`REBUILT`、`FAILED`。
- 约束：只写 `prepared/<owner_code>/`；不修改任务文件；不输出普通 `RuleResult`。

### Inspect

- 输入：owner `Inspector`、注入 `ctx.files` 的 `RuleContext`。
- 输出：公共 `RuleResult`。
- 无匹配且无有效 prepared 输出时返回 `skip`。
- 单规则异常返回 `error`，不中断其他规则。

## 6. 依赖规则

- `app/services/extraction` 不导入 `app/services/scanning`。
- `app/services/scanning` 不导入 `app/services/prepare`。
- `app/services/prepare` 不导入 `app/services/scanning`。
- `app/inspectors/*` 不互相导入业务实现，只通过 `RuleContext` 消费注入数据。
- 普通规则不得导入其他普通规则或 prepare 实现。
- `Executor` 可以导入 extraction、scanning 和 prepare，但不硬编码业务规则。

## 7. 错误与日志契约

日志使用结构化字段；内部契约要求至少保留：

| 场景 | 必要字段 |
| --- | --- |
| 主包开始/完成/失败 | `task_id`、`package`、`checksum`、`error`（失败时） |
| 子包状态 | `task_id`、`source`、`target`、`category`、`depth`、`checksum`、`status`、`error` |
| `.log.gz` 状态 | `task_id`、`source_relative_path`、`target`、`depth`、`status`、`error` |
| catalog 异常 | `task_id`、`path`、`error` |
| pattern 拒绝 | `task_id`、`rule_code`、`pattern`、`error` |
| prepare 状态 | `task_id`、`rule_code`、`prepare_code`、`prepare_state` |
| inspect 无匹配 | `task_id`、`rule_code`、`source_patterns` |

## 8. 兼容承诺

- 不改变 OpenAPI、公共 Pydantic 字段、状态枚举和前端 API。
- 不改变一个包/一个任务/一个输出目录。
- 不改变 `pkg.extract.*` 隐藏规则身份和 `EXTRACT → PREPARE → INSPECT` 顺序。
- 不把 prepare 暴露为普通规则结果。
- 行为优化只能表现为性能、日志或内部状态变化；公共结果语义变化必须回到规格评审。
