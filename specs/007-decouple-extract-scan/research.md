# 阶段 0 研究：解压与规则扫描解耦

日期：2026-09-14  
状态：已完成  
规格：[spec.md](spec.md)

## 结论摘要

采用“统一解压入口 + 内存任务文件清单 + 单一模式匹配器 + owner 私有 prepare”的方案。大主包、小主包、嵌套子包和 `.log.gz` 全部在 `EXTRACT` 内完成安全展开；解压完成后构建一次最终可巡检文件清单；普通规则和私有 prepare 通过同一清单做 `re.fullmatch()` 匹配。该方案不改变公共 API，并把现有混合职责拆成单向依赖模块。

## 已确认输入

- 规格共有 8 项澄清：允许行为优化但公共契约兼容；必须重排内部文件位置；采用统一内存清单；注册时拒绝非法/不安全 `source_patterns[]`；清单不持久化；匹配结果按 `/` 归一化稳定排序；清单只含最终可巡检文件；统一 `EXTRACT` 入口有界递归展开。
- 用户已确认的直觉：大主包和单个日志/KPI 小包最先进入统一解压；然后按 category 分类落位；prepare 只负责选择、解析和格式化已经解压好的文件。
- 现状痛点集中在 `app/services/extraction.py` 与 `app/services/prepare.py`：前者混合 manifest、预算、递归、落位和主包编排；后者混合 prepared 缓存与通用文件扫描。

## 决策记录

### D1. 统一 EXTRACT 入口，大小包不分支

**决策**：所有上传包都进入 `extract_main_site()`，先形成 `.main/` 证据现场，再分类落位和递归展开。

**理由**：小分类包只是成员分布不同的主包；单独入口会复制安全、manifest、预算和幂等逻辑。统一入口也让 `pkg.extract.*` 隐藏规则继续以同一状态模型汇总。

**被拒绝方案**：为“大主包”和“小主包”分别设计服务。  
**拒绝原因**：分类边界不稳定，容易导致同一嵌套结构在两种入口下产生不同 manifest 和路径。

### D2. 递归解压保留在 EXTRACT

**决策**：子包和 `.log.gz` 在 `EXTRACT` 内有界递归展开；prepare 只处理已经展开的最终文件。

**理由**：`EXTRACT → PREPARE → INSPECT` 是固定屏障。如果 prepare 展开通用压缩包，会重新引入隐藏阶段、跨规则时序依赖和重复解压，也让安全预算难以集中。

**边界**：`.log.gz` 属于通用展开，不是 owner prepare 的业务格式化；prepare 可以解析 `.log`/`.csv` 并生成 owner 私有中间文件，但不能解压新的压缩包。

### D3. 使用不持久化的 TaskFileCatalog

**决策**：解压完成后为本次执行或单规则重跑构建一次内存 `TaskFileCatalog`。

**理由**：清单能保证普通规则和 prepare 使用唯一文件来源；避免每条规则重复 `rglob()`；也能在不新增输出产物的情况下排除任务现场文件。

**被拒绝方案**：
1. 持久化清单 JSON：增加输出契约、清理时机和单规则重跑一致性负担。
2. 每规则直接扫描：保留重复遍历，且每个调用点都要重复排除规则。
3. 只把解压 manifest 当作清单：manifest 包含证据、失败、重复和来源状态，不代表最终可巡检文件集合。

### D4. catalog 使用 category 白名单

**决策**：catalog 只扫描 `logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other` 七个分类根。

**理由**：输出任务根目录同时存在 `task.json`、`system.json`、`rules/`、`prepared/`、报告和执行日志。黑名单容易漏排；分类根由解压落位统一定义，白名单最可靠。

**结果**：`.main/`、`.patrolx-extracted.json`、`prepared/`、任务元数据、规则结果、报告和执行日志不进入清单。

### D5. 扫描器只依赖窄布局契约

**决策**：`app/services/scanning/catalog.py` 只导入解压服务中的布局常量模块，不依赖主包编排、manifest 写入或递归展开。

**理由**：扫描需要知道“哪些根是最终工作现场”，但不应理解解压过程。布局常量集中后，分类目录变化不会迫使普通规则修改。

**依赖方向**：

```text
executor → extraction.site / scanning.catalog
prepare ← executor（注入 catalog 匹配结果；prepare 不 import scanning）
extraction.nested / scanning.catalog → extraction.layout
inspectors → executor 注入的 RuleContext
```

### D6. 非法 pattern 在注册时拒绝，扫描时保留防御

**决策**：`Inspector.validate()` 继续拒绝空值、首尾空白、绝对路径、`..`、`~` 和非法正则；`matcher.py` 再次防御并拒绝越界路径。

**理由**：注册失败能让开发期立即暴露坏规则；运行时防御能防止动态测试、历史对象或未来注册路径绕过校验。

**结果**：catalog 匹配时对每个模式调用 `re.fullmatch()`；所有普通规则得到的集合必须等于同一 catalog 的声明式匹配结果。

### D7. prepare 不再拥有通用扫描函数

**决策**：删除 `prepare.match_relative_files()`；`prepare.py` 只保留 owner 私有目录、marker、规则文件 SHA-256。

**理由**：通用扫描属于 scanning 服务；留在 prepare 会让规则误以为可以自行扫描任务目录，破坏“清单是唯一来源”的约束。

**迁移**：更新 executor、测试和样例工具调用；不保留混合 helper。`app.services.extraction` facade 继续保留，避免一次性破坏解压隐藏规则的既有调用。

### D8. manifest v3 仍是幂等边界

**决策**：保留 manifest v3，不升级版本；catalog 不写入 manifest。

**理由**：v3 已记录主包 checksum、子包状态、`.log.gz` 状态和 rejected 信息，足够支撑安全复用和失败追踪。catalog 是执行期派生视图，不属于持久化事实。

**策略**：manifest 结构有效、主包 checksum 一致且 `.main/` 存在时复用；否则删除 staging、重建 `.main/` 和分类现场。

### D9. 安全预算集中且固定

**决策**：继续使用固定预算和底层限制：任务累计最多 200,000 个文件、2GB 解压总量、最大递归深度 8；底层 zip/tar 同时使用 `UnpackLimit` 防单包炸弹。

**理由**：解压安全和规则扫描无关，必须由 extraction 统一计费。固定值可避免安全包叠加耗尽资源，也符合宪法“默认轻量”的要求。

**防护保留**：
- 目标路径 `resolve()` 后必须仍在任务根内。
- 目标自身或父级出现符号链接立即拒绝。
- 不展开链接成员。
- checksum 相同的子包只展开一次。
- staging 建好后原子 rename；主包替换失败时恢复 `.main.previous/`。

### D10. 失败按层级隔离

**决策**：主包失败阻断任务；子包、`.log.gz`、普通文件冲突、单文件解析、prepare 失败在安全时留痕并隔离。

**理由**：主包现场是所有分类结果的来源，继续执行会产生不可信的空结果；局部失败通常只影响部分规则，任务仍可产出有价值的发现。

### D11. 兼容优先于重命名公共行为

**决策**：不修改 OpenAPI、公共 Pydantic 模型和结果字段含义；模块位置可以重排，内部函数接口以 facade 和新 scanning 契约为准。

**理由**：该功能目标是不兼容输出的内部重构；行为优化应通过测试显式说明，不能表现为 CLI 与 API 差异。

## 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| catalog 误含 `prepared/` 或任务产物 | 规则读取私有/非源数据 | 只扫描七个 category 根；测试构造这些产物并断言不可匹配 |
| 旧任务目录缺少部分 category 目录 | 清单为空导致规则 skip | catalog 对缺失 category 容忍为空；单规则重跑先确保 manifest 可复用或重建 |
| pattern 正则误匹配 `.main/` 或 manifest | 规则读到证据/中间状态 | catalog 列表先排除，再做 fullmatch；不是只依赖 pattern |
| regex 命中目录符号链接 | 越界读取 | 遍历不跟踪链接；文件或路径为链接时拒绝 |
| 拆模块造成 import 循环 | 运行时失败 | 强制单向依赖；`extraction/__init__` 只 re-export，不 import scanning；prepare 不 import scanning |
| 单规则重跑使用旧解压现场 | 匹配结果与规则代码不匹配 | 检查 manifest checksum 和结构；失败则重建，再建 catalog |
| 行为变化未声明 | 契约兼容性破坏 | 以现有 baseline 测试为基线；只允许测试中显式记录的执行期优化 |

## 需要补充的验证

1. `TaskFileCatalog` 排序、白名单、排除物、符号链接和穿越拒绝。
2. `source_patterns` 完整匹配：目录、嵌套文件、多模式去重、无匹配 skip。
3. 主包幂等复用与 checksum/manifest 损坏重建。
4. 大主包包含日志子包、KPI 子包和 `.log.gz` 的有界递归展开。
5. 小主包只包含单一类别文件时与全量大包共享同一路径模型。
6. prepare 只收到 owner 匹配文件，缓存 marker 失效后只重建 owner 数据。
7. 单规则重跑不改变无关规则结果。
8. CLI/API 使用同一 catalog 与匹配路径，结果语义一致。
