# PatrolX 入口隔离机制

这篇文档整理本地调试、CLI 全流程和在线 API 三类入口的关系，重点说明它们为什么不会互相触发、如何共用巡检内核，以及当前仍需要注意的边界。

## 1. 结论先行

PatrolX 不是为“本地模式”和“在线模式”维护两套巡检实现，而是把系统拆成三层：

```text
入口层
  决定从哪里发现数据包、如何触发任务

执行层
  统一走 run_task / Executor / Inspector / store / report

数据层
  统一按 task_id 写入 output/<task_id>/
```

三类常用入口：

| 命令 | 输入目录 | 运行方式 | 任务触发 | 典型用途 |
| --- | --- | --- | --- | --- |
| `python main.py` | `local_run/` | 当前进程同步执行 | 直接调用 `run_task()` | 本地开发、临时调试 |
| `python -m app.cli run` | `uploads/` | 当前进程同步执行 | 直接调用 `run_task()` | 全流程验证、CLI 批量巡检 |
| `python build.py run` / `uvicorn app.main:app` | API 上传到 `uploads/<task_id>/` | FastAPI 服务 | `TaskService` 队列异步执行 | Web/API 在线使用 |

入口不同，但巡检内核和结果契约一致。

## 2. `main.py` 的双角色

`app/main.py` 同时承担两个职责：

- 被 `uvicorn` 导入时：作为 FastAPI 应用入口。
- 被 `python main.py` 直接执行时：作为本地调试入口。

关键代码：

```python
app = create_app()


def main() -> int:
    """本地调试入口：扫描 local_run/ 并逐个执行全部数据包。"""
    from app.local_run import run_local_packages

    return run_local_packages()


if __name__ == "__main__":
    raise SystemExit(main())
```

区别来自 Python 的标准入口判断：

- `uvicorn app.main:app` 只导入模块，创建 `app`，不会执行 `main()`。
- `python main.py` 会执行 `if __name__ == "__main__"`，进入 `main()`。

因此：

```bash
python main.py
```

只会触发 `local_run/` 扫描，不会触发在线 API 服务。

## 3. 本地调试入口

本地调试代码在 `app/local_run.py`：

```python
from app.cli import find_packages, run_task
from app.core.config import settings
from app.models.schemas import TaskMode, TaskTrigger


def run_local_packages() -> int:
    """运行 local_run/ 下所有压缩包；每个包仍是独立任务。"""
    packages = find_packages(settings.local_run)
    if not packages:
        print("未找到数据包：请将 zip/tar.gz 放入 local_run/ 目录")
        return 1

    for package in packages:
        run_task(package, mode=TaskMode.LOCAL, trigger=TaskTrigger.CLI)
    return 0
```

行为约定：

- 固定扫描 `local_run/` 顶层目录。
- 扫描到几个合法压缩包，就顺序执行几个。
- 不做“选择最新包”的隐式决策。
- 不使用 `uploads/`。
- 不需要命令行参数。
- 每个包仍然是一个独立任务。
- 原始压缩包只读。
- 输出统一写入 `output/<task_id>/`。

## 4. CLI 全流程入口

CLI 的包发现逻辑在 `app/cli.py`：

```python
def find_packages(root: Path | None = None) -> list[Path]:
    base = root if root is not None else settings.uploads
    base.mkdir(parents=True, exist_ok=True)
    return [p for p in sorted(base.iterdir()) if p.is_file() and is_archive(p)]
```

当不传 `root` 时，默认扫描：

```text
uploads/
```

CLI 主流程：

```python
packages = find_packages()

for pkg in packages:
    run_task(pkg, task_id=args.task_id)
```

`build.py verify` 现在显式映射到 CLI：

```python
return context.run([str(python), "-m", "app.cli", "run"], context.root)
```

因此：

```bash
python main.py          # local_run/
python build.py verify  # uploads/
```

两者的输入目录不同，语义也不同。

## 5. 在线 API 入口

在线模式入口是：

```bash
python build.py run
```

实际启动：

```bash
uvicorn app.main:app
```

上传接口的关键流程：

```python
task_id = generate_task_id(filename)

created = task_service.reserve(
    filename,
    name,
    province,
    operator,
    version,
    product=product,
)

task_dir = settings.uploads / created.task_id
task_dir.mkdir(parents=True, exist_ok=True)
shutil.copyfile(temp_path, task_dir / filename)

task_service.submit(created.task_id)
```

任务服务会写入 SQLite：

```python
TaskRecord(
    task_id=task_id,
    mode=TaskMode.ONLINE.value,
    status=TaskStatus.PENDING.value,
    trigger=TaskTrigger.API.value,
    package_file=package_file,
)
```

然后进入内存队列：

```python
def submit(self, task_id: str) -> None:
    self._queue.put(task_id)
```

worker 串行执行：

```python
def _worker_loop(self) -> None:
    while True:
        task_id = self._queue.get()
        ...
        with self._lock:
            self._execute(task_id)
```

`_execute()` 最终仍调用统一执行函数：

```python
executed = run_task(
    package,
    name=name,
    customer=customer,
    version=version,
    task_id=task_id,
    mode=mode,
    trigger=trigger,
)
```

## 6. 共用执行内核

虽然入口不同，但最后都落到同一个核心函数：

```python
run_task()
```

内部链路可以概括为：

```text
run_task()
→ registry.load_all()
→ Executor.run_all()
→ pkg.extract.main 安全解压
→ TaskFileCatalog 构建输入清单
→ prepare
→ inspector
→ store.save_rule_result()
→ render_report()
→ output/<task_id>/
```

这样设计的好处是：

- 本地、CLI、API 看到的结果契约一致。
- 规则只需要面向 `RuleContext` 和 `TaskFileCatalog` 编写。
- 不需要在每条规则里判断“我是在线还是本地”。
- Web、CLI、报告都消费同一份契约化输出。

## 7. 输入目录职责

当前目录职责：

```text
local_run/
└── 本地调试压缩包

uploads/
└── <task_id>/
    └── 原始上传压缩包

output/
└── <task_id>/
    ├── task.json
    ├── system.json
    ├── rules/
    ├── prepared/
    ├── logs/
    └── report.html
```

职责划分：

| 目录 | 语义 |
| --- | --- |
| `local_run/` | 开发者手工放入的本地调试输入 |
| `uploads/` | CLI 全流程验证和在线上传输入现场 |
| `output/` | 任务输出现场，按 `task_id` 隔离 |

注意：本地 `local_run/` 的包不会被移动或复制到 `uploads/`；本地模式直接读取原位置。

## 8. `task_id` 与任务隔离

任务 ID 由包名派生：

```python
def generate_task_id(package_name: str) -> str:
    """一个包名唯一派生一个任务 ID。"""
    return f"task-{clean_task_id(package_name)}"
```

示例：

```text
sample.zip → task-sample
```

输出目录：

```text
output/task-sample/
```

这个模型对应项目约束：

```text
一个数据包 = 一个任务 = 一个输出目录
```

## 9. 当前边界和注意事项

入口层面已经隔离，但仍有几个需要理解的边界。

### 9.1 同名包会派生同一个 `task_id`

如果存在：

```text
local_run/sample.zip
uploads/task-sample/sample.zip
```

它们会派生同一个：

```text
output/task-sample/
```

串行执行时会表现为复用或覆盖同一任务现场。并发执行时不要依赖这种行为。

### 9.2 `python main.py` 仍会加载 FastAPI 应用对象

当前 `app/main.py` 中：

```python
app = create_app()
```

在模块顶部执行。因此即使运行：

```bash
python main.py
```

进程也会加载 FastAPI 相关模块。

这不代表本地任务会进入在线队列；本地流程不会调用 `TaskService.submit()`。但严格来说，这不是“进程级零加载隔离”。

### 9.3 不要在 `create_app()` 里加入包扫描逻辑

`create_app()` 只应该负责 FastAPI 应用装配。

如果在这里扫描 `uploads/` 或 `local_run/`，会导致：

```bash
uvicorn app.main:app
```

启动服务时意外触发巡检任务。

### 9.4 本地入口不要隐式选择包

当前设计刻意不做“最新包”选择。

原因是这会引入隐式依赖：

- 依赖文件修改时间。
- 依赖目录状态。
- 依赖开发者的主观预期。

本地入口的规则应该是：

```text
local_run/ 里有什么合法压缩包，就执行什么。
```

## 10. 学习检查清单

理解这套机制时，可以对照以下问题：

1. `python main.py` 为什么不会启动在线巡检？
2. `uvicorn app.main:app` 为什么不会扫描 `local_run/`？
3. `python build.py verify` 为什么扫描 `uploads/`？
4. 本地任务和在线任务是否共用同一个执行内核？
5. `mode` 和 `trigger` 分别表示什么？
6. 为什么输出统一放在 `output/<task_id>/`？
7. 为什么 `create_app()` 里不能扫描数据包？
8. 同名包在 `local_run/` 和 `uploads/` 同时存在时有什么风险？

## 11. 相关代码

| 文件 | 作用 |
| --- | --- |
| `app/main.py` | FastAPI 应用入口与 `python main.py` 本地调试入口 |
| `app/local_run.py` | `local_run/` 本地调试运行逻辑 |
| `app/cli.py` | CLI 全流程、单规则重跑、任务 ID 生成 |
| `app/core/config.py` | 输入输出目录配置 |
| `app/services/tasks.py` | 在线任务队列、worker、状态更新 |
| `app/api/router.py` | 在线上传和任务 API |
