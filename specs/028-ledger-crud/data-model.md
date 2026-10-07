# 阶段 1 数据模型：网元类型筛选与设备台账维护

## `LST ME.txt` 解析证据

任务证据 `inventory.json` 从单设备语义升级为记录级语义；`parser_version=3` 起只保留所选网元类型的记录明细，其它类型仅计入 `unmatched_count`。

### 核心字段

```json
{
  "schema_version": 2,
  "parser_version": "3",
  "network_element_type_filter": {
    "requested": "UMF2020",
    "normalized": "UMF2020",
    "status": "ok",
    "matched_count": 2,
    "unmatched_count": 1
  },
  "records": [
    {
      "raw_name": "NJ-AGG-001",
      "normalized_name": "NJ-AGG-001",
      "raw_network_element_type": "UMF2020",
      "normalized_network_element_type": "UMF2020",
      "raw_version": "V900R016C10SPC200",
      "matched": true,
      "source_file": "config/LST ME.txt",
      "name_source_lines": [7],
      "type_source_lines": [8],
      "version_source_lines": [9]
    }
  ],
  "devices": [
    {
      "status": "ok",
      "raw_name": "NJ-AGG-001",
      "normalized_name": "NJ-AGG-001",
      "network_element_type": "UMF2020",
      "version": {
        "status": "ok",
        "raw_version": "V900R016C10SPC200"
      },
      "source_file": "config/LST ME.txt"
    },
    {
      "status": "ok",
      "raw_name": "NJ-AGG-002",
      "normalized_name": "NJ-AGG-002",
      "network_element_type": "UMF2020",
      "version": {
        "status": "ok",
        "raw_version": "V900R016C10SPC201"
      },
      "source_file": "config/LST ME.txt"
    }
  ],
  "archived": {
    "archived": true,
    "device_id": null,
    "observation_id": null,
    "reason": null,
    "devices": [
      {
        "device_id": "device-id-1",
        "observation_id": "observation-id-1",
        "normalized_name": "NJ-AGG-001",
        "network_element_type": "UMF2020"
      },
      {
        "device_id": "device-id-2",
        "observation_id": "observation-id-2",
        "normalized_name": "NJ-AGG-002",
        "network_element_type": "UMF2020"
      }
    ]
  }
}
```

### 状态与原因

| 场景 | 结果 |
| --- | --- |
| 上传 `product` 缺失 | `not_archived`，`network_element_type_filter_missing` |
| 所有记录网元类型缺失 | `not_archived`，`network_element_type_missing` |
| 没有记录与上传 `product` 相等 | `not_archived`，`network_element_type_no_match` |
| 存在匹配记录 | 逐台去重归档；`devices` 至少包含一条匹配记录 |
| 同名匹配记录版本一致 | 合并为一台设备并只写一条台账观测 |
| 同名匹配记录版本不同 | 版本冲突；该设备不归档 |
| 记录缺设备名、缺版本或解析异常 | 不中断其他记录；结构化写入 `errors` |
| 日志补充包 | 继续整体 `not_applicable`，不解析设备记录 |

### 旧字段兼容

- 既有 `site` 字段含义不变，来源于上传省份和运营商。
- 既有 `device` / `version` 字段继续返回：
  - 一个匹配设备时与该设备一致。
  - 多个匹配设备时 `device.status=matched_multiple`，`normalized_name=null`，版本不做单一聚合。
- 前端任务详情优先读取 `devices`；旧任务继续读取旧字段。
- 既有 `archived.device_id` / `archived.observation_id` 只在单设备归档时填充；多设备归档时为 `null`，并使用新增 `archived.devices[]` 表达每个设备结果。
- 解析失败仍保留行号、来源文件和结构化原因，不修改原始上传包。

## `inventory_devices`

设备档案继续作为台账主表，复用既有 `device_id` 身份算法。

| 字段 | 类型 | 变化 | 说明 |
| --- | --- | --- | --- |
| `device_id` | VARCHAR(64) | 既有 | 由省份和规范化设备名 SHA-256 派生 |
| `device_key` | VARCHAR(64) | 既有 | 规范化设备名 |
| `province` | VARCHAR(64) | 既有 | 局点省份 |
| `current_device_name` | VARCHAR(256) | 既有 | 当前设备名 |
| `current_site_key` | VARCHAR(160) | 既有 | 当前局点 |
| `current_operator` | VARCHAR(64) | 既有 | 当前运营商 |
| `remark` | TEXT | 兼容保留 | 不通过公共契约或界面暴露 |
| `created_by` | VARCHAR(64) | 兼容保留 | 不通过公共契约或界面暴露 |
| `updated_by` | VARCHAR(64) | 兼容保留 | 不通过公共契约或界面暴露 |
| `latest_task_id` | VARCHAR(64) | 既有 | 手动设备无观测时使用内部 `manual` |
| `latest_status` | VARCHAR(32) | 既有 | 手动设备无观测时为 `manual` |
| `updated_at` | DateTime | 既有 | 最近维护或档案变更时间 |

本次裁剪不新增数据库列；已部署库中的历史维护列继续兼容保留，`init_db()` 只负责既有增量迁移。

## `inventory_observations`

保持既有结构。`observation_id = task_id + device_id` 派生，天然支持同一个任务归档多台设备。设备物理删除时删除该设备全部观测。任务输出目录中的 `inventory.json` 不修改，因此任务详情证据仍可读取，但不再出现在台账观测查询中。

## `inventory_change_audits`

删除审计继续使用该表：

- `task_id` 改为可空；维护操作不伪造任务 ID。
- `observation_id` 对维护操作可为空。
- 维护操作只写入 `action=delete`。
- `before_snapshot` / `after_snapshot` 保存可审计摘要。

删除流程在同一事务内：

1. 查询设备和观测。
2. 构造删除前摘要。
3. 删除该设备的历史审计、观测和设备档案。
4. 写入删除审计。

## 契约模型

台账读模型只暴露巡检和查询所需字段；不暴露备注维护字段。

写入请求模型只有删除路径，且没有请求体；不提供 `InventoryDeviceCreateRequest` 或 `InventoryDeviceUpdateRequest`。

响应字段保持 UTC；时间字段使用 `*_at` 命名。
