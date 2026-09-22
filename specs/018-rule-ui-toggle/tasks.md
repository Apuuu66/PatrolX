# 任务：界面规则启停

**输入**：来自 `/specs/018-rule-ui-toggle/` 的设计文档

## 阶段 1：设置

- [x] T001 在 `specs/018-rule-ui-toggle/` 保存规格、澄清结论、计划、研究、数据模型、API 契约和快速验证文档
- [x] T002 完成 Speckit 产物 analyze/review 并提交 `main` 后，从 `main` 创建实现分支 `feature/018-rule-ui-toggle` 与 `.worktrees/018-rule-ui-toggle`

## 阶段 2：基础层

- [x] T003 在 `app/models/db.py` 新增规则启停状态模型，在 `app/models/schemas.py` 新增 `InspectorState`、分页响应和启停请求契约
- [x] T004 新增 `app/services/rule_states.py`，实现普通规则状态初始化、启用集合查询和状态更新；同步调整 `app/inspectors/registry.py`，禁用规则不再从注册表删除
- [x] T005 调整 `app/services/executor.py`，支持任务级启用规则集合，并确保停用普通规则的私有 prepare 不执行

## 阶段 3：用户故事 1 - 查看并切换规则启停状态（P1）

- [x] T006 [P] [US1] 新增 `tests/test_rule_states.py`，覆盖初始化、持久化、重复更新、未知规则、隐藏规则和启用集合
- [x] T007 [P] [US1] 新增 `tests/test_rule_states_api.py`，覆盖列表状态字段、管理员启停、非管理员拒绝、未知规则和不可管理规则
- [x] T008 [US1] 更新 `docs/api/openapi.yaml`、`app/api/router.py` 与 Pydantic 契约，实现分页 `/api/v2/inspector-states` 和启停更新接口；保持既有 `/api/v2/inspectors` 兼容
- [x] T009 [US1] 执行前端 API 客户端生成后，更新 `web/src/api/http.ts` 与 `web/src/pages/InspectorsPage.tsx`，接入默认 10 条分页并展示启停开关、筛选和错误反馈

## 阶段 4：用户故事 2 - 新任务只执行启用规则（P2）

- [x] T010 [P] [US2] 新增 `tests/test_rule_state_tasks.py`，覆盖停用规则不产生新任务结果、重新启用恢复、历史结果不变、全部普通规则停用时任务完成
- [x] T011 [US2] 在 `app/services/tasks.py` 和 `app/cli.py` 接入任务开始时启用集合，并拒绝重跑停用规则和增量重建停用规则

## 阶段 5：用户故事 3 - 初始化与冲突状态清晰可见（P3）

- [x] T012 [P] [US3] 在 `tests/test_rule_states.py` 补充 `disabled_rules` 首次导入、初始化后配置修改不覆盖界面状态、新注册规则默认启用、连续 10 条顺序切换和非法/未知配置错误用例
- [x] T013 [US3] 实现/修正初始化冲突与错误提示，确保配置引用未知规则或格式非法时不静默接受

## 阶段 6：收尾

- [x] T014 更新 `docs/architecture.md` 中规则启停、任务计划和配置初始化的说明
- [x] T015 执行 `python build.py contract && python build.py gen-web-api`，确认 OpenAPI、Pydantic 和前端客户端一致
- [x] T016 执行 `python build.py lint && python build.py test`
- [x] T017 执行 `python build.py web-build && python build.py verify`
- [x] T018 按 `quickstart.md` 完成端到端检查并提交实现

## 依赖与执行顺序

- T002 → T003 → T004 → T005 → US1 → US2 → US3 → 收尾。
- T006/T007/T010/T012 可先写失败测试，但实现依赖 T003/T004/T005；T006/T012 只保留一个基础初始化断言入口，其余边界由 T012 覆盖。
- US1 提供界面状态能力；US2 依赖启用集合进入任务执行；US3 依赖状态初始化语义。
- T015 后必须重新执行 T016/T017，避免契约和前端生成漂移。

## 并行机会

- T006/T007/T010/T012 分属不同测试文件，可并行补充。
- 后端契约与前端交互设计可在 API 契约冻结后并行推进。
- 当前单人实现按编号顺序执行，避免同文件冲突。

## 实现策略

按基础层 → US1 → US2 → US3 → 收尾执行。每个阶段先跑新增测试，再跑相关回归测试；进入下一阶段前修复当前阶段失败。
