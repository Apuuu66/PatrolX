# 快速验证：设备台账版本以 LST ME 执行时间为准

## 1. 展示效果用例（代表性样例包）

`tests/fixtures/make_real_package.py` 的 `LST ME.txt` 内容**只增不减**地补入头部执行时间行（固定时间戳、保持幂等），例如：

```text
+++    CSP/*××××××××××××*/     2025-05-26  14:40:36
%%LST ME:;%%
RETCODE = 0  操作成功

查询结果
--------
网元名称: UMF-SZ-01
...
```

同时新增"头部无执行时间"的边界样例文件（例如 `config/LST ME_no_time.txt` 或独立测试包），用于验证回退路径在界面与接口中同样可见。

单元测试样例构造器 `tests/fixtures/inventory/builder.py` 增加可选的头部时间参数（不传时保持既有内容不变，避免影响既有断言）。

## 2. 后端验证

实现分支内运行：

```bash
python build.py contract
python build.py gen-web-api
python build.py lint
python build.py test
```

必须覆盖的自动化断言：

1. 头部行尾时间解析成功：`+++    CSP/*xx*/     2025-05-26  14:40:36` → `2025-05-26T06:40:36+00:00`（UTC，沿用既有 `isoformat()` 约定）。
2. 首行为 `%%LST ME:;%%` 噪声、时间行在第二条非设备记录行时仍能解析。
3. 头部无时间 / 日期非法（`2025-02-30`）/ 晚于任务完成时间 5 分钟以上 → 回退任务完成时间，`time_source=task` 且原因正确。
4. 多设备文件：全部设备记录共用文件头时间；多来源文件各自独立；同一设备命中多个来源文件时取其最近的可解析执行时间。
5. 证据结构：`schema_version=3`、`parser_version=4`、`execution_time.per_file` 含原文与行号。
6. 归档：`observed_at` 取执行时间；`time_source=lst_me`；同一任务重跑覆盖且时间随之刷新。
7. 乱序补传：先完成执行时间较晚的任务、再完成较早任务，设备 `current_version` 与 `last_seen_at` 不回退。
8. 相同执行时间：按 `task_id` 稳定排序，重复查询结果一致。
9. 兼容：历史证据（无 `execution_time`）与历史观测（`time_source` 默认 `task`）读取不报错；无 `LST ME.txt` 来源文件的任务返回 `execution_time={"status":"missing","source":"task","per_file":[]}`。
10. 冲突不变：同一任务内同名设备多版本值仍判 `conflict` 且不进入当前版本裁决。
11. 契约：OpenAPI 与 Pydantic 一致，生成客户端包含 `time_source` / `time_source_reason` / `execution_time`。

## 3. 前端与端到端验证

```bash
python build.py e2e            # 或 cd web && npx playwright test e2e/inventory-execution-time.spec.ts
```

E2E 必须覆盖：

1. 上传含头部执行时间的包 → 设备详情显示执行时间并标注来源为设备执行时间。
2. 上传头部无时间的包 → 显示任务完成时间并标注兜底来源。
3. 先上传执行时间较晚的包、再上传较早的包 → 设备列表"当前版本"仍是较晚执行的版本，"最近观测"不回退。
4. 任务详情台账面板显示本次归档使用的执行时间与来源。

## 4. 手工验证

```bash
python build.py run
```

1. 打开 `/inventory`：检查"当前版本""最近观测"与来源标识。
2. 打开设备详情：检查"当前版本""最近观测""观测时间"列与版本历史的时间来源。
3. 打开任务详情 → 台账面板：检查执行时间、来源与回退原因说明。
