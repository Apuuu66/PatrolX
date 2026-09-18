# 快速验证：KPI 资源全集登记与在线分类

## 1. 命令行导入资源全集

准备 CSV：

```csv
资源id,中文描述,英文描述
UNIT_1,次,times
ME_21002,创建媒体资源请求次数(次),Create Media Resource Request Count
ME_21003,媒体成功率,对应英文
```

执行预览：

```bash
python tools/generate_kpi_config.py --resource-csv /path/to/resource.csv
```

执行登记：

```bash
python tools/generate_kpi_config.py --resource-csv /path/to/resource.csv --apply
```

预期：

- `UNIT_1` 被跳过。
- `me_21002` 和 `me_21003` 进入 `deploy/config/kpi/resource_metrics.yaml`。
- 两个指标 `domain` 均为 `null`。
- `call.yaml`、`api.yaml`、`media.yaml` 不因导入而新增指标。

## 2. 在线分类

```bash
python build.py run
```

打开左侧菜单 `KPI 资源`：

1. 搜索 `21002`，确认能看到资源指标。
2. 选择一个或多个未分类指标。
3. 选择目标域 `media`，点击批量分类。
4. 刷新页面确认状态变为 `media`。
5. 检查 `deploy/config/kpi/media.yaml`，确认指标定义已写入且没有自动阈值或公式。

## 3. 引用保护验证

1. 在 `api.yaml` 中给某个已分类指标配置阈值或把它加入公式输入。
2. 尝试在 KPI 指标资源页面把它改到 `call`。
3. 预期页面提示指标被引用，`api.yaml` 和资源库状态保持不变。

## 4. 质量门禁

```bash
python build.py contract
python build.py gen-web-api
python build.py lint
python build.py test
python build.py web-build
```

涉及本地全流程时再执行：

```bash
python build.py verify
```
