# API 契约：界面规则启停

本功能在 `/api/v2` 上新增专用契约；既有 `GET /api/v2/inspectors` 保持兼容，不在本功能中修改。

## GET /api/v2/inspector-states

分页查询普通规则启停状态。只返回普通规则；隐藏内部规则不进入列表。

### 查询参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | integer | 否 | `1` | 页码，最小 1 |
| `page_size` | integer | 否 | `10` | 每页条数，1–100 |
| `category` | string | 否 | - | 按规则分类过滤 |
| `enabled` | boolean | 否 | - | 按启停状态过滤 |
| `search` | string | 否 | - | 按规则代码或名称模糊匹配 |

### 响应

返回 `InspectorStateListResponse`：

```json
{
  "items": [
    {
      "code": "log.ccc_service",
      "name": "CCC 服务日志检查",
      "category": "log",
      "priority": 2,
      "enabled": true,
      "updated_at": "2026-09-22T00:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

## PUT /api/v2/inspector-states/{rule_code}/enabled

更新一条普通规则的启停状态。

### 请求

```json
{
  "enabled": false
}
```

### 状态码

| 状态码 | 场景 |
| --- | --- |
| 200 | 更新成功，返回最新 `InspectorInfo` |
| 422 | 请求体不是 strict boolean |
| 403 | 当前用户无管理员权限 |
| 404 | 规则不存在 |
| 409 | 规则存在但不可启停 |

### 错误

错误沿用 `{code, message, detail}` 契约。

## 行为约定

- 更新成功后，后续新任务立即使用新状态。
- 对不存在规则返回 `not_found`。
- 对隐藏内部规则返回 `rule_not_manageable`。
- 对已注册普通规则的重复同值更新，返回成功且不要求改变 `updated_at`。
