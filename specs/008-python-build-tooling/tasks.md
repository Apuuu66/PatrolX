---
description: "统一 Python 构建工具实现任务列表"
---

# 任务：统一 Python 构建工具

**输入**：来自 `/specs/008-python-build-tooling/` 的设计文档

**前置条件**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/build-cli.md`、`quickstart.md`

**测试**：本功能必须包含构建入口单元测试、环境流程测试和旧入口迁移看护测试；实现前先确认对应测试失败。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事（US1–US4）
- 描述中包含精确的文件路径

---

## 阶段 1：设置

**目的**：建立隔离实现环境和构建入口骨架

- [x] T001 创建实现分支 `feature/python-build-tooling` 和 worktree `.worktrees/feature-python-build-tooling`，先提交本目录全部 Speckit 产物
- [x] T002 [P] 在 `tests/build/test_build_entry.py` 中编写入口测试：覆盖 `--help`、命令注册、未知命令、缺参错误和 Python 版本检查
- [x] T003 在 `build.py` 中创建标准库 `argparse` 子命令骨架、命令注册表、帮助输出和非零错误路径；先让 T002 通过

**检查点**：构建入口骨架可运行 `python build.py --help`，未知命令返回非零且提示可用命令

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：实现跨平台环境、精确依赖锁和可注入的子进程执行基础

**⚠️ 关键**：本阶段完成前不得开始用户故事实现

- [x] T004 [P] 在 `tests/build/test_build_environment.py` 中编写环境测试：覆盖 `.venv` 缺失、平台解释器路径、Python 3.11+ 检查、锁文件安装参数和现有 uv 环境不兼容提示
- [x] T005 [P] 在 `tests/build/test_build_lock.py` 中编写锁维护测试：覆盖 `lock` 命令、精确版本行、平台环境标记和不使用 `uv.lock`
- [x] T006 在 `build.py` 中实现跨平台环境工具：后端解释器选择、Python 版本校验、`.venv` 健康检查、无 shell 参数列表执行器和可注入执行钩子
- [x] T007 在 `build.py` 中实现 `install`：使用官方 Python 标准能力创建/复用 `.venv`，按 `requirements-lock.txt` 安装依赖，并用 `--no-deps` 安装本地项目
- [x] T008 在 `build.py` 中实现 `lock`：从 `pyproject.toml` 解析依赖并刷新 `requirements-lock.txt`；生成结果必须包含直接与传递依赖精确版本及平台标记
- [x] T009 创建 `requirements-lock.txt`：锁定当前后端、pytest、Ruff 与传递依赖精确版本；为 Windows/macOS/Linux 差异加入环境标记
- [x] T010 在 `pyproject.toml` 中保留直接依赖声明并核对与 `requirements-lock.txt` 的范围一致；不引入 uv
- [x] T011 运行 `python build.py install`、`python build.py lock --check`（或等效只读校验）、`tests/build/test_build_environment.py` 和 `tests/build/test_build_lock.py`

**检查点**：干净环境只需官方 Python 即可完成精确依赖安装；环境与锁行为有测试覆盖

---

## 阶段 3：用户故事 1 - 新成员零 Make 完成基础流程（优先级：P1）🎯 MVP

**目标**：新成员只使用 `python build.py install` 和 `python build.py verify` 完成依赖安装与本地全流程。

**独立测试**：在无 GNU Make、无 uv、只有官方 Python 的环境中执行安装和本地巡检，确认生成任务目录、规则结果和报告，且不依赖 Makefile 或 shell 包装。

### 用户故事 1 的测试

- [x] T012 [P] [US1] 在 `tests/build/test_build_verify.py` 中编写测试：`verify` 调用 `.venv` 内 Python 执行 `main.py`；`.venv` 缺失时提示安装；不调用 Make/uv
- [x] T013 [P] [US1] 在 `tests/build/test_build_install.py` 中编写端到端级安装流程测试：精确锁参数、本地项目 `--no-deps`、Windows/macOS/Linux 路径和不使用 shell

### 用户故事 1 的实现

- [x] T014 [US1] 在 `build.py` 中实现 `verify` 子命令，调用现有本地全流程入口并透传环境变量；失败保留原始输出
- [x] T015 [US1] 完善 `build.py` 的 `install` 错误提示：缺锁、Python 版本不足、现有 `.venv` 不兼容和 pip 初始化失败分别给出下一步操作
- [x] T016 [US1] 更新 `README.md` 的快速开始和基础流程，统一使用 `python build.py install`、`python build.py verify`

**检查点**：用户故事 1 可独立验证；README 基础流程不再要求 Make、uv 或 shell 包装

---

## 阶段 4：用户故事 2 - 贡献者用一致入口完成质量门禁（优先级：P1）

**目标**：贡献者使用 `python build.py lint` 和 `python build.py test` 完成后端质量检查。

**独立测试**：分别构造通过和失败的风格/测试状态，运行统一命令，确认退出码、失败输出和帮助信息一致。

### 用户故事 2 的测试

- [x] T017 [P] [US2] 在 `tests/build/test_build_quality.py` 中编写测试：`lint` 分别调用 Ruff check 和 format check；`test` 调用 pytest；环境缺失和子进程失败返回非零

### 用户故事 2 的实现

- [x] T018 [US2] 在 `build.py` 中实现 `lint` 子命令，复用现有 Ruff 配置并保持当前检查范围 `app tests`
- [x] T019 [US2] 在 `build.py` 中实现 `test` 子命令，调用 pytest 并保持现有 pytest 配置
- [x] T020 [US2] 在 `README.md` 和 `docs/architecture.md` 中更新质量门禁命令为 `python build.py lint` / `python build.py test`

**检查点**：质量门禁可独立通过统一入口运行；通过和失败状态可被测试验证

---

## 阶段 5：用户故事 3 - 维护者完成契约、前端客户端和单规则调试（优先级：P2）

**目标**：维护者使用统一入口完成 OpenAPI 校验/导出、前端客户端生成和单规则重跑。

**独立测试**：使用现有契约与样例任务数据运行 `contract`、`gen-web-api`、`verify-one --rule <code>`，确认产物语义与旧入口一致，缺参提示可操作。

### 用户故事 3 的测试

- [x] T021 [P] [US3] 在 `tests/build/test_build_contract.py` 中编写测试：`contract` 调用现有 OpenAPI 导出模块；`gen-web-api` 在 `web/` 下调用 npm/npx 生成客户端
- [x] T022 [P] [US3] 在 `tests/build/test_build_verify_one.py` 中编写测试：`verify-one` 要求 `--rule`，正确透传到现有 CLI `run-one`，并复用 `.venv`

### 用户故事 3 的实现

- [x] T023 [US3] 在 `build.py` 中实现 `contract` 子命令，保持校验/导出行为与现有模块一致
- [x] T024 [US3] 在 `build.py` 中实现 `gen-web-api` 子命令，跨平台发现 npm/npx 并以参数列表调用
- [x] T025 [US3] 在 `build.py` 中实现 `verify-one --rule <rule_code>` 子命令，调用现有单规则重跑逻辑并透传可选任务/输入参数
- [x] T026 [US3] 更新 `README.md`、`docs/architecture.md` 中的契约、客户端生成和单规则调试命令

**检查点**：契约、客户端和单规则流程可通过 `build.py` 独立使用；OpenAPI 与生成客户端语义不变

---

## 阶段 6：用户故事 4 - 开发者通过统一入口启动前端与端到端流程（优先级：P3）

**目标**：开发者使用 `build.py` 启动在线服务、前端开发/构建和端到端检查。

**独立测试**：运行 `run`、`web-install`、`web-dev`、`web-build`、`e2e-install` 和 `e2e` 的注入测试与可用冒烟；确认 Node/npm 缺失或浏览器缺失时给出前置条件提示。

### 用户故事 4 的测试

- [x] T027 [P] [US4] 在 `tests/build/test_build_run.py` 中编写测试：`run` 复用 `.venv` 调用在线启动器；不自动绕过精确锁安装；Node/npm 缺失时提示前置条件
- [x] T028 [P] [US4] 在 `tests/build/test_build_frontend.py` 中编写测试：`web-install`、`web-dev`、`web-build`、`e2e-install` 和 `e2e` 的命令映射、工作目录、Windows npm/npx 发现和失败传播

### 用户故事 4 的实现

- [x] T029 [US4] 在 `build.py` 中实现 `run` 子命令，启动现有在线 API + Web 流程；`.venv` 缺失时提示先安装
- [x] T030 [US4] 在 `build.py` 中实现 `web-install`、`web-dev`、`web-build`、`e2e-install` 和 `e2e` 子命令，保持现有 npm/Playwright 行为
- [x] T031 [US4] 更新 `README.md` 和 `docs/architecture.md` 中的在线服务、前端开发/构建、端到端命令

**检查点**：在线、前端和端到端工作流均可由 `build.py` 独立发起；旧 Make 目标没有行为缺口

---

## 阶段 7：收尾与横切关注点

**目的**：删除旧入口、同步所有权威文档、完成等价性验证

- [x] T032 [P] 在 `tests/build/test_build_migration.py` 中编写迁移看护测试：断言根目录不存在 `Makefile`、`run-offline.sh`、`run-online.sh`、`uv.lock`，且活跃文档不推荐 `make` 或 uv
- [x] T033 删除 `Makefile`、`run-offline.sh`、`run-online.sh` 和 `uv.lock`
- [x] T034 更新 `.gitignore`：移除 `.uv/`、`.uv-cache/` 等 uv 专用忽略项，保留 `.venv/`
- [x] T035 删除 `requirements.txt`，更新 `Dockerfile` 使用 `requirements-lock.txt` 安装依赖，并保持现有 Python 3.12 slim 运行行为
- [x] T036 更新 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md` 中所有当前工作流和交付门禁命令为 `python build.py`；不改写历史 Speckit 产物
- [x] T037 [P] 更新 `app/contract/export.py` 模块说明，将旧 `make contract` 表述改为 `python build.py contract`
- [x] T038 在 `tests/build/test_build_parity.py` 中添加等价性测试：验证 `contract`、`gen-web-api`、`test`、`lint`、`verify`、`verify-one` 与旧工作流的目标命令和参数映射一致，且巡检输出契约不变
- [ ] T039 运行 `specs/008-python-build-tooling/quickstart.md` 的 Windows、macOS 和 Linux 验证清单；至少在三个平台验证安装、lint、test，并记录结果
- [x] T040 运行完整验证：`python build.py lint`、`python build.py test`、`python build.py contract`、`python build.py gen-web-api`、`python build.py web-build`、`python build.py verify`

---

## 执行记录

- 2026-09-14：已在 macOS 完成 `install`、`lint`、`test`、`contract`、`gen-web-api`、`web-install`、`web-build`、`verify` 验证。
- T039 保持未勾选：本次只完成 macOS 实测；Windows 和 Linux 人工验证仍未执行。

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：无依赖；T002 测试先于 T003 实现。
- **基础层（阶段 2）**：依赖阶段 1；阻塞所有用户故事。
- **US1（阶段 3）**：依赖基础层。
- **US2（阶段 4）**：依赖基础层；可与 US1 并行设计测试，但 `build.py` 实现建议顺序合并。
- **US3（阶段 5）**：依赖基础层；建议在 US1/US2 后实现以减少同文件冲突。
- **US4（阶段 6）**：依赖基础层；建议在 US1/US2/US3 后实现以减少同文件冲突。
- **收尾（阶段 7）**：依赖所有用户故事完成后执行，尤其是旧入口删除和文档迁移。

### 用户故事内部

1. 先编写并确认测试失败。
2. 再实现 `build.py` 子命令。
3. 最后更新该故事直接依赖的权威文档。
4. 每个检查点只验证当前故事，不要求提前实现后续故事。

### 并行机会

- T002、T004、T005 分属不同测试文件，可在基础实现前并行编写。
- T012、T013，T017，T021、T022，T027、T028 分别是不同测试文件，可在对应故事实现前并行编写。
- 文档更新若限定不同文件可并行：例如 T036 与 T037。
- `build.py` 的用户故事实现任务共享同一文件，必须顺序执行，不应分配给多个执行者并行修改。

---

## 实现策略

### MVP 优先（用户故事 1）

1. 完成阶段 1 和阶段 2。
2. 完成阶段 3 的安装与本地全流程。
3. 运行 US1 独立测试并确认基础流程可用。
4. 暂停评审后再进入质量门禁和前端工作流。

### 增量交付

1. 基础环境 + 精确锁可复现安装。
2. 本地全流程可用。
3. lint/test 质量门禁可用。
4. 契约、客户端和单规则调试可用。
5. 在线、前端和端到端命令可用。
6. 删除旧入口并完成迁移看护。

---

## 注意事项

- 所有新命令通过 `build.py` 暴露，不新增第二权威入口。
- 子进程必须使用参数列表执行，禁止 `shell=True`。
- 不修改巡检规则、执行编排、任务模型、结果契约或 OpenAPI 语义。
- 删除旧入口前，必须先完成对应新命令映射和测试。
- 历史文档与历史 Speckit 产物中的 `make`、uv 记录不改写。
