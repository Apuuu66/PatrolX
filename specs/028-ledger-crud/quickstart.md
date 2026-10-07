# 快速验证：设备台账维护与网元类型命名

## 展示效果用例

使用 `tests/fixtures/inventory/builder.py::make_inventory_zip` 构造可重复执行的巡检包。样例 `LST ME.txt` 至少包含 3 条设备记录：

| 设备名 | ME type | Software version | 上传网元类型 | 期望 |
| --- | --- | --- | --- | --- |
| NJ-AGG-001 | UMF2020 | V900R016C10SPC200 | UMF2020 | 归档 |
| NJ-AGG-002 | UMF2020 | V900R016C10SPC201 | UMF2020 | 归档 |
| NJ-AGG-003 | UMF2021 | V900R016C10SPC202 | UMF2020 | 不归档，仅任务证据摘要 |

上传省份和运营商分别为江苏、移动。该用例证明一个任务可以归档多台设备，也证明不匹配网元类型的记录不会进入台账。

## 手动界面路径

1. 打开任务列表，点击上传数据包；确认巡检包字段为“网元类型”。
2. 选择江苏、移动和 `UMF2020`，上传多设备样例并等待任务完成。
3. 打开任务详情，确认匹配设备列表显示 `NJ-AGG-001` 和 `NJ-AGG-002`；`NJ-AGG-003` 仅作为未匹配摘要说明。
4. 打开设备台账，确认只出现 `NJ-AGG-001` 和 `NJ-AGG-002`，且两个设备都有本任务观测。
5. 点击新增设备：
   - 选择不同设备名，可创建成功。
   - 再次使用相同省份和设备名，系统提示已存在。
6. 点击已有设备的编辑入口，更新备注并刷新。
7. 点击删除入口，确认危险提示后删除。
8. 刷新设备列表确认设备消失；打开设备详情接口应返回不存在。
9. 再次上传包含相同设备名且网元类型匹配的巡检包；任务完成后设备重新出现在台账。
10. 上传不选择网元类型的普通巡检包，确认任务完成但任务详情明确显示台账未归档原因。

## 后端自动化断言

1. 上传表单和字典页的 `product` 中文文案为“网元类型”。
2. 多设备 `LST ME.txt` 可解析出多台设备，每台保留网元类型、版本、来源文件和行号。
3. 只有记录网元类型规范化后等于上传 `product` 的设备进入台账。
4. 网元类型不匹配的记录不出现在 `devices`，不出现在台账观测，但出现在 `records` 摘要中。
5. 上传 `product` 缺失时任务不失败，台账不归档，原因为 `network_element_type_filter_missing`。
6. 单条记录异常或缺版本不阻断其他匹配记录归档。
7. `parser_version` 为 `2`；旧任务详情仍可读取旧证据。
8. 管理员创建设备成功，响应包含 `remark` 和维护字段。
9. 重复省份 + 规范化设备名返回 `device_already_exists`。
10. 非 admin 创建、更新或删除返回 403。
11. 更新备注只改变维护字段，不改变 `device_id` 和观测数据。
12. 删除设备后，设备、观测和版本历史接口返回不存在或空。
13. 删除不修改 `inventory.json` 文件内容和 checksum。
14. 删除操作写入一条 `delete` 审计。
15. 相同设备身份重新巡检且网元类型匹配后重新建账。
16. OpenAPI 契约和生成客户端同步。

## 验证命令

实现分支内：

```bash
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py web-build
.venv/bin/python build.py e2e
.venv/bin/python build.py verify
```

涉及上传表单、任务详情和台账页面的 E2E 必须覆盖：打开上传 -> 选择网元类型 -> 多设备任务完成 -> 匹配设备归档 -> 新增/编辑/删除 -> 重新巡检可见。
