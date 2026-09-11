# Service-Aware Log Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 App Problem Scene 真实包结构实现服务/节点维度的日志过滤，并新增服务错误、故障模式、重复错误和堆栈异常四类日志规则。

**Architecture:** `log.filter` 作为 P0 规则，递归读取 `*.log` 与 `*.log.gz`，解析 `ServiceLog_*/<service>/logs/<node>/` 结构，生成规范化 JSONL、服务索引和兼容的 `filtered.log`。P1 日志规则只消费该产物，按服务聚合、识别已知故障模式、重复错误和异常堆栈。样例包同步改为完整 App Problem Scene 结构，保证本地全流程可验证。

**Tech Stack:** Python 3.12、gzip、regex、Pydantic v2、pytest、现有 Inspector/Executor/ArtifactStore。

**Spec:** `docs/example/real-package-structure.md` 与 `docs/example/zip.txt`。

## Global Constraints

- 真实服务日志结构为 `log/ServiceLog_*/<service>/logs/<node>/*.log` 与 `*.log.gz`。
- `ServiceLog_*` 不是服务名；服务名是其后业务目录，如 `AAAService`、`AppService`。
- 节点名是 `logs/` 后的目录，如 `paas-192.168.2.2`。
- 日志过滤必须流式读取 `.log.gz`，不额外解压落盘。
- 过滤默认保留 `WARN`、`WARNING`、`ERROR`、`FATAL`、`CRITICAL`，并保留 ERROR/FATAL 后的堆栈帧。
- 所有新日志分析规则均为 P1、`category=log`，输入均为 `log.filter.artifacts.filtered_logs`。
- 新增规则代码固定为 `log.service_errors`、`log.fault_pattern`、`log.repeat_error`、`log.stacktrace`。
- 修改 `log.filter` 时必须升级 `rule_version`，确保旧产物自动失效重跑。
- 所有日志规则的 `metadata.processed_files` 必须记录处理过的源文件名；每条日志规则执行时通过 `ctx.log` 打印这些文件；命中类规则还要把命中文件名写入对应 finding 的 `source_file`。
- 每个 task 结束运行对应测试；最终运行 `make lint`、`make test` 和完整本地流程。

---

### Task 1: Full App Problem Scene Sample Fixture

**Files:**

- Modify: `tests/fixtures/make_sample.py`
- Output: `tests/fixtures/sample/sample.zip`

**Interfaces:**

- Produces: 主包内告警、配置、KPI、资源、话统、嵌套日志子包六类真实布局。
- Produces: 嵌套包 `Service Logs (Problem)/ServiceLog_20260901011314.zip`。
- Produces: `AAAService` 与 `AppService` 的 `.log` 与 `.log.gz`。

- [x] **Step 1: Replace the simplified sample generator**

Rewrite `tests/fixtures/make_sample.py`:

```python
"""生成完整 App Problem Scene 样例包 tests/fixtures/sample/sample.zip。"""

import gzip
import io
import json
import zipfile
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"
OUTPUT = SAMPLE_DIR / "sample.zip"

BASE = "ZZapp01BCN_app_Problem_scene_333/333/app Problem scene"

FILES: dict[str, str] = {
    f"{BASE}/Alarm Information/alarm_history_202609010101137101.csv": (
        "alarm_id,created_time,cleared_time,alarm_code,severity,status,object,description\n"
        "1001,2026-09-01 10:00:01,,DB_CONNECTION_POOL_EXHAUSTED,CRITICAL,未处理,app-node-01,数据库连接池耗尽\n"
        "1002,2026-09-01 10:00:04,2026-09-01 10:00:30,SCTP_LINK_DOWN,HIGH,处理中,app-node-01,SCTP链路中断\n"
        "1003,2026-09-01 10:02:11,,CPU_USAGE_HIGH,MEDIUM,未处理,pod-app-1,CPU使用率偏高\n"
    ),
    f"{BASE}/Alarm Information/alarm_summary_202609010101137101.json": json.dumps({
        "scene_id": "333",
        "scene_name": "app Problem scene",
        "begin_time": "2026-09-01T10:00:00Z",
        "end_time": "2026-09-01T10:10:00Z",
        "total": 3,
        "unhandled": 2,
        "severity_distribution": {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1},
    }, ensure_ascii=False),
    f"{BASE}/Basic Information/system_info.ini": (
        "[app]\nname=app\nlog_level=INFO\n\n[system]\nnode_id=app-node-01\nregion=gd\ncollect_time=2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Basic Information/version.ini": (
        "[version]\nproduct=app\nrelease=R24.1\npatch=SP03\nbuild=20260901.01\n"
    ),
    f"{BASE}/KPI/kpi_202609010101137101.csv": (
        "metric,value,unit,timestamp\n"
        "call_success_rate,93.6,%,2026-09-01T10:00:00Z\n"
        "attach_success_rate,96.8,%,2026-09-01T10:00:00Z\n"
        "setup_success_rate,95.2,%,2026-09-01T10:00:00Z\n"
    ),
    f"{BASE}/Resource/pod_cpu_mem_202609010101137101.txt": (
        "pod-app-1 cpu 890m mem 768Mi\n"
        "pod-app-2 cpu 430m mem 1200Mi\n"
        "pod-aaa-1 cpu 210m mem 512Mi\n"
    ),
    f"{BASE}/Traffic/call_stat_202609010101137101.txt": (
        "total_calls 12345\nanswer_rate 93.8\n"
    ),
}

AAA_CURRENT = (
    "2026-09-01T10:05:00Z ERROR aaa auth failure count 1\n"
    "2026-09-01T10:05:01Z ERROR aaa auth failure count 2\n"
    "2026-09-01T10:05:02Z ERROR aaa auth failure count 3\n"
    "2026-09-01T10:05:03Z ERROR aaa auth failure count 4\n"
    "2026-09-01T10:05:04Z ERROR aaa auth failure count 5\n"
    "2026-09-01T10:05:05Z ERROR aaa auth failure count 6\n"
    "2026-09-01T10:05:06Z WARN  aaa retry timer exceeded\n"
)
AAA_HISTORY = "2026-09-01T10:06:00Z ERROR aaa history cached failure\n"
APP_CURRENT = (
    "2026-09-01T10:00:00Z INFO  app service started\n"
    "2026-09-01T10:00:01Z ERROR app db connection pool exhausted retry=1\n"
    "2026-09-01T10:00:02Z ERROR app db connection pool exhausted retry=2\n"
    "2026-09-01T10:00:03Z ERROR app db connection pool exhausted retry=3\n"
    "2026-09-01T10:00:04Z ERROR app db connection pool exhausted retry=4\n"
    "2026-09-01T10:00:05Z ERROR app db connection pool exhausted retry=5\n"
    "2026-09-01T10:00:06Z ERROR app db connection pool exhausted retry=6\n"
    "2026-09-01T10:00:07Z WARN  app retry timer exceeded\n"
)
APP_ERROR = (
    "2026-09-01T10:00:08Z ERROR app sctp link down\n"
    "2026-09-01T10:00:09Z ERROR app sctp reconnect failed\n"
    "        at com.patrolx.app.SctpClient.reconnect(SctpClient.java:122)\n"
    "java.net.SocketTimeoutException: sctp reconnect timed out\n"
    "2026-09-01T10:00:10Z INFO  app service stopped\n"
)
APP_HISTORY = "2026-09-01T10:07:00Z ERROR app history connection timeout\n"

SUB_PACKAGE = io.BytesIO()
with zipfile.ZipFile(SUB_PACKAGE, "w") as zf:
    zf.writestr("AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log", AAA_CURRENT)
    zf.writestr(
        "AAAService/logs/paas-192.168.2.2/aaa_service_history_20260901011314.log.gz",
        gzip.compress(AAA_HISTORY.encode("utf-8")),
    )
    zf.writestr("AppService/logs/paas-192.168.2.2/app_service_20260901011314.log", APP_CURRENT)
    zf.writestr("AppService/logs/paas-192.168.2.2/app_service_error_20260901011314.log", APP_ERROR)
    zf.writestr(
        "AppService/logs/paas-192.168.2.2/app_service_history_20260901011314.log.gz",
        gzip.compress(APP_HISTORY.encode("utf-8")),
    )


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
        zf.writestr(f"{BASE}/Service Logs (Problem)/ServiceLog_20260901011314.zip", SUB_PACKAGE.getvalue())
    print(f"已生成样例包: {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Regenerate fixture**

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python tests/fixtures/make_sample.py
```

Expected: `tests/fixtures/sample/sample.zip` regenerated successfully.

- [x] **Step 3: Verify fixture classification in a temporary output**

```bash
rm -rf /tmp/patrolx-fixture-verify
PATROLX_PACKAGE_DIR=tests/fixtures/sample PATROLX_OUTPUT_DIR=/tmp/patrolx-fixture-verify make verify
find /tmp/patrolx-fixture-verify -maxdepth 5 -type f | sort
```

Expected: 能看到 `alarm/`、`config/`、`kpi/`、`resource/`、`traffic/`、`log/ServiceLog_20260901011314/AAAService/`、`log/ServiceLog_20260901011314/AppService/`。

- [x] **Step 4: Commit**

```bash
git add tests/fixtures/make_sample.py tests/fixtures/sample/sample.zip
git commit -m "test(fixture): add full App Problem Scene sample"
```

---

### Task 2: ServiceLog-Aware `log.filter`

**Files:**

- Modify: `app/inspectors/log/filter.py`
- Test: `tests/test_rules.py`

**Interfaces:**

- Consumes: `pkg.extract.log.ready`。
- Produces: `log.filter.artifacts.filtered_logs/{filtered.log,filtered.jsonl,index.json}`。
- Produces: JSONL record keys `service,node,source_file,line_no,timestamp,level,message`。
- Produces: `index.json.services[service]`，包含 `nodes,files,total_lines,kept_lines,levels,error_count,warn_count`。

- [x] **Step 1: Write failing tests**

Append to `tests/test_rules.py`:

```python
import json


def test_log_filter_builds_service_index_for_service_log_layout(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:00Z INFO  app service started\n"
        "2026-09-01T10:00:01Z ERROR app db connection pool exhausted\n"
        "        at com.patrolx.app.DbPool.acquire(DbPool.java:88)\n"
    )
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 3\n"
    ctx = _ctx(tmp_path, {
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": app,
        "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log.gz": aaa,
    })

    result = _run_rule("log.filter", ctx)
    root = Path(ctx.artifacts.get("log.filter.artifacts.filtered_logs").path)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))

    assert result.status == RuleStatus.PASS
    assert result.metadata["service_count"] == 2
    assert set(index["services"]) == {"AAAService", "AppService"}
    assert index["services"]["AppService"]["error_count"] == 1
    assert index["services"]["AppService"]["nodes"] == {"paas-192.168.2.2": 2}
    assert index["services"]["AAAService"]["error_count"] == 1
    records = [json.loads(line) for line in (root / "filtered.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {record["service"] for record in records} == {"AAAService", "AppService"}
    app_records = [record for record in records if record["service"] == "AppService"]
    assert [record["level"] for record in app_records] == ["ERROR", "STACK"]
    assert app_records[0]["node"] == "paas-192.168.2.2"
    assert "DbPool.acquire" in app_records[1]["message"]


def test_log_filter_keeps_python_traceback_after_error(tmp_path: Path) -> None:
    plain = (
        "2026-09-01T10:06:00Z ERROR app worker failed\n"
        "Traceback (most recent call last):\n"
        '  File "/opt/app/worker.py", line 42, in run\n'
        "    call_remote()\n"
        "ConnectionError: remote unavailable\n"
    )
    ctx = _ctx(tmp_path, {
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_error_20260901011314.log": plain,
    })

    result = _run_rule("log.filter", ctx)
    root = Path(ctx.artifacts.get("log.filter.artifacts.filtered_logs").path)
    records = [json.loads(line) for line in (root / "filtered.jsonl").read_text(encoding="utf-8").splitlines()]

    assert result.status == RuleStatus.PASS
    assert [record["level"] for record in records] == ["ERROR", "STACK", "STACK", "STACK"]
```

- [x] **Step 2: Run tests and confirm failure**

```bash
make test
```

Expected: 新用例失败，因为 `filtered.jsonl`、`service`、`node`、`services` 和 `STACK` 行为不存在。

- [x] **Step 3: Implement service/node filtering**

Modify `app/inspectors/log/filter.py`. Upgrade `rule_version` to `2.0.0`, set `inputs=["pkg.extract.log.ready"]`, and implement:

```python
import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}
MIN_LEVEL = 30
STACK_LEVEL = "STACK"
LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?)\s+"
    r"(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+(?P<message>.*)$"
)
STACK_LINE_RE = re.compile(
    r"^(\s*at\s+|\s*Caused by:|Traceback \(most recent call last\):|\s*File \"|Exception:|Error:)"
)
```

File discovery and service/node extraction:

```python
def _is_log_file(path: Path) -> bool:
    lower = path.name.lower()
    return lower.endswith(".log") or lower.endswith(".log.gz")


def _file_service_name(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".log.gz"):
        return path.name[:-7]
    if lower.endswith(".log"):
        return path.name[:-4]
    return path.stem


def _service_node_of(logs_dir: Path, path: Path) -> tuple[str, str]:
    parts = list(path.relative_to(logs_dir).parts[:-1])
    if parts and re.match(r"(?i)^servicelog[_-]", parts[0]):
        parts = parts[1:]
    parts = [part for part in parts if part.lower() not in {"log", "logs"}]
    if not parts:
        return _file_service_name(path), ""
    return parts[0], "/".join(parts[1:])


def _read_lines(path: Path):
    if path.name.lower().endswith(".log.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
    else:
        with path.open("rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
```

Parsing and stack retention:

```python
@dataclass(slots=True)
class ParsedLine:
    timestamp: str | None
    level: str | None
    message: str


def _parse_line(raw: str) -> ParsedLine:
    match = LOG_LINE_RE.match(raw.rstrip("\r\n"))
    if not match:
        return ParsedLine(None, None, raw.rstrip("\r\n"))
    return ParsedLine(match.group("timestamp"), match.group("level"), match.group("message"))


def _process_file(ctx, logs_dir, path, out_log, out_jsonl) -> tuple[str, str, dict]:
    service, node = _service_node_of(logs_dir, path)
    source_file = str(path.relative_to(ctx.data_dir))
    records = []
    total = 0
    in_stack = False

    for line_no, raw in enumerate(_read_lines(path), start=1):
        total += 1
        parsed = _parse_line(raw)
        if parsed.level:
            in_stack = LEVELS[parsed.level] >= 40
            if LEVELS[parsed.level] < MIN_LEVEL:
                continue
            record = {
                "service": service,
                "node": node,
                "source_file": source_file,
                "line_no": line_no,
                "timestamp": parsed.timestamp,
                "level": parsed.level,
                "message": raw.rstrip("\r\n"),
            }
        elif in_stack and STACK_LINE_RE.match(raw):
            record = {
                "service": service,
                "node": node,
                "source_file": source_file,
                "line_no": line_no,
                "timestamp": None,
                "level": STACK_LEVEL,
                "message": raw.rstrip("\r\n"),
            }
        else:
            in_stack = False
            continue

        records.append(record)
        out_jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_log.write(record["message"] + "\n")

    counts = Counter(record["level"] for record in records)
    return service, node, {
        "files": [{
            "service": service,
            "node": node,
            "source_file": source_file,
            "total_lines": total,
            "kept_lines": len(records),
        }],
        "total_lines": total,
        "kept_lines": len(records),
        "levels": dict(counts),
        "error_count": counts["ERROR"] + counts["FATAL"] + counts["CRITICAL"],
        "warn_count": counts["WARN"] + counts["WARNING"],
    }
```

Run and build a merged index:

```python
def _merge_service(target: dict, source: dict, node: str) -> None:
    target.setdefault("nodes", {})
    target["nodes"][node] = target["nodes"].get(node, 0) + source["kept_lines"]
    target.setdefault("files", []).extend(source["files"])
    for key in ("total_lines", "kept_lines", "error_count", "warn_count"):
        target[key] = target.get(key, 0) + source[key]
    target.setdefault("levels", {})
    for level, count in source["levels"].items():
        target["levels"][level] = target["levels"].get(level, 0) + count


def _run(ctx: RuleContext) -> object:
    logs_dir = ctx.data_dir / RuleCategory.LOG.value
    files = [path for path in sorted(logs_dir.rglob("*")) if path.is_file() and _is_log_file(path)]
    if not files:
        return make_result(inspector, status=RuleStatus.SKIP, summary="未发现日志类文件", skip_reason="未发现日志类文件")

    out_root = ctx.rule_artifact_path(inspector.code, inspector.outputs_artifacts[0])
    out_root.mkdir(parents=True, exist_ok=True)
    services = {}
    total_lines = kept_lines = 0

    with (out_root / "filtered.log").open("w", encoding="utf-8") as out_log, \
         (out_root / "filtered.jsonl").open("w", encoding="utf-8") as out_jsonl:
        for path in files:
            try:
                service, node, result = _process_file(ctx, logs_dir, path, out_log, out_jsonl)
            except (OSError, gzip.BadGzipFile):
                continue
            _merge_service(services.setdefault(service, {}), result, node)
            total_lines += result["total_lines"]
            kept_lines += result["kept_lines"]

    index = {
        "files": [item for service in services.values() for item in service["files"]],
        "services": services,
        "service_count": len(services),
        "total_lines": total_lines,
        "kept_lines": kept_lines,
        "levels": {
            level: sum(service["levels"].get(level, 0) for service in services.values())
            for level in sorted({key for service in services.values() for key in service["levels"]})
        },
        "error_count": sum(service["error_count"] for service in services.values()),
        "warn_count": sum(service["warn_count"] for service in services.values()),
    }
    (out_root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=f"日志过滤完成：{len(services)} 个服务，{len(files)} 个文件，保留 {kept_lines}/{total_lines} 行",
        metadata={"files": len(files), "service_count": len(services), "kept_lines": kept_lines, "total_lines": total_lines},
    )


inspector.run = _run
registry.register(inspector)
```

- [x] **Step 4: Run focused tests**

```bash
make test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add app/inspectors/log/filter.py tests/test_rules.py
git commit -m "feat(log): add ServiceLog service-aware filtering"
```

---

### Task 3: Service Error Concentration Rule

**Files:**

- Create: `app/inspectors/log/service_errors.py`
- Test: `tests/test_rules.py`

**Interfaces:**

- Consumes: `filtered.jsonl`。
- Produces: rule code `log.service_errors`。
- Produces metrics: `service_count`（个）、`error_service_count`（个）、`max_service_error_count`（条）。

- [x] **Step 1: Write failing test**

Append to `tests/test_rules.py`:

```python
def _load_filter_artifact(ctx) -> None:
    artifact = ctx.artifacts.get("log.filter.artifacts.filtered_logs")
    ctx.inputs[artifact.key] = artifact


def test_service_errors_warn_on_hot_service(tmp_path: Path) -> None:
    lines = [f"2026-09-01T10:00:{second:02d}Z ERROR app db connection pool exhausted retry={second}" for second in range(1, 7)]
    plain = "\n".join(lines) + "\n"
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 1\n"
    ctx = _ctx(tmp_path, {
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": plain,
        "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log": aaa,
    })
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.service_errors", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[0].value == 2
    assert result.metrics[2].value == 6
    assert result.findings[0].title.startswith("AppService 服务错误集中")
```

- [x] **Step 2: Run test and confirm failure**

```bash
make test
```

Expected: FAIL with `规则未注册: log.service_errors`。

- [x] **Step 3: Implement `log.service_errors`**

Create `app/inspectors/log/service_errors.py`:

```python
"""log.service_errors（P1）：按服务聚合错误，识别错误集中服务。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

WARN_SERVICE_ERRORS = 5
FAIL_SERVICE_ERRORS = 20

inspector = Inspector(
    code="log.service_errors",
    name="服务日志错误集中度",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="按服务聚合 ERROR/FATAL/CRITICAL 日志，识别错误最集中的服务",
    recommendation="优先排查错误最集中的服务及其数据库、网络和下游依赖",
    inputs=["log.filter.artifacts.filtered_logs"],
    outputs_metrics=[
        {"key": "service_count", "label": "服务数量", "unit": "个"},
        {"key": "error_service_count", "label": "存在错误的服务数", "unit": "个"},
        {"key": "max_service_error_count", "label": "单服务最大错误数", "unit": "条"},
    ],
)


def _artifact_path(ctx: RuleContext) -> Path | None:
    artifact = ctx.inputs.get("log.filter.artifacts.filtered_logs")
    if artifact is None:
        return None
    path = Path(artifact.path) / "filtered.jsonl"
    return path if path.exists() else None


def _run(ctx: RuleContext) -> object:
    path = _artifact_path(ctx)
    if path is None:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="依赖过滤产物缺失",
            skip_reason="依赖产物 log.filter.artifacts.filtered_logs 缺失或缺少 filtered.jsonl",
        )

    services: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            record = json.loads(raw)
            service = services.setdefault(record["service"], {"errors": 0, "levels": {}, "first": record})
            level = record["level"]
            service["levels"][level] = service["levels"].get(level, 0) + 1
            if level in ("ERROR", "FATAL", "CRITICAL"):
                service["errors"] += 1

    max_service = max(services, key=lambda name: (services[name]["errors"], name))
    max_count = services[max_service]["errors"]
    error_service_count = sum(item["errors"] > 0 for item in services.values())

    if max_count > FAIL_SERVICE_ERRORS:
        status, summary = RuleStatus.FAIL, f"服务错误严重集中：{max_service} {max_count} 条"
    elif max_count >= WARN_SERVICE_ERRORS:
        status, summary = RuleStatus.WARN, f"服务错误集中：{max_service} {max_count} 条"
    else:
        status, summary = RuleStatus.PASS, f"服务错误分布正常：共 {len(services)} 个服务"

    findings = []
    if status != RuleStatus.PASS:
        first = services[max_service]["first"]
        findings = [Finding(
            finding_id=f"{inspector.code}-f001",
            title=f"{max_service} 服务错误集中",
            severity=Severity.MEDIUM,
            source_file=first["source_file"],
            evidence=first["message"],
            recommendation=inspector.recommendation,
        )]

    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "service_count", "label": "服务数量", "value": len(services), "unit": "个"},
            {"key": "error_service_count", "label": "存在错误的服务数", "value": error_service_count, "unit": "个"},
            {"key": "max_service_error_count", "label": "单服务最大错误数", "value": max_count, "unit": "条"},
        ],
        findings=findings,
        metadata={
            "service_error_counts": {name: item["errors"] for name, item in services.items()},
            "service_level_counts": {name: item["levels"] for name, item in services.items()},
            "hot_service": max_service,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
```

- [x] **Step 4: Run focused tests**

```bash
make test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add app/inspectors/log/service_errors.py tests/test_rules.py
git commit -m "feat(log): add service error concentration rule"
```

---

### Task 4: Known Fault Pattern Rule

**Files:**

- Create: `app/inspectors/log/fault_pattern.py`
- Test: `tests/test_rules.py`

**Interfaces:**

- Consumes: `filtered.jsonl`。
- Produces: rule code `log.fault_pattern`。
- Produces metrics: `matched_pattern_count`（类）、`affected_service_count`（个）、`max_pattern_hit_count`（条）。

- [x] **Step 1: Write failing test**

Append to `tests/test_rules.py`:

```python
def test_fault_pattern_matches_real_operational_cases(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:01Z ERROR app db connection pool exhausted retry=1\n"
        "2026-09-01T10:00:02Z ERROR app db connection pool exhausted retry=2\n"
        "2026-09-01T10:00:03Z ERROR app sctp link down\n"
        "2026-09-01T10:00:04Z ERROR app sctp reconnect failed\n"
    )
    aaa = "2026-09-01T10:05:00Z ERROR aaa auth failure count 1\n"
    ctx = _ctx(tmp_path, {
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": app,
        "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log": aaa,
    })
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.fault_pattern", ctx)

    assert result.status == RuleStatus.FAIL
    assert result.metrics[0].value == 4
    assert result.metrics[1].value == 2
    assert result.metadata["pattern_counts"]["db_connection_pool_exhausted"] == 2
    assert result.findings[0].title.startswith("AppService 数据库连接池耗尽")
```

- [x] **Step 2: Run test and confirm failure**

```bash
make test
```

Expected: FAIL with `规则未注册: log.fault_pattern`。

- [x] **Step 3: Implement `log.fault_pattern`**

Create `app/inspectors/log/fault_pattern.py`:

```python
"""log.fault_pattern（P1）：识别日志中的已知业务故障模式。"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

PATTERNS = [
    {
        "key": "db_connection_pool_exhausted",
        "name": "数据库连接池耗尽",
        "pattern": re.compile(r"db connection pool exhausted", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查数据库连接池配置、连接泄漏和数据库负载",
    },
    {
        "key": "auth_failure",
        "name": "认证失败",
        "pattern": re.compile(r"auth failure|authentication failed", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查认证服务、账号状态、证书/密码和限流策略",
    },
    {
        "key": "sctp_link_down",
        "name": "SCTP 链路中断",
        "pattern": re.compile(r"sctp link down", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查 SCTP 对端状态、网络连通性和链路配置",
    },
    {
        "key": "sctp_reconnect_failed",
        "name": "SCTP 重连失败",
        "pattern": re.compile(r"sctp reconnect failed", re.I),
        "severity": Severity.HIGH,
        "recommendation": "确认对端是否恢复，检查网络隔离、地址端口和重连参数",
    },
    {
        "key": "dependency_timeout",
        "name": "依赖连接超时",
        "pattern": re.compile(r"connection timeout|connect timed out|read timed out", re.I),
        "severity": Severity.MEDIUM,
        "recommendation": "检查下游服务时延、网络抖动、超时和重试配置",
    },
    {
        "key": "out_of_memory",
        "name": "内存耗尽",
        "pattern": re.compile(r"OutOfMemoryError|out of memory", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查内存水位、堆配置、业务内存增长和泄漏迹象",
    },
]

inspector = Inspector(
    code="log.fault_pattern",
    name="日志故障模式识别",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="将日志消息匹配到数据库连接池、认证失败、SCTP 链路、依赖超时和内存耗尽等已知故障模式",
    recommendation="按命中的故障模式查看证据、受影响服务，并执行对应处置建议",
    inputs=["log.filter.artifacts.filtered_logs"],
    outputs_metrics=[
        {"key": "matched_pattern_count", "label": "命中故障模式数", "unit": "类"},
        {"key": "affected_service_count", "label": "受影响服务数", "unit": "个"},
        {"key": "max_pattern_hit_count", "label": "单模式最大命中数", "unit": "条"},
    ],
)


def _artifact_path(ctx: RuleContext) -> Path | None:
    artifact = ctx.inputs.get("log.filter.artifacts.filtered_logs")
    if artifact is None:
        return None
    path = Path(artifact.path) / "filtered.jsonl"
    return path if path.exists() else None


def _run(ctx: RuleContext) -> object:
    path = _artifact_path(ctx)
    if path is None:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="依赖过滤产物缺失",
            skip_reason="依赖产物 log.filter.artifacts.filtered_logs 缺失或缺少 filtered.jsonl",
        )

    groups: dict[tuple[str, str], dict] = {}
    pattern_counts: Counter[str] = Counter()
    service_counts: Counter[str] = Counter()

    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            record = json.loads(raw)
            for pattern in PATTERNS:
                if not pattern["pattern"].search(record["message"]):
                    continue
                key = (record["service"], pattern["key"])
                pattern_counts[pattern["key"]] += 1
                service_counts[record["service"]] += 1
                group = groups.setdefault(key, {"pattern": pattern, "records": []})
                if len(group["records"]) < 5:
                    group["records"].append(record)

    high_pattern_count = sum(
        1 for pattern in PATTERNS
        if pattern["severity"] == Severity.HIGH and pattern_counts[pattern["key"]] > 0
    )
    max_count = max(pattern_counts.values(), default=0)

    if high_pattern_count >= 2 or max_count > 10:
        status = RuleStatus.FAIL
    elif pattern_counts:
        status = RuleStatus.WARN
    else:
        status = RuleStatus.PASS

    findings = []
    for (service, pattern_key), group in sorted(groups.items()):
        pattern = group["pattern"]
        first = group["records"][0]
        findings.append(Finding(
            finding_id=f"{inspector.code}-{service}-{pattern_key}".lower(),
            title=f"{service} {pattern['name']}",
            severity=pattern["severity"],
            source_file=first["source_file"],
            evidence="\n".join(record["message"] for record in group["records"])[:4096],
            recommendation=pattern["recommendation"],
        ))

    summary = "未命中已知故障模式" if not pattern_counts else f"命中 {len(pattern_counts)} 类故障模式，影响 {len(service_counts)} 个服务"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "matched_pattern_count", "label": "命中故障模式数", "value": len(pattern_counts), "unit": "类"},
            {"key": "affected_service_count", "label": "受影响服务数", "value": len(service_counts), "unit": "个"},
            {"key": "max_pattern_hit_count", "label": "单模式最大命中数", "value": max_count, "unit": "条"},
        ],
        findings=findings,
        metadata={
            "pattern_counts": dict(pattern_counts),
            "service_counts": dict(service_counts),
            "high_pattern_count": high_pattern_count,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
```

- [x] **Step 4: Run focused tests**

```bash
make test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add app/inspectors/log/fault_pattern.py tests/test_rules.py
git commit -m "feat(log): add known fault pattern inspection"
```

---

### Task 5: Repeated Error Rule

**Files:**

- Create: `app/inspectors/log/repeat_error.py`
- Test: `tests/test_rules.py`

**Interfaces:**

- Consumes: `filtered.jsonl`。
- Produces: rule code `log.repeat_error`。
- Produces metrics: `repeated_pattern_count`（个）、`max_repeat_count`（次）。

- [x] **Step 1: Write failing test**

Append to `tests/test_rules.py`:

```python
def test_repeat_error_detects_database_pool_storm(tmp_path: Path) -> None:
    lines = [f"2026-09-01T10:00:{second:02d}Z ERROR app db connection pool exhausted id={second}" for second in range(1, 9)]
    ctx = _ctx(tmp_path, {
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log": "\n".join(lines) + "\n",
    })
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.repeat_error", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[1].value == 8
    assert result.findings[0].title.startswith("AppService 重复错误：")
```

- [x] **Step 2: Run test and confirm failure**

```bash
make test
```

Expected: FAIL with `规则未注册: log.repeat_error`。

- [x] **Step 3: Implement `log.repeat_error`**

Create `app/inspectors/log/repeat_error.py`:

```python
"""log.repeat_error（P1）：识别服务日志中的高频重复错误。"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

WARN_REPEAT = 5
FAIL_REPEAT = 20
NORMALIZE_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\d+",
    re.I,
)

inspector = Inspector(
    code="log.repeat_error",
    name="高频重复错误识别",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="按服务归一化错误消息，识别连接池耗尽、认证失败、重试风暴等重复错误",
    recommendation="检查重复错误的触发频率、外部依赖可用性、重试与限流配置",
    inputs=["log.filter.artifacts.filtered_logs"],
    outputs_metrics=[
        {"key": "repeated_pattern_count", "label": "重复错误模式数", "unit": "个"},
        {"key": "max_repeat_count", "label": "最大重复次数", "unit": "次"},
    ],
)


def _artifact_path(ctx: RuleContext) -> Path | None:
    artifact = ctx.inputs.get("log.filter.artifacts.filtered_logs")
    if artifact is None:
        return None
    path = Path(artifact.path) / "filtered.jsonl"
    return path if path.exists() else None


def _normalized_message(message: str) -> str:
    return NORMALIZE_RE.sub("<var>", message).strip().lower()


def _run(ctx: RuleContext) -> object:
    path = _artifact_path(ctx)
    if path is None:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="依赖过滤产物缺失",
            skip_reason="依赖产物 log.filter.artifacts.filtered_logs 缺失或缺少 filtered.jsonl",
        )

    counts: Counter[tuple[str, str]] = Counter()
    groups: dict[tuple[str, str], dict] = {}

    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            record = json.loads(raw)
            if record["level"] == "STACK":
                continue
            normalized = _normalized_message(record["message"])
            key = (record["service"], normalized)
            counts[key] += 1
            group = groups.setdefault(key, {"first": record, "evidence": []})
            if len(group["evidence"]) < 5:
                group["evidence"].append(record["message"])

    repeated = {key: count for key, count in counts.items() if count >= WARN_REPEAT}
    max_count = max(repeated.values(), default=0)
    status = RuleStatus.FAIL if max_count > FAIL_REPEAT else RuleStatus.WARN if repeated else RuleStatus.PASS

    findings = []
    for (service, normalized), count in sorted(repeated.items(), key=lambda item: (-item[1], item[0])):
        group = groups[(service, normalized)]
        findings.append(Finding(
            finding_id=f"{inspector.code}-{service}-{len(findings) + 1:03d}".lower(),
            title=f"{service} 重复错误：{normalized[:120]}",
            severity=Severity.HIGH if count > FAIL_REPEAT else Severity.MEDIUM,
            source_file=group["first"]["source_file"],
            evidence="\n".join(group["evidence"])[:4096],
            recommendation=inspector.recommendation,
        ))

    summary = f"发现 {len(repeated)} 个高频重复错误，最大重复 {max_count} 次" if repeated else "未发现高频重复错误"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "repeated_pattern_count", "label": "重复错误模式数", "value": len(repeated), "unit": "个"},
            {"key": "max_repeat_count", "label": "最大重复次数", "value": max_count, "unit": "次"},
        ],
        findings=findings,
        metadata={
            "thresholds": {"warn": WARN_REPEAT, "fail": FAIL_REPEAT},
            "top_patterns": {
                f"{service}:{normalized}": count
                for (service, normalized), count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
                if count >= WARN_REPEAT
            },
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
```

- [x] **Step 4: Run focused tests**

```bash
make test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add app/inspectors/log/repeat_error.py tests/test_rules.py
git commit -m "feat(log): add repeated error inspection"
```

---

### Task 6: Stack Trace Rule

**Files:**

- Create: `app/inspectors/log/stacktrace.py`
- Test: `tests/test_rules.py`

**Interfaces:**

- Consumes: `filtered.jsonl`。
- Produces: rule code `log.stacktrace`。
- Produces metrics: `stacktrace_count`（个）、`exception_type_count`（类）。

- [x] **Step 1: Write failing test**

Append to `tests/test_rules.py`:

```python
def test_stacktrace_groups_by_service_and_type(tmp_path: Path) -> None:
    app = (
        "2026-09-01T10:00:01Z ERROR app request failed\n"
        "        at com.patrolx.app.Service.run(Service.java:31)\n"
        "java.lang.NullPointerException: service unavailable\n"
    )
    aaa = (
        "2026-09-01T10:05:00Z ERROR aaa worker failed\n"
        "Traceback (most recent call last):\n"
        "OutOfMemoryError: Java heap space\n"
    )
    ctx = _ctx(tmp_path, {
        "log/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_error_20260901011314.log": app,
        "log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_error_20260901011314.log": aaa,
    })
    _run_rule("log.filter", ctx)
    _load_filter_artifact(ctx)

    result = _run_rule("log.stacktrace", ctx)

    assert result.status == RuleStatus.WARN
    assert result.metrics[0].value == 2
    assert result.metrics[1].value == 2
    assert result.metadata["top_service"] == "AppService"
```

- [x] **Step 2: Run test and confirm failure**

```bash
make test
```

Expected: FAIL with `规则未注册: log.stacktrace`。

- [x] **Step 3: Implement `log.stacktrace`**

Create `app/inspectors/log/stacktrace.py`:

```python
"""log.stacktrace（P1）：识别服务日志中的异常类型与堆栈。"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

EXCEPTION_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9_]*(?:Exception|Error)|OutOfMemoryError|StackOverflowError)\b"
)

inspector = Inspector(
    code="log.stacktrace",
    name="日志堆栈异常识别",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="从过滤后的日志中识别异常类型和堆栈，并按服务与异常类型聚合",
    recommendation="根据异常类型定位代码路径，优先处理出现最早且重复最多的异常",
    inputs=["log.filter.artifacts.filtered_logs"],
    outputs_metrics=[
        {"key": "stacktrace_count", "label": "堆栈/异常条数", "unit": "个"},
        {"key": "exception_type_count", "label": "异常类型数", "unit": "类"},
    ],
)


def _artifact_path(ctx: RuleContext) -> Path | None:
    artifact = ctx.inputs.get("log.filter.artifacts.filtered_logs")
    if artifact is None:
        return None
    path = Path(artifact.path) / "filtered.jsonl"
    return path if path.exists() else None


def _run(ctx: RuleContext) -> object:
    path = _artifact_path(ctx)
    if path is None:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="依赖过滤产物缺失",
            skip_reason="依赖产物 log.filter.artifacts.filtered_logs 缺失或缺少 filtered.jsonl",
        )

    service_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    groups: dict[tuple[str, str], dict] = {}
    stack_frame_count = 0

    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            record = json.loads(raw)
            if record["level"] == "STACK":
                stack_frame_count += 1
            matches = EXCEPTION_RE.findall(record["message"])
            if not matches and record["level"] != "STACK":
                continue
            for exception_type in matches:
                key = (record["service"], exception_type)
                service_counts[record["service"]] += 1
                type_counts[exception_type] += 1
                group = groups.setdefault(key, {"records": []})
                if len(group["records"]) < 5:
                    group["records"].append(record)

    if not type_counts:
        return make_result(
            inspector,
            status=RuleStatus.PASS,
            summary="未发现异常堆栈",
            metrics=[
                {"key": "stacktrace_count", "label": "堆栈/异常条数", "value": stack_frame_count, "unit": "个"},
                {"key": "exception_type_count", "label": "异常类型数", "value": 0, "unit": "类"},
            ],
        )

    top_service = service_counts.most_common(1)[0][0]
    total_occurrences = sum(type_counts.values())
    status = RuleStatus.FAIL if total_occurrences > 5 else RuleStatus.WARN

    findings = []
    for (service, exception_type), group in sorted(groups.items()):
        first = group["records"][0]
        findings.append(Finding(
            finding_id=f"{inspector.code}-{service}-{exception_type}".lower().replace("_", "-"),
            title=f"{service} 出现 {exception_type}",
            severity=Severity.HIGH if total_occurrences > 5 else Severity.MEDIUM,
            source_file=first["source_file"],
            evidence="\n".join(record["message"] for record in group["records"])[:4096],
            recommendation=inspector.recommendation,
        ))

    return make_result(
        inspector,
        status=status,
        summary=f"发现 {len(type_counts)} 类异常，共 {total_occurrences} 次；最集中服务为 {top_service}",
        metrics=[
            {"key": "stacktrace_count", "label": "堆栈/异常条数", "value": total_occurrences, "unit": "个"},
            {"key": "exception_type_count", "label": "异常类型数", "value": len(type_counts), "unit": "类"},
        ],
        findings=findings,
        metadata={
            "service_counts": dict(service_counts),
            "exception_type_counts": dict(type_counts),
            "stack_frame_count": stack_frame_count,
            "top_service": top_service,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
```

- [x] **Step 4: Run focused tests**

```bash
make test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add app/inspectors/log/stacktrace.py tests/test_rules.py
git commit -m "feat(log): add service stack trace inspection"
```

---

### Task 7: Full Pipeline Verification

**Files:**

- Read: `output/task-sample/sample/rules/*.json`
- Read: `output/task-zzapp01bcn_app_problem_scene_333/zzapp01bcn_app_problem_scene_333/rules/*.json`
- Read: `output/task-sample/report.html`
- Modify only if verification exposes a defect.

**Interfaces:**

- Consumes: all prior rules, the full App Problem Scene fixture, and the real uploaded package.
- Produces: verified local full-flow output.

- [x] **Step 1: Regenerate and run the fixture package**

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python tests/fixtures/make_sample.py
PATROLX_PACKAGE_DIR=tests/fixtures/sample make verify
```

Expected: 全流程完成；输出包含 `log.filter`、`log.service_errors`、`log.fault_pattern`、`log.repeat_error`、`log.stacktrace`。

- [x] **Step 2: Run the real uploaded package**

```bash
PATROLX_PACKAGE_DIR=uploads make verify
```

Expected: 真实包的嵌套 `ServiceLog_20260901011314.zip` 只解压一次，`AAAService` 和 `AppService` 日志全部被扫描。

- [x] **Step 3: Inspect generated rule contracts**

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

for base in (
    Path('output/task-sample/sample/rules'),
    Path('output/task-zzapp01bcn_app_problem_scene_333/zzapp01bcn_app_problem_scene_333/rules'),
):
    print('BASE', base)
    for code in ('log.filter', 'log.service_errors', 'log.fault_pattern', 'log.repeat_error', 'log.stacktrace'):
        result = json.loads((base / f'{code}.json').read_text(encoding='utf-8'))
        print(code, result['status'], result['summary'])
PY
```

Expected: `log.filter=PASS`；新增规则至少一条为 `WARN` 或 `FAIL`，发现中包含 `AAAService` / `AppService` 和真实源文件路径。

- [x] **Step 4: Check reports**

Open:

```text
output/task-sample/report.html
output/task-zzapp01bcn_app_problem_scene_333/report.html
```

Expected: 报告展示新增规则、指标和发现。

- [x] **Step 5: Final verification and commit**

```bash
make lint
make test
git status --short
git add app tests
git commit -m "feat(log): verify service-aware offline inspection flow"
```

Expected: lint、tests 和 git status 无未预期变更。
