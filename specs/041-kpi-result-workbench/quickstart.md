# Quickstart：验证 KPI 巡检结果判读工作台

**功能**：`041-kpi-result-workbench`  
**适用阶段**：tasks/analyze/review 通过后的实现验收；当前文档描述目标行为，不代表实现已完成。  
**浏览器**：Google Chrome，桌面宽度 1280、1440、1920。

## 1. 前置条件

```bash
cd "$(git rev-parse --show-toplevel)"
git worktree list
git branch --show-current
.venv/bin/python --version
node --version
```

- 实现阶段必须在 `041-kpi-result-workbench` 对应的独立 worktree 中执行，不得在主工作区修改业务代码。
- 验收只使用 `tests/fixtures/make_real_package.py` 生成的合成包。
- 输入、SQLite、输出和截图使用 `/tmp/patrolx-kpi-workbench/` 隔离目录，不读写现场数据库。
- 运行前后检查真实输入 SHA-256；本验收不得修改真实压缩包或其内容。

建议隔离环境：

```bash
mkdir -p /tmp/patrolx-kpi-workbench/output
export PATROLX_SQLITE_PATH=/tmp/patrolx-kpi-workbench/patrolx.db
export PATROLX_OUTPUT_DIR=/tmp/patrolx-kpi-workbench/output
```

若项目使用其他等价配置项，以实际配置定义为准，但必须保持数据库和输出目录均在 `/tmp/patrolx-kpi-workbench/` 下。

## 2. 确认效果图与浏览器

在 Plan Review 或实现验收开始时，用 Google Chrome 打开当前已确认的 v2 效果图：

```bash
open -a "Google Chrome" \
  specs/041-kpi-result-workbench/assets/mockups-v2/review-v2.html
```

逐张核对：

- `assets/kpi-results-v2.png`：三视图、汇总、结果表和证据抽屉。
- `assets/kpi-focus-management-v2.png`：团队关注批量加入/移出、筛选和 dirty 保存。
- `assets/kpi-scope-control-v2.png`：测量单元唯一启停、纳入指标数和历史恢复。
- `assets/rule-network-assignment-v2.png`：一个或多个网元归属、未归属和清空确认。
- `assets/log-supplement-network-v2.png`：UMF/CSP/不指定单选。

五张图的整体结构此前已确认；媒体资源成功率证据口径修订后，用户已确认当前版本。实现中若再次改变界面结构、信息层级或关键交互，必须重新确认效果图。

## 3. 生成合成样例

```bash
.venv/bin/python tests/fixtures/make_real_package.py
```

合成样例必须覆盖：

- 20 个真实呼叫 KPI 指标身份，其中媒体资源创建、修改、删除共 10 个纳入团队关注，至少 5 个属于需处理；20 个均按源包直接提供的 `base` 指标读取，不把成功率标成派生指标，具体清单见 [plan.md](./plan.md) 第 11.1 节。
- `failure`、`warning`、`trend_degraded`、`unjudgeable`、`needs_config` 五类互斥分组。
- UMF 与 CSP 使用相同的 `measurement_unit_id` 和 `metric_resource_id`。
- 历史指标、绑定或派生记录存在 `enabled=false`，恢复结果包含成功和失败。
- 缺阈值、缺方向、无基线、无数据、全零和分母为零等边界。
- UMF 归属规则、CSP 归属规则、多归属规则和未归属规则。
- 日志补充包选择 UMF、选择 CSP、未选择三种变体。
- 团队关注 revision 冲突和证据加载失败的可重试测试数据。

生成器必须使用固定时间戳并保持幂等。生成的 zip 和解压内容只保留在 `/tmp`，不得进入 Git：

```bash
git status --short
git diff --cached --name-status
```

## 4. 自动化门禁

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
.venv/bin/python build.py web-build
.venv/bin/python build.py e2e
.venv/bin/python build.py verify
```

若全量 `verify` 需要默认输入现场，改为在隔离配置下运行；不得为了通过测试覆盖或删除真实数据。

专项测试至少覆盖：

```bash
.venv/bin/python -m pytest tests/test_kpi_workbench_v6.py -q
.venv/bin/python -m pytest tests/test_kpi_team_focus_v6.py -q
.venv/bin/python -m pytest tests/test_kpi_measurement_scope_v6.py -q
.venv/bin/python -m pytest tests/test_rule_network_assignments_v6.py -q
.venv/bin/python -m pytest tests/test_log_supplement_network_scope.py -q
```

契约检查必须确认：

- 五份规划契约已合并进 `docs/api/openapi.yaml`，路径、Schema、错误码和 `202 + Location` 一致。
- v5 `batch-confirm` 与 v2 `inspector-states` 仍为冻结字段语义，只标记 `deprecated`。
- v6 查询旧任务返回 `409 task_result_requires_rebuild`。
- 前端生成客户端可重复生成，无手写 v6 API 路径或响应类型。
- 所有分页接口使用 `page`、`page_size` 和 `total`。
- 所有错误响应为 `{code, message, detail}`。

## 5. 启动页面

```bash
.venv/bin/python build.py run
open -a "Google Chrome" http://127.0.0.1:8000/
```

在 Chrome 中分别把视口设为：

- `1280 × 900`
- `1440 × 900`
- `1920 × 1080`

验收结果：

1. 1280 宽无页面级横向滚动；表内必要的横向滚动只发生在表格容器。
2. 1440×900 首屏同时看到汇总、判定分组和至少 5 个需处理指标。
3. 1920 宽保持内容可读，不把表格列无限拉伸成难以扫读的超宽布局。
4. 默认视图为“需处理”；切换“团队关注”和“全部指标”不改变顶部汇总。
5. 每行只有“查看证据”一个入口；选择行后打开证据抽屉。
6. 1440 及以上抽屉打开时结果列表仍可见；1280 使用覆盖层。
7. 状态不只依赖颜色，键盘可切换视图、筛选、打开证据和保存关注。

## 6. 主路径：需处理 → 证据 → 团队关注

1. 打开含 20 个指标、其中 10 个纳入团队关注的合成任务。
2. 确认三视图计数：需处理 + 无需处理 = 团队关注；全部指标独立显示任务快照全集。
3. 在“需处理”中依次核对五类分组顺序：失败 → 预警 → 趋势恶化 → 无法判定 → 待配置。
4. 点击任一失败指标，确认证据包含今日值、昨日值、变化、阈值来源、日聚合、有效点、对象/周期分组、来源文件及 7 日趋势。
5. 打开技术分析，确认跨任务历史与同设备版本对比只在次级区域按需加载，不参与首屏排序。
6. 打开 `TeamFocusDrawer`，按测量单元筛选并批量加入一个当前指标、移出另一个指标，保存后 revision 加 1。
7. 确认关注变化不改变巡检结果、报告和已生成历史结果。
8. 从关注移除一项后切到“全部指标”，一次操作即可重新找到并加入。

## 7. 证据失败与局部重试

在 E2E 中拦截单个 evidence 请求并返回 `424 kpi_evidence_unavailable`：

1. 结果表和顶部汇总仍正常显示。
2. 证据抽屉显示错误原因和“重试”动作。
3. 解除拦截后点击重试，只有该 drawer 恢复，不整页重新加载。
4. 其他指标行和视图计数不受影响。

可重复验证以 Playwright 的网络拦截为权威层，不用人工改历史 JSON 文件。

## 8. 团队关注 revision 冲突

1. 在 Chrome 打开两个会话或两个标签页，均加载 UMF 团队关注，记录相同 `revision`。
2. 标签页 A 加入一个指标并保存，revision 递增。
3. 标签页 B 用旧 revision 保存另一个差异。
4. 预期返回 `409 team_focus_revision_conflict`，响应 detail 同时含 `expected_revision`、`current_revision` 和 `network_element_type`。
5. B 页面保留本地暂存差异，不自动覆盖或静默丢弃；刷新后由维护人员确认重试。
6. 确认数据库没有部分写入，revision 只由成功请求递增。

## 9. UMF/CSP 隔离与共享关注

1. 分别打开 UMF 与 CSP 合成任务；二者使用相同的测量单元 ID 和指标 ID。
2. 在 UMF 加入关注，CSP 同一 ID 不得出现该关注。
3. 在 CSP 加入关注，UMF 也不得出现。
4. 同一网元类型下的第二个 UMF 任务应共享同一关注集合和 revision。
5. 关注不携带 `task_id`、`device_id` 或用户名作为身份。
6. 当前任务不可用的历史关注保留显示为 `unavailable` 并给出原因，不自动删除。

## 10. 测量单元启停与历史恢复

1. 在测量单元页停用一个单位，确认提示“只影响后续巡检”。
2. 绑定、派生、维护口径、团队关注和历史结果均保留。
3. 启动新任务，该单位下基础指标和派生指标均不进入任务快照。
4. 重新启用单位并启动新任务，所有已确认基础指标和所有已定义派生指标均纳入，不允许指标级开关排除。
5. 打开历史停用恢复审计，确认逐对象记录 metric/binding/derived、之前状态、结果、时间和失败原因。
6. 触发含至少一个失败项的恢复重试，确认状态为 `partial_success`；成功项不回滚，失败项仍有错误和尝试次数。
7. 确认相同 `idempotency_key` 重试不会创建重复维护操作。
8. 绑定页只保留诊断和单条异常修正，不出现批量确认入口。

## 11. 未归属规则与归属审计

1. 升级后首次进入规则归属页，确认所有既有业务规则初始为“未归属”，不存在“公共”选项。
2. 未归属规则在 UMF、CSP 和未选类型的日志包中均不执行，也不生成 `skip`。
3. 将一条规则只归属 UMF，启动 UMF 任务时执行，启动 CSP 任务时不出现该规则结果。
4. 将同一规则增加 CSP 归属，两个类型的后续任务均执行。
5. 不提交 `confirm_unassign` 清空最后归属，预期 `400 rule_unassign_confirmation_required`。
6. 提交 `confirm_unassign=true` 后规则进入未归属并停止参与后续任务。
7. 用过期 `expected_revision` 保存，预期 `409 rule_assignment_revision_conflict`。
8. 批量请求中任一规则冲突时整批不应用；成功批量写入每条规则各一条审计，全局 revision 只递增一次。
9. 在审计页按 UMF 筛选，可看到该规则进入和离开 UMF 的前后集合、actor、source、result 和时间。

## 12. 任务开始冻结与执行中修改

1. 上传任务并使其进入排队状态，但尚未真正开始。
2. 在排队期间修改规则归属、测量单元启停或 KPI 配置。
3. 任务真正开始时冻结当前规则集合/版本、归属 revision、注册表指纹、KPI 配置和指标集合。
4. 执行中再次修改配置，当前任务结果保持不变。
5. 后续任务或显式重建使用新配置。
6. 单规则/增量重跑只读取任务快照：
   - 规则不在快照：`rule_not_in_task_scope`。
   - 注册表版本变化：`rule_snapshot_version_mismatch`。
7. 历史任务结果不因归属或配置变化被改写。

## 13. 日志补充包规则适用网元

### 13.1 选择 UMF

1. 上传 `log_supplement` 包，`rule_network_element_type=UMF`。
2. 只执行 UMF 归属命中的业务规则。
3. 任务 `product` 仍为空，分类 profile 仍为 `GENERIC`。
4. 不触发设备台账解析、归档或 UMF/CSP 精细分类。

### 13.2 选择 CSP

同包内容使用不同文件名上传并选择 CSP，只执行 CSP 归属命中的业务规则，其他隔离要求与 UMF 相同。

### 13.3 不指定

1. 不传 `rule_network_element_type`。
2. 只执行解压、分类等内部技术单元，普通业务规则集合为空。
3. 页面明确显示“未选择规则适用网元类型”。
4. 不得显示“全部通过”或伪造任何规则 `skip` 结果。

### 13.4 错误与幂等

- 巡检包携带非空 `rule_network_element_type`：`400 metadata_not_applicable`。
- 日志包选择运行时字典外或公共值：`400 invalid_rule_network_element_type`。
- 同名、同 checksum、同 kind、同 product、同规则适用类型重复上传：`202` 幂等恢复，不重跑。
- 同名同 checksum/kind/product 但规则适用类型不同（包括一方未选）：`409 package_rule_network_element_type_conflict`。
- checksum 不同时优先返回 `package_checksum_conflict`，不得继续比较 kind、product 或规则类型。

## 14. 旧任务行内重建

1. 打开一个没有 v6 KPI 快照的旧任务，进入 KPI 结果页。
2. 预期 API 返回 `409 task_result_requires_rebuild`，页面显示重建动作，不渲染 v5 兼容面板。
3. 点击任务行内“重建”，确认对话框明确包含：
   - 删除并重建任务输出；
   - 操作不可撤销；
   - 原始上传包只读。
4. 确认后调用 `POST /api/v2/tasks/{task_id}/rebuild`，`mode=full`、`confirmed=true`。
5. 预期 `202 + Location`，`task_id` 保持不变。
6. 重建完成后刷新 KPI 工作台，按当前规则归属和 KPI 配置展示新结果。
7. 原始包缺失时返回 `409 package_missing` 并引导上传同名包，不删除历史记录。

## 15. 视觉与可访问性记录

验收截图只写入临时目录：

```bash
mkdir -p /tmp/patrolx-kpi-workbench/screenshots
open -a "Google Chrome" http://127.0.0.1:8000/
```

每个视口至少保存：

- 默认需处理首屏；
- 团队关注抽屉；
- 证据抽屉；
- 测量单元范围页；
- 规则归属页；
- 日志补充包上传表单。

不得把截图、数据库、真实包、输出目录或日志加入 Git。最终记录应包含视口尺寸、任务 ID、构建版本、测试命令和通过/失败结果。

## 16. 常见问题

### 打开 KPI 页面显示需要重建

该任务没有 v6 快照。按任务行重建，不要修改历史 JSON 或让前端回退到 v5。

### 团队关注为空但指标仍全部巡检

这是正确行为。关注只决定查看范围，不决定巡检执行范围；巡检启停只看测量单元。

### 新增规则没有出现在任务结果

先检查规则归属是否包含当前网元类型。未归属规则不执行，也不会生成 `skip`。

### 日志包显示没有业务规则结果

确认是否选择了“规则适用网元类型”。未选择时只执行内部技术单元，这是明确空态，不是全部通过。

### 同名日志包上传冲突

按错误码处理：先核对包内容 checksum，再核对 package kind、product，最后核对规则适用网元类型。不要跳过前置比较直接修改类型。

### 恢复操作显示部分失败

`partial_success` 表示部分对象已成功恢复且不会回滚。查看逐项错误后只重试失败项。
