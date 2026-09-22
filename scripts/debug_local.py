"""local_run 本地任务的解压与规则命中调试脚本。"""

import argparse
import json
from collections import Counter, defaultdict
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


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """提取 manifest 中的 source→target 映射，便于核对解压现场。"""
    entries: list[dict[str, Any]] = []
    sections = (
        ("files", "source"),
        ("subpackages", "source"),
        ("log_gz", "source_relative_path"),
    )
    for section, source_key in sections:
        for item in manifest.get(section, []):
            if not isinstance(item, dict):
                continue
            entries.append(
                {
                    "source": item.get(source_key) or item.get("source"),
                    "target": item.get("target"),
                    "category": item.get("category", "other"),
                    "status": item.get("status", "unknown"),
                }
            )
    for item in manifest.get("rejected", []):
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "source": item.get("source") or item.get("source_relative_path"),
                "target": item.get("target"),
                "category": item.get("category", "rejected"),
                "status": item.get("status", "rejected"),
            }
        )
    return entries


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
        "entries": _manifest_entries(manifest),
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


def _task_rules(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("code"): item for item in ((task.get("system") or {}).get("rules") or []) if item.get("code")}


def _rule_match(catalog: TaskFileCatalog, rule: Any, task_rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    patterns = list(rule.source_patterns or [])
    pattern_matches = {pattern: [path.as_posix() for path in catalog.match([pattern])] for pattern in patterns}
    result = task_rules.get(rule.code, {})
    return {
        "code": rule.code,
        "name": rule.name,
        "status": result.get("status"),
        "summary": result.get("summary"),
        "skip_reason": result.get("skip_reason"),
        "source_patterns": patterns,
        "pattern_matches": pattern_matches,
        "matched_files": [path.as_posix() for path in catalog.match(patterns)],
    }


def _rule_report(task_dir: Path, code: str, catalog: TaskFileCatalog | None = None) -> dict[str, Any]:
    registry.load_all()
    rule = registry.get(code)
    category = "logs" if rule.category == RuleCategory.LOG else rule.category.value
    catalog = catalog or TaskFileCatalog.build(task_dir)
    task = _load_json(task_dir / "task.json")
    match = _rule_match(catalog, rule, _task_rules(task))
    return {
        **match,
        "priority": rule.priority.value,
        "rule_version": rule.rule_version,
        "enabled": code in set(registry.codes()),
        "catalog_paths": [path.as_posix() for path in catalog.paths()],
        "manifest": _manifest_report(task_dir),
        "category": category,
    }


def _rule_matches(task_dir: Path, catalog: TaskFileCatalog) -> list[dict[str, Any]]:
    """为全部普通规则计算 source_patterns 命中明细。"""
    registry.load_all()
    task = _load_json(task_dir / "task.json")
    task_rules = _task_rules(task)
    return [_rule_match(catalog, rule, task_rules) for rule in registry.all()]


def build_report(task_dir: Path, task: dict[str, Any], *, rule_code: str | None = None) -> dict[str, Any]:
    """构造解压现场、实际文件清单和全部规则命中明细。"""
    catalog = TaskFileCatalog.build(task_dir)
    report: dict[str, Any] = {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "created_at": task.get("created_at"),
        "completed_at": task.get("completed_at"),
        "package_file": (task.get("system") or {}).get("package_file"),
        "attention_rules": _attention_rules(task),
        "manifest": _manifest_report(task_dir),
        "catalog_paths": [path.as_posix() for path in catalog.paths()],
        "rule_matches": _rule_matches(task_dir, catalog),
    }
    if rule_code is not None:
        rule_report = _rule_report(task_dir, rule_code, catalog)
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

    print("解压条目:")
    entries = manifest.get("entries") or []
    if not entries:
        print("  无")
    for entry in entries:
        target = entry.get("target") or "-"
        source = entry.get("source") or "-"
        print(f"  {entry.get('status', 'unknown')} {target} <- {source}")

    print("实际巡检目录:")
    catalog_paths = report.get("catalog_paths") or []
    if not catalog_paths:
        print("  无")
    for path in catalog_paths:
        print(f"  {path}")

    print("规则命中:")
    for match in report.get("rule_matches") or []:
        status = str(match.get("status") or "unknown").upper()
        matched = match.get("matched_files") or []
        print(f"  {status:5} {match['code']}: {len(matched)} 个文件")
        if not matched:
            print("    MISS")
        for path in matched:
            print(f"    HIT {path}")

    print("需关注规则:")
    if not report["attention_rules"]:
        print("  无")
    for rule in report["attention_rules"]:
        reason = rule.get("skip_reason") or rule.get("summary") or ""
        print(f"  {str(rule.get('status')).upper():5} {rule.get('code')} | {reason}")

    if "rule" not in report:
        return
    rule = report["rule"]
    print("\n选中规则匹配:")
    print(f"  code: {rule['code']}")
    for pattern, matches in rule["pattern_matches"].items():
        print(f"  pattern: {pattern}")
        if not matches:
            print("    MISS")
        for path in matches:
            print(f"    HIT  {path}")


def _tree_lines(paths: list[str]) -> list[str]:
    """按最终父目录分组展示实际巡检文件树；不读取 .main 证据现场。"""
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        parent = str(Path(path).parent)
        grouped[parent].append(path)

    lines: list[str] = []
    for directory in sorted(grouped):
        lines.append(f"{directory}/")
        lines.extend(f"  {Path(path).name}" for path in sorted(grouped[directory]))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="调试 local_run 任务的解压与规则命中")
    parser.add_argument("--task-id", help="任务 ID；默认选择最新的 local 任务")
    parser.add_argument("--rule", help="可选规则 code；输出该规则匹配明细")
    parser.add_argument("--tree", action="store_true", help="按父目录显示实际巡检文件树")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    task = select_task(settings.output, args.task_id)
    task_dir = Path(task["_task_dir"])
    report = build_report(task_dir, task, rule_code=args.rule)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
        if args.tree:
            print("\n巡检目录树:")
            lines = _tree_lines(report.get("catalog_paths") or [])
            print("\n".join(lines) if lines else "  无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
