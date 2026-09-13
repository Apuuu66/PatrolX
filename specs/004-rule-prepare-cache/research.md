# 研究记录：规则私有预处理与轻量缓存

## 1. 规则模型：source_patterns 还是公共 artifacts/inputs

**Decision**：普通巡检规则继续使用 `source_patterns` 作为源数据匹配模型。本特性不引入公共 `artifacts/inputs`；prepare 只继承 owner 规则的 source patterns，并把结果写入规则私有目录。

**Rationale**：`source_patterns` 能保持“规则只处理自己的数据”的边界；规则私有 prepared 数据能减少重复解析。公共 artifact 模型容易演化为规则间依赖。

**Alternatives considered**：

- 公共 `inputs[]` / `artifacts`：表达力强，但会形成公共依赖面，违反已确认的轻量隔离方向。
- 按大类共享 prepared 目录：日志/KPI 多条规则复用，但会重新产生隐式耦合，后续很难判断哪条规则消费了哪些数据。

## 2. 阶段编排方式

**Decision**：使用固定阶段屏障 `EXTRACT → PREPARE → INSPECT`，不建立普通规则依赖图。prepare 由 owner 规则声明，内部按 `owner priority → owner code → prepare code` 排序；inspect 按 `priority → code` 排序。

**Rationale**：阶段屏障语义简单、结果确定，能保证 prepare 的输出在所有 inspect 前就绪。

**Alternatives considered**：

- 继续使用优先级和拓扑排序把 prepare 混入普通规则：实现复杂，prepare 会暴露为普通规则节点。
- 每条 inspect 执行前懒加载 prepare：单规则重跑简单，但全量阶段顺序不确定，也难以表达“prepare 全部完成”。

## 3. prepare 是否并发

**Decision**：第一版顺序执行。prepare 之间保持逻辑独立，后续可以在不改变契约的情况下引入 bounded concurrency。

**Rationale**：当前 Constitution 优先单节点顺序执行；顺序实现更易定位失败，也更符合轻量默认。两条样例规则不会成为主要性能瓶颈。

**Alternatives considered**：

- 第一版直接引入线程/进程并发：性能可能更好，但会增加失败隔离、日志上下文和文件写入边界复杂度。

## 4. 缓存刷新依据

**Decision**：使用当前规则代码文件内容的 md5 作为 marker。marker 不存在或不一致时重建；一致时复用。重建前清空 owner prepared 目录；成功后写入新 marker；失败不写入 marker。

**Rationale**：开发过程中频繁改代码但未必升版本，内容 md5 能自动感知变化；不依赖命令、开关或人工版本维护。用户已确认接受“只看当前规则文件”的取舍。

**Alternatives considered**：

- 只看 mtime：容易被复制、checkout 或工具触碰误触发，也可能漏判内容不变场景。
- 输入文件 checksum：需要扫描大文件，成本可能接近预处理本身。
- prepared 输出 checksum / manifest：更严谨但明显过重。
- 自动 import 分析：能覆盖 helper 文件，但复杂且脆弱。
- 显式刷新开关：增加命令选择和人工记忆成本，不符合开发体验要求。

**已知限制**：只校验当前规则 Python 文件。被 prepare 引用的共享 helper 文件变化不会触发重建。该限制由用户明确接受。

## 5. prepared 输出声明

**Decision**：第一版不声明 outputs。prepare 可以自行写文件，owner prepared 目录和成功 marker 是缓存边界；不检查具体输出文件是否存在。

**Rationale**：输出声明会让规则开发变重，也不能解决 helper 变化、输入语义变化等所有问题。用户已选择轻量开发体验优先。

**Alternatives considered**：

- 声明 `cache_files[]` 并检查存在性：可发现部分删除，但增加声明维护成本，且用户已明确拒绝。
- 记录输出 hash：更可靠但成本高，不符合轻量目标。

## 6. 目录模型

**Decision**：不迁移既有解压分类目录。当前实现已经是 `output/<task_id>/logs/`、`kpi/` 等任务级目录；本特性只新增：

```text
output/<task_id>/prepared/<owner_code>/
```

**Rationale**：额外引入 `data/` 或目录迁移会扩大本功能范围，并与现有 `source_patterns`、解压清单和测试路径冲突。`system_id` 不是运行时目录身份，prepare 只需要保持任务和 owner 双重隔离。

**Alternatives considered**：

- 将解压数据统一迁到 `data/`：会要求同步修改解压、source patterns、样例和报告，收益与 prepare 目标无关。
- 按日志/KPI 大类共享 prepared：会形成隐式跨规则耦合，违反规则隔离。

## 7. 失败与 skip 语义

**Decision**：

- 主包解压失败：任务失败，不进入 prepare/inspect。
- prepare 执行异常：owner inspect 框架直接 `skip`，不调用 owner 逻辑。
- prepare 无匹配输入：prepare 和 owner inspect 显式 `skip`。
- 其他规则不因单个 prepare 失败而中断。

**Rationale**：避免 prepared 失败后 owner 读取旧数据或原始数据产生误导性结论。与现有任务容错要求一致。

**Alternatives considered**：

- owner 回退读原始文件：实现简单，但会失去 prepare 的性能收益，并放大失败差异。
- owner 返回 error：语义更严重，但“预处理未就绪”更适合用 `skip` 表达。

## 8. 首批迁移范围

**Decision**：第一版迁移 `log.app_service` 和 `kpi.threshold`。

**Rationale**：覆盖日志大文件解析和 KPI 结构化文件解析两类典型场景，又不要求一次性迁移所有规则。

**Alternatives considered**：

- 只迁移 KPI：实现最小，但无法验证日志场景。
- 一次迁移所有日志规则：风险大，测试和样例数据要求高，不符合第一版范围。
