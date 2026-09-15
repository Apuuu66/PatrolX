# 快速验证：KPI 指标字典与分组展示

## 前置条件

- 仓库已安装依赖：`python build.py install`
- 使用包含 KPI CSV 的样例数据包。
- 本地开发 API/Web 可通过 `python build.py run` 启动。

## 1. 校验配置组织

检查新目录存在且旧混合文件不再被代码引用：

```bash
test -f deploy/config/kpi/common.yaml
test -f deploy/config/kpi/call.yaml
test -f deploy/config/kpi/api.yaml
test -f deploy/config/kpi/media.yaml
rg -n "deploy/config/kpi_rules.yaml" app tests docs || true
```

预期：四个新配置文件存在；实现完成后 `app`、`tests`、`docs` 不再指向旧路径。

## 2. 后端测试

```bash
python build.py lint
python build.py test
```

重点覆盖：
- 配置加载、别名归一化、冲突和公式引用校验。
- 比率先聚合输入再计算。
- 公式输入缺失或分母为零时不可用。
- 未登记指标不改变规则状态。
- CLI/API/单规则重跑结构一致。

## 3. 契约校验与前端客户端

```bash
python build.py contract
python build.py gen-web-api
cd web && npm run build
```

预期：
- OpenAPI 包含 KPI 记录分页接口和 `exclude_records` 参数。
- 生成的前端客户端同步更新。
- 前端类型检查和构建通过。

## 4. 本地全流程

```bash
python build.py verify
```

预期：
- 任务正常完成。
- 新 KPI 规则 JSON 的 `metadata.version=2`。
- `metric_catalog`、`kpi_results`、`unclassified_metrics` 可读。
- 历史 `output/<task_id>/` 不被改写。

## 5. 手工页面验证

1. 打开任务详情，进入一个 KPI 规则。
2. 首屏应看到规则摘要、重点指标和越限/不可用汇总。
3. 切换质量、业务量、容量、时延、其他分组。
4. 输入中文、英文或稳定 key 搜索。
5. 打开指标抽屉，确认公式、输入值、来源文件和直接列交叉参考。
6. 在抽屉中打开原始记录，确认使用分页查询。
7. 查看无阈值指标，确认只有中性值展示，没有通过/失败状态。

## 6. 单规则重跑

```bash
python build.py verify-one --rule kpi.call
```

预期：
- 只重跑 `kpi.call`。
- 结果按新目录配置生成 `metadata.version=2`。
- 前端刷新该规则后显示目录式结果。
- 其他规则 JSON 不被补跑或改写。

## 7. 历史结果兼容

- 使用启用前生成的任务访问规则详情。
- 预期：没有 `metadata.version=2` 时回退到旧 KPI 明细表。
- 不出现伪造的空目录，也不触发历史结果重算。
