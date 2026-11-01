# 数据模型：KPI-only 规则库收缩

本次不新增表、字段或迁移。以下实体描述收缩后必须维持的不变量。

## 活动普通规则目录（Active Rule Catalog）

- **来源**：`RuleRegistry` 中 `hidden=False` 的已注册规则。
- **字段**：`code`、`name`、`category`、`priority`、`rule_version`、`source_patterns`、`enabled`。
- **不变量**：
  - 活动规则代码集合严格等于 `{"kpi.measurement_units"}`。
  - `category` 必须为 `RuleCategory.KPI`。
  - 唯一的 `source_refs` 为 `["kpi_all"]`，展开后包含 `^kpi/.*\.csv$` 与 `^traffic/.*\.csv$`。
  - `rule_version` 保持 `3.3.0`。
  - 目录接口、启停分页和普通规则统计只能从此集合派生。

## 隐藏解压基础设施（Hidden Extraction Rule）

- **来源**：`pkg.extract.main` 与 `pkg.extract.{logs,kpi,traffic,alarm,config,resource,other}`。
- **字段**：`code`、`hidden=True`、`priority=P0`、`rule_version`。
- **不变量**：
  - 作为 `EXTRACT` 阶段基础设施执行。
  - 不出现在默认 `/inspectors`、普通规则统计、启停管理或 `system.rules`。
  - 保持安全、幂等、分类落位和 manifest 行为。
  - 不属于被删除的业务规则范围。

## 任务执行计划（Task Execution Plan）

- **组成**：全部 hidden `pkg.extract.*` + 当前启用的活动普通规则。
- **不变量**：
  - 默认配置下普通 `INSPECT` 计划仅含 `kpi.measurement_units`。
  - KPI 被停用时只执行隐藏解压基础设施，不回退到已删除规则。
  - 包内非 KPI 数据仍被分类、解压和保留。
  - 单个输入缺失或不适配时 KPI 返回 `skip` 且包含 `skip_reason`。

## 规则结果（Rule Result，历史兼容）

- **来源**：SQLite `TaskRuleResult`、`output/<task_id>/rules/<code>.json`、`system.json` 摘要。
- **字段**：沿用现有 `RuleResult` 契约，包括 `code`、`name`、`category`、`priority`、`status`、`severity`、`metrics`、`findings`、`metadata`、`skip_reason` 等。
- **不变量**：
  - 新任务只写入 KPI 规则结果。
  - 历史非 KPI 结果字段、数量、内容保持可读且不被重写。
  - `RuleCategory` 全部历史值可反序列化。
  - 已删除规则的结果可按 `task_id + rule_code` 读取，但不能借此注册或执行规则。

## 规则启停状态（Rule State）

- **来源**：SQLite `RuleState`。
- **字段**：`rule_code`、`enabled`、`updated_at`。
- **不变量**：
  - 新初始化只创建活动 KPI 规则状态。
  - 旧的非 KPI 状态行保留但不显示、不进入执行计划、不可更新为活动状态。
  - 隐藏规则不可启停。
  - KPI 状态可由管理员切换，重复更新不刷新同值时间戳。

## 设备台账（Inventory Evidence）

- **来源**：包内基础配置与上传元数据（省份、运营商、网元类型、版本）。
- **不变量**：
  - 台账提取不依赖任何普通规则。
  - 上传网元类型与台账类型比较时沿用现有大小写归一/匹配语义。
  - 规则删除不改变台账表、归档文件或历史台账。

## 巡检包（Inspection Package）

- **不变量**：
  - 原始包内容与 SHA-256 在任务前后一致。
  - 所有 7 个分类目录仍可生成。
  - 非 KPI 数据不触发普通规则。
  - 不迁移、不清理、不提交真实上传包和真实历史数据。

## 状态转换

```text
上传/本地包
  → EXTRACT（hidden pkg.extract.*）
  → PREPARE（仅活动规则私有 prepare）
  → INSPECT（仅已启用活动普通规则）
  → 结果持久化 / 台账 / 报告
```

已删除规则不存在可执行状态转换；历史结果只支持读取，不支持启停、重跑或增量重建。
