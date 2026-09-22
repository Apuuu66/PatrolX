"""local_run 本地任务的解压与规则匹配调试脚本。"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.inspectors.registry import registry
from app.models.schemas import RuleCategory
from app.services import extraction
from app.services.scanning import TaskFileCatalog

ATTENTION_STATUSES = {"warn", "fail", "error", "skip"}
MANIFEST_NAME = ".patrolx-extracted.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def find_local_tasks(output_dir: Path | None = None) -> list[dict[str, Any]]:
    """读取全部 local 模式任务元数据，按完成时间排序。"""
    root = output_dir or settings.output
    tasks: list[dict[str, Any]] = []
    for task_file in root.glob("*/task.json"):
        task = _load_json(task_file)
        if task.get("mode") != "local":
            continue
        task["_task_dir"] = task_file.parent
        tasks.append(task)
    return sorted(tasks, key=lambda item: str(item.get("completed_at") or item.get("task_id") or ""))


def select_task(output_dir: Path | None = None, task_id: str | None = None) -> dict[str, Any]:
    """选择指定任务或最新 local 任务。"""
    tasks = find_local_tasks(output_dir)
    if task_id is not None:
        for task in tasks:
            if task.get("task_id") == task_id:
                return task
        raise SystemExit(f"未找到 local 任务: {task_id}")
    if not tasks:
        raise SystemExit("未找到 local 任务：请先通过 local_run/ 执行任务")
    return tasks[-1]


def _status_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(item.get("status", "unknown")) for item in entries)
    return dict(sorted(counter.items()))


def _manifest_report(task_dir: Path) -> dict[str, Any]:
    manifest = extraction.read_manifest(task_dir)
    grouped: dict[str, list[dict[str, Any]]] = {
        category: [] for category in ("logs", "kpi", "traffic", "alarm", "config", "resource", "other")
    }
    for key in ("files", "subpackages", "log_gz"):
        for item in manifest.get(key, []):
            category = str(item.get("category", "other"))
            grouped.setdefault(category, []).append(item)
    return {
        "version": manifest.get("version"),
        "main": manifest.get("main"),
        "categories": {category: _status_counts(items) for category, items in sorted(grouped.items())},
        "failures": {category: extraction.category_failures(manifest, category) for category in sorted(grouped)},
        "policy_skipped": {
            category: extraction.policy_skipped_summary(manifest, category) for category in sorted(grouped)
        },
    }


def _attention_rules(task: dict[str, Any]) -> list[dict[str, Any]]:
    rules = (task.get("system") or {}).get("rules") or []
    return [
        {
            "code": rule.get("code"),
            "status": rule.get("status"),
            "summary": rule.get("summary"),
            "skip_reason": rule.get("skip_reason"),
        }
        for rule in rules
        if rule.get("status") in ATTENTION_STATUSES
    ]


def _rule_report(task_dir: Path, code: str) -> dict[str, Any]:
    registry.load_all()
    rule = registry.get(code)
    category = "logs" if rule.category == RuleCategory.LOG else rule.category.value
    catalog = TaskFileCatalog.build(task_dir)
    pattern_matches = {
        pattern: [path.as_posix() for path in catalog.match([pattern])] for pattern in (rule.source_patterns or [])
    }
    return {
        "code": rule.code,
        "name": rule.name,
        "priority": rule.priority.value,
        "rule_version": rule.rule_version,
        "enabled": code in set(registry.codes()),
        "source_patterns": list(rule.source_patterns or []),
        "pattern_matches": pattern_matches,
        "matched_files": [path.as_posix() for path in catalog.match(rule.source_patterns or [])],
        "catalog_paths": [path.as_posix() for path in catalog.paths()],
        "manifest": _manifest_report(task_dir),
        "category": category,
    }


def build_report(task_dir: Path, task: dict[str, Any], *, rule_code: str | None = None) -> dict[str, Any]:
    """构造任务概览或规则匹配诊断报告。"""
    report: dict[str, Any] = {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "created_at": task.get("created_at"),
        "completed_at": task.get("completed_at"),
        "package_file": (task.get("system") or {}).get("package_file"),
        "attention_rules": _attention_rules(task),
        "manifest": _manifest_report(task_dir),
    }
    if rule_code is not None:
        rule_report = _rule_report(task_dir, rule_code)
        report.update(
            {
                key: rule_report[key]
                for key in (
                    "source_patterns",
                    "pattern_matches",
                    "matched_files",
                    "catalog_paths",
                    "category",
                )
            }
        )
        report["rule"] = rule_report
    return report


def _print_human(report: dict[str, Any]) -> None:
    print(f"任务: {report['task_id']} | 状态: {report['status']} | 包: {report['package_file']}")
    manifest = report["manifest"]
    main = manifest.get("main") or {}
    print(f"解压: version={manifest.get('version')} count={main.get('count', 0)} reused={main.get('reused', False)}")
    for category, statuses in manifest["categories"].items():
        if statuses:
            print(f"  {category}: {statuses}")

    print("需关注规则:")
    if not report["attention_rules"]:
        print("  无")
    for rule in report["attention_rules"]:
        reason = rule.get("skip_reason") or rule.get("summary") or ""
        print(f"  {str(rule.get('status')).upper():5} {rule.get('code')} | {reason}")

    if "rule" not in report:
        return
    rule = report["rule"]
    print("\n规则匹配:")
    print(f"  code: {rule['code']}")
    for pattern, matches in rule["pattern_matches"].items():
        print(f"  pattern: {pattern}")
        for path in matches:
            print(f"    HIT  {path}")
        if not matches:
            print("    MISS")
    print("  matched_files:")
    if not rule["matched_files"]:
        print("    无")
    for path in rule["matched_files"]:
        print(f"    {path}")
    print("  catalog_paths:")
    if not rule["catalog_paths"]:
        print("    无")
    for path in rule["catalog_paths"]:
        print(f"    {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="调试 local_run 任务的解压与规则匹配")
    parser.add_argument("--task-id", help="任务 ID；默认选择最新的 local 任务")
    parser.add_argument("--rule", help="可选规则 code；输出该规则匹配明细")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    task = select_task(settings.output, args.task_id)
    task_dir = Path(task["_task_dir"])
    report = build_report(task_dir, task, rule_code=args.rule)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
