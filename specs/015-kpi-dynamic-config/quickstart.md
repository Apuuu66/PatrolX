# 快速验证：KPI 按需分类与动态口径配置

## 前置条件

1. 已安装项目依赖：
   ```bash
   python build.py install
   ```
2. `deploy/data/kpi/base/` 存在离线生成的基础资源和预留单位。
3. 数据库已初始化；KPI 规则配置允许为空。
4. `rules/*.json` 不是运行时依赖；可临时移走后验证。
5. 准备一个包含 KPI CSV 的数据包，其中至少有一列当前未分类。

## 启动

```bash
python build.py run
```

前端访问页面：

- `/kpi-resources`：KPI 配置中心
- `/tasks/<task_id>`：任务详情
- `/tasks/<task_id>/rules/kpi.call` 等：规则详情

## 按需分类闭环

1. 上传并执行包含未分类 KPI 列的数据包。
2. 打开任务详情，确认出现“KPI 按需分类线索”。
3. 检查线索状态：
   - `unclassified`：可去分类；
   - `classified`：可重跑；
   - `unregistered`：需离线更新资源全集；
   - `ambiguous`：需人工确认。
4. 从 `unclassified` 线索进入基础指标页。
5. 勾选指标并分类到 `call`、`api` 或 `media`。
6. 返回任务详情，按提示手动重跑相关 KPI 规则。
7. 确认只有目标规则结果更新。

## 动态配置验证

1. 在 KPI 配置中心修改一个 raw 指标的聚合方式。
2. 为另一个指标配置受控 ratio 公式。
3. 新增或修改业务域阈值。
4. 修改容量规则、展示规则或公共配置。
5. 每次保存后检查：
   - 响应包含新的 `rule_config_version`；
   - 配置审计新增记录；
   - 失败输入不会产生部分保存。

## 快照与重跑验证

1. 对修改配置前的已完成任务执行单规则重跑，确认结果仍使用旧快照。
2. 创建新任务，确认新快照包含：
   - `schema_version: 2`；
   - `classification_version`；
   - `rule_config_version`；
   - 完整 `base_metrics`；
   - 有效 `metrics` 和 `rules`。
3. 对历史任务执行全量重建，确认按当前配置生成新快照。
4. 确认单条 KPI 文件解析失败不会中断整个任务。

## 退役验证

1. 临时移除 `deploy/data/kpi/rules/` 下所有 JSON。
2. 创建新任务。
3. 确认系统仍能基于数据库配置生成快照并执行 KPI 规则。
4. 恢复基础资源文件；不要把 `rules/*.json` 作为运行时依赖恢复。

## 契约与回归验证

```bash
python build.py contract
python build.py gen-web-api
python build.py lint
python build.py test
python build.py verify
cd web && npm run build
```

预期全部通过；OpenAPI、Pydantic、生成客户端和前端调用保持一致。
