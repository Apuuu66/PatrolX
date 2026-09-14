# 快速验证：分类短路径解压与准备状态

## 前置条件

1. 使用仓库根目录。
2. 已创建虚拟环境：`python build.py install`。
3. 准备一个包含日志、KPI、配置或嵌套分类子包的 zip 样例。可临时使用：
   ```bash
   mkdir -p local_run
   cp tests/fixtures/sample/sample.zip local_run/
   ```

## 1. 共享解压现场验证

```bash
python main.py
```

预期：

- `python main.py` 只扫描 `local_run/`，不扫描 `uploads/`。
- 主包证据仍在 `output/<task_id>/.main/`。
- 分类文件出现在 `output/<task_id>/logs/`、`output/<task_id>/kpi/` 等分类根下。
- 分类路径不额外插入来源子压缩包目录层。
- `.patrolx-extracted.json` 的 `version` 为 `4`。

示例断言方向：

```text
存在：output/<task_id>/kpi/<压缩包内部路径>/kpi.csv
不存在：output/<task_id>/kpi/<来源子包名>/<压缩包内部路径>/kpi.csv
```

## 2. 在线任务列表展示

```bash
python build.py run
```

打开任务列表页后预期：

- 每个任务卡片出现“数据准备”摘要。
- 成功任务默认折叠。
- 失败、冲突或长路径任务默认展开。
- 点击标题或箭头可在当前卡片内折叠/展开。
- 展开内容不进入 Pass/Warn/Fail 普通规则统计。

## 3. 删除失败展示

选择一个存在长路径或占用文件的现场触发删除：

预期：

- 不提示“任务已删除”。
- 完整错误提示展示 5 秒。
- 收起后任务卡片保留“删除失败”状态，可重新展开。
- 错误包含任务标识、现场位置、原因；路径过长时包含实际长度和上限。
- “重试删除”可再次触发；成功后提示消失且任务移除。

## 4. 契约与生成客户端

```bash
python build.py contract
python build.py gen-web-api
```

预期契约校验通过，`web/src/api/client.ts` 包含 `DataPreparationV2` 等生成类型。

## 5. 质量门禁

```bash
python build.py lint
python build.py test
python build.py verify
```

涉及 UI 时还需要：

```bash
cd web && npm run build
```

实现分支内完成并通过以上验证后，才可进入 review/合入流程。
