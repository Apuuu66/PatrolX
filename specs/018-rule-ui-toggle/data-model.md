# 数据模型：界面规则启停

## RuleState

规则启停状态是运行时持久化状态，用于决定新任务执行哪些普通规则。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `rule_code` | string | 主键；非空；对应已注册普通规则 | 规则唯一代码 |
| `enabled` | boolean | 非空；默认 `true` | 当前是否参与后续新任务 |
| `updated_at` | UTC datetime | 非空；使用 `updated_at` 命名 | 最近一次状态变更时间 |

### 约束

- 只保存普通规则状态；隐藏内部前置规则不创建启停记录。
- `rule_code` 必须与注册表中的普通规则一一对应。
- 不保存变更操作人、历史版本、审批状态或定时启停配置。

### 状态转换

```text
不存在 --首次初始化--> enabled=disabled_rules 中不包含该规则
enabled=true  --界面停用--> enabled=false
enabled=false --界面启用--> enabled=true
enabled=true  --重复启用--> enabled=true，updated_at 不要求变化
enabled=false --重复停用--> enabled=false，updated_at 不要求变化
```

### 生命周期

- 系统首次初始化时，从既有 `disabled_rules` 导入普通规则的初始停用状态。
- API 状态列表、TaskService 初始化、CLI 新任务、单规则重跑和增量重建先触发同一个惰性初始化；初始化后，界面更新是状态的唯一修改入口。
- 初始化遇到配置格式非法或未知规则时抛出统一错误，阻止本次读取或执行。
- 规则代码在注册表中消失时，对应状态记录不再参与执行；当前版本不提供自动清理契约。

## InspectorState 契约

分页规则状态列表返回普通规则定义的运行时视图，不修改既有 `InspectorInfo`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | string | 普通规则代码 |
| `name` | string | 规则名称 |
| `category` | string | 规则分类 |
| `priority` | integer | 规则优先级 |
| `enabled` | boolean | 当前启停状态 |
| `updated_at` | UTC datetime | 最近一次状态变更时间 |

列表响应使用 `items/total/page/page_size`，默认 `page=1`、`page_size=10`。

## 任务规则集合

任务开始时生成的临时逻辑集合，不作为持久化任务契约新增字段。

- 包含全部隐藏解压规则。
- 包含 `enabled=true` 的普通规则及其私有 prepare。
- 排除 `enabled=false` 的普通规则及其私有 prepare。
- 执行期间不重新读取启停状态。
