# 快速验证：保留主包现场并原地解压日志压缩文件

## 前置条件

1. 后端依赖已安装。
2. 可使用真实样例包 `uploads/ZZapp01BCN_app_Problem_scene_333.zip`，或使用测试中构造的嵌套样例。
3. 本地验证从仓库根目录执行。

## 自动化验证

```bash
make lint
make test
make verify
```

重点测试：

- 主包现场保留。
- 多级子压缩包按自身分类展开。
- `.log.gz` 展开为同目录 `.log`。
- `logs/` 不保留原始子压缩包或 `.log.gz`。
- 失败隔离与重跑幂等。

## 场景 1：保留主包原始现场

1. 执行本地全流程。
2. 打开本次任务目录：

   ```text
   output/<task_id>/
   ```

3. 预期存在：

   ```text
   .main/
   logs/
   kpi/
   traffic/
   alarm/
   config/
   resource/
   .patrolx-extracted.json
   ```

4. `.main/` 内应能看到上传包的原始目录结构，且不被后续阶段删除。

## 场景 2：日志子包与历史日志解压

1. 使用包含 `ServiceLog_*.zip` 的样例执行任务。
2. 检查 `logs/` 中出现服务、节点目录层级下的普通 `.log` 文件。
3. 确认 `.log.gz` 已有同名 `.log`。
4. 确认 `logs/` 中不存在 `.zip`、`.tar.gz`、`.tar`、`.tgz` 或已成功展开的 `.log.gz`。
5. 确认 `.main/` 中仍保留原始 `ServiceLog_*.zip`。

## 场景 3：KPI 子包内包含多类子包

1. 构造如下结构：

   ```text
   main.zip
   └── kpi_outer.zip
       ├── kpi_data.zip
       └── ServiceLog.zip
   ```

2. 执行任务。
3. 预期 KPI 数据出现在 `kpi/`，日志文件出现在 `logs/`。
4. 预期 `kpi/` 和 `logs/` 不保留中间压缩包。
5. 预期 `.patrolx-extracted.json` 记录每一层子包状态和分类原因。

## 场景 4：失败隔离

1. 构造一个正常 `.log.gz`、一个损坏 `.log.gz` 和其他业务文件的包。
2. 执行任务。
3. 预期任务继续完成。
4. 预期正常 `.log.gz` 生成 `.log`。
5. 预期损坏文件在 manifest 或执行日志中有显式失败原因。
6. 预期其他规则结果不受影响。

## 场景 5：重跑幂等

1. 连续执行同一上传包两次。
2. 预期第二次复用 `.main/` 和已成功展开结果。
3. 预期日志指标不变。
4. 预期 `.main/` 仍完整保留。
