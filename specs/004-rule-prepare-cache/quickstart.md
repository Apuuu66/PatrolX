# 快速验证：规则私有预处理与轻量缓存

## 前置条件

1. 后端依赖已安装。
2. 仓库内存在样例包 `tests/fixtures/sample/sample.zip`。
3. 本地开发时可使用 PyCharm 直接运行 `main.py`，不需要记忆额外刷新命令。

## 自动化验证

```bash
make lint
make test
make verify
```

重点测试文件：

- `tests/test_prepare_cache.py`
- `tests/test_prepare_pipeline.py`
- `tests/test_executor.py`

## 场景 1：全量任务三阶段执行

1. 将样例 zip 放入 `uploads/`，或直接依赖 `make verify` 的样例兜底。
2. 运行本地全流程：

   ```bash
   make verify
   ```

3. 打开最新任务目录下的 `execution.log`。
4. 预期顺序：

   - extract 日志完成。
   - `kpi.threshold` 与 `log.app_service` 的 prepare 执行完成。
   - inspect 规则开始执行。
5. 预期文件：

   ```text
   output/<task_id>/prepared/kpi.threshold/
   output/<task_id>/prepared/log.app_service/
   ```

## 场景 2：代码未变化时缓存命中

1. 完成一次全量运行。
2. 不修改规则代码，再次运行：

   ```bash
   python main.py run
   ```

3. 预期结果：

   - `execution.log` 出现 `prepare_cache_hit`。
   - prepared 目录没有被清空重建。
   - 目标规则结果仍正常生成。

## 场景 3：当前规则文件变化后自动重建

1. 选择 `kpi.threshold` 或 `log.app_service`。
2. 修改该规则文件中的 prepare 逻辑，例如调整一个临时日志文本。
3. 再次运行该规则：

   ```bash
   python main.py run-one --rule kpi.threshold
   ```

4. 预期结果：

   - `execution.log` 出现 `prepare_cache_rebuild`。
   - `prepared/<owner_code>/` 被重建。
   - 当前规则 inspect 使用最新 prepared 数据。
   - 不需要执行刷新命令。

## 场景 4：删除 prepared 目录后重建

1. 完成一次运行。
2. 删除整个目录：

   ```text
   output/<task_id>/prepared/kpi.threshold/
   ```

3. 再次运行：

   ```bash
   python main.py run-one --rule kpi.threshold
   ```

4. 预期结果：目录和 `.prepare.md5` marker 重新生成。

## 场景 5：prepare 失败不扩散

1. 临时让样例 prepare抛出异常。
2. 运行该规则或全量任务。
3. 预期结果：

   - 日志出现 `prepare_error`。
   - 对应 owner 规则结果为 `skip`，原因说明预处理未就绪。
   - 其他普通规则继续生成结果。
4. 恢复代码后再次运行，prepare 自动重建并恢复正常结果。

## 目录边界

- 既有解压分类目录保持现状，例如 `logs/`、`kpi/`；本功能不做 `data/` 目录迁移。
- 只新增 `output/<task_id>/prepared/<owner_code>/`；不得新增 `system_id` 目录层。
- `source_patterns` 使用 Python regex 和 `re.fullmatch()`，匹配 `output/<task_id>/` 相对路径。

## 验收边界

- 单独删除 prepared 中的业务输出文件但保留 `.prepare.md5` 时，不要求自动重建。
- 主包解压失败时任务必须失败，不能继续 prepare/inspect。
- 不应出现新的手动刷新命令、环境变量或 UI 开关。
