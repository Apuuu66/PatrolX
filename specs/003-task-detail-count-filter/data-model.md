# 数据模型：任务详情统计数字过滤

## 概述

本功能不引入新的持久化实体或后端数据模型变更。所有数据结构均为前端展示层的运行时状态。

## 前端运行时状态

### StatusFilter

用户当前选择的状态过滤条件。

| 属性 | 类型 | 说明 |
|------|------|------|
| value | `RuleStatus \| null` | 当前激活的规则状态；`null` 表示无过滤 |

**状态转换**：
- `null → "pass"/"warn"/"fail"/"error"/"skip"`：用户点击某个状态数量
- `"pass"/"warn"/"fail"/"error"/"skip" → null`：用户再次点击同一状态数量
- `"A" → "B"`：用户在激活状态 A 时点击状态 B（替换过滤）

### VisibleRuleResults

详情页可见的普通规则结果列表（已排除隐藏的内部准备规则）。

来源：`SystemInspection.rules` 过滤掉 `hidden` 为 `true` 的规则后的结果。

**用于推导**：
- 总览状态数量（按 `status` 字段分组计数）
- 过滤后的规则列表（按 `status` 字段筛选）
- 分类分组及分组标题数量（先按 `category` 分组，再按过滤条件筛选）

## 依赖的已有实体

### RuleResult

已有契约实体，本功能不修改其结构。关键字段：

| 字段 | 类型 | 用途 |
|------|------|------|
| code | `string` | 规则标识 |
| category | `RuleCategory` | 分类分组依据 |
| status | `RuleStatus` | 过滤依据 |

### RuleStatus

已有枚举类型：`"pass" | "warn" | "fail" | "error" | "skip"`。

### TaskStats

已有契约类型，本功能不修改。任务详情页总览状态数量不再直接使用此类型渲染，改为从 `VisibleRuleResults` 推导。
