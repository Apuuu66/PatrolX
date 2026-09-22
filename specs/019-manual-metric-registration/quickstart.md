# 快速验证：人工注册指标

## 前置条件

1. 准备一个包含 KPI 测量单元 CSV 的任务包，其中至少一列未在资源目录中注册。
2. 使用 admin 账号访问 Web 界面。
3. 启动本地服务：`python build.py run`。

## 界面验证

1. 打开“测量单元”页面，进入绑定列表。
2. 找到指标 ID 为空的候选绑定。
3. 点击“注册指标”，确认表单预填基础列名和展示单位。
4. 提交后确认：
   - 绑定显示新的 `ME__MANUAL_` 前缀 ID。
   - 绑定状态仍是“候选”。
   - 指标带“人工注册”标识。
5. 点击“编辑指标”，修改中文名、英文名或启用状态。
6. 保存后确认：
   - 资源 ID 不变。
   - 绑定状态、任务和来源文件不变。
   - 中文重复时保存被拒绝。
7. 人工确认绑定后，重跑或执行 KPI 巡检，验证确认绑定参与巡检。

## 命令验证

```bash
python build.py lint
python build.py test
python build.py contract
python build.py gen-web-api
python build.py verify
```

## 期望

- 后端测试覆盖注册、改绑已有资源、重复中文名、非人工资源编辑和绑定状态保持。
- OpenAPI 与 Pydantic/前端客户端一致。
- 全流程验证无失败。
