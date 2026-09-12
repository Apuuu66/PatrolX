"""契约化结果落盘与执行日志。"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.models.schemas import InspectionTask, RuleResult, RuleStatus, Summary, SystemInspection


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def task_dir(output: Path, task_id: str) -> Path:
    return output / task_id


def rule_path(output: Path, task_id: str, code: str) -> Path:
    return task_dir(output, task_id) / "rules" / f"{code}.json"


def append_log(output: Path, task_id: str, level: str, message: str, **detail) -> None:
    path = task_dir(output, task_id) / "execution.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": now_utc(), "level": level, "message": message, **detail}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _atomic_write_json(path: Path, data: object) -> None:
    """原子写 JSON，避免并发读者看到截断内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def save_rule_result(output: Path, task_id: str, result: RuleResult) -> None:
    _atomic_write_json(
        rule_path(output, task_id, result.code),
        result.model_dump(by_alias=True, mode="json"),
    )


def compute_summary(results: list[RuleResult]) -> Summary:
    counts = {s.value: 0 for s in RuleStatus}
    for r in results:
        counts[r.status.value] += 1
    return Summary(
        total=len(results),
        pass_=counts["pass"],
        warn=counts["warn"],
        fail=counts["fail"],
        error=counts["error"],
        skip=counts["skip"],
    )


def save_system(output: Path, task_id: str, system: SystemInspection) -> None:
    _atomic_write_json(task_dir(output, task_id) / "system.json", system.model_dump(by_alias=True, mode="json"))


def save_task_meta(output: Path, task: InspectionTask) -> None:
    _atomic_write_json(task_dir(output, task.task_id) / "task.json", task.model_dump(by_alias=True, mode="json"))


def load_task_meta(output: Path, task_id: str) -> InspectionTask | None:
    path = task_dir(output, task_id) / "task.json"
    if not path.exists():
        return None
    return InspectionTask.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_rule_result(output: Path, task_id: str, code: str) -> RuleResult | None:
    path = rule_path(output, task_id, code)
    if not path.exists():
        return None
    return RuleResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_system(output: Path, task_id: str) -> SystemInspection | None:
    path = task_dir(output, task_id) / "system.json"
    if not path.exists():
        return None
    return SystemInspection.model_validate(json.loads(path.read_text(encoding="utf-8")))
