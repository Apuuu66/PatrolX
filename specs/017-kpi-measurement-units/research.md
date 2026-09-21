# 研究结论

## Decision：资源目录使用三列 CSV
- **Decision**: 表头固定为 `资源id,中文描述,英文描述`，按前缀识别资源类型。
- **Rationale**: 与用户现状一致；不猜测指标与测量单元关系。
- **Alternatives considered**: 扩展列存绑定关系，已拒绝，因为任务 CSV 才能发现真实绑定。

## Decision：测量单元匹配大小写敏感
- **Decision**: 英文名空格转 `_`，不改变大小写；多个片段命中时取最长，否则歧义。
- **Rationale**: 用户明确不做大小写兼容，且可避免误归属。
- **Alternatives considered**: lower-case 匹配，已拒绝。

## Decision：表头锚点是周期列
- **Decision**: 扫描定位 `测量开始时间/测量结束时间/周期(分钟)`；周期列及其之前是元数据/维度，之后是指标列。
- **Rationale**: 不同 CSV 表头行号可能变化，锚点比固定行号更稳。
- **Alternatives considered**: 固定第三行，已拒绝。

## Decision：绑定关系单独存储
- **Decision**: `ME -> MU` 一对一绑定持久化；状态为 candidate/confirmed/conflict/ignored。
- **Rationale**: 资源 CSV 无绑定；不同资源 ID 是不同指标。
- **Alternatives considered**: 资源表内嵌 MU，已拒绝。

## Decision：行对象通用化
- **Decision**: 周期列之前的第一维度列作为行对象；无维度列用 `__all__`，按对象聚合统计。
- **Rationale**: 同时支持呼叫类和 CPU/内存类文件，不做容器特殊模型。
- **Alternatives considered**: CPU/Pod 专用解析，已拒绝。

## Decision：MVP 无阈值
- **Decision**: 默认期望 100% 可读；缺失、空值、解析错误判失败，全 0 是 pass + 形态提示。
- **Rationale**: 用户确认首版只保证可读性。
- **Alternatives considered**: 业务阈值配置，延后。

## Decision：旧 KPI 完全删除
- **Decision**: 删除旧规则、服务、配置、页面、测试和基础 JSON；不迁移旧任务。
- **Rationale**: 用户确认不兼容旧任务，避免双模型维护。
- **Alternatives considered**: feature flag 双轨，已拒绝。
