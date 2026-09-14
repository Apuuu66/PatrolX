# Quickstart：压缩项解压跳过与白名单策略

## 前置条件

1. 已创建 Python 虚拟环境：
   ```bash
   python build.py install
   ```
2. 项目级配置位于 `deploy/config/extract_policy.yaml`。
3. 准备一个测试主包，建议包含：
   - `skip/0/normal.zip`：应跳过解压。
   - `skip/xx/0/deep.zip`：应按深层前缀跳过解压。
   - `skip/0/AlarmFiles/service_ALARM.zip`：应因目录或文件名关键字命中白名单并解压。
   - `skip/0/alarm.txt`：应按分类拷贝到 `alarm/`。
   - 跳过范围外的一个普通压缩项：应保持既有解压行为。

## 配置样例

```yaml
version: 1
nested:
  skip_all: false
  skip_paths:
    - /skip/
whitelist:
  paths: []
  name_keywords:
    - alarm
```

## 自动化验证

```bash
python build.py lint
python build.py test
python build.py verify
```

重点运行策略相关测试：

```bash
python build.py test -- tests/test_extract_policy.py tests/test_extraction_policy.py tests/test_archive.py tests/test_rule_execution.py
```

具体测试文件名以 `tasks.md` 为准；如测试命令与构建入口参数不一致，以 `python build.py test --help` 输出为准。

## 手工验收

1. 执行一个包含上述结构的本地任务。
2. 检查 `output/<task_id>/.main/skip/`：
   - 原始 `normal.zip`、`deep.zip`、`service_ALARM.zip` 均存在。
3. 检查 category 现场：
   - `other/skip/0/normal.zip` 或对应分类目录下存在未展开压缩项。
   - `other/skip/xx/0/deep.zip` 存在且无内部文件。
   - 白名单命中的 `service_ALARM.zip` 被展开为内部文件。
   - `alarm.txt` 被拷贝到 `alarm/`。
4. 检查 `.patrolx-extracted.json`：
   - `policy.skip_paths` 为 `["skip/"]`。
   - `policy.whitelist_keywords` 包含 `alarm`。
   - 被跳过压缩项状态为 `skipped`，原因为路径命中。
   - 白名单压缩项状态为 `extracted`，决策为 `whitelist`。
5. 检查结构化日志：
   - `alarm.txt` 拷贝事件包含白名单原因。
   - 非白名单且损坏的跳过范围内压缩项只保留为 `skipped`，不阻断任务。

## 预期结果

- 跳过范围内非白名单压缩项 100% 保持未展开。
- 白名单内容 100% 按既有流程进入 category 现场。
- 未配置或未命中的路径行为与 007 基线一致。
- 普通规则无匹配时返回 `skip`，原因中能看出存在策略跳过内容。
