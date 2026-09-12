"""全局概览 API 测试。"""

import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.inspectors.registry import registry
from app.main import app

client = TestClient(app)


def _finding(index: int) -> dict:
    return {
        "finding_id": f"f-{index}",
        "title": f"问题 {index}",
        "severity": "medium",
        "evidence": "evidence",
        "recommendation": "处理建议",
    }


def _rule(code: str, status: str, findings: list[dict]) -> dict:
    return {
        "code": code,
        "name": code,
        "category": "log",
        "priority": 0,
        "execution_order": 0,
        "status": status,
        "severity": "low",
        "summary": "summary",
        "metrics": [],
        "findings": findings,
        "metadata": {},
    }


def _task(task_id: str, stats: dict, rules: list[dict]) -> dict:
    summary = {key: stats[key] for key in ("total", "pass", "warn", "fail", "error", "skip")}
    return {
        "task_id": task_id,
        "name": task_id,
        "mode": "online",
        "status": "completed",
        "trigger": "api",
        "created_at": "2026-09-11T00:00:00Z",
        "completed_at": None,
        "stats": {**summary, "systems": 1},
        "system": {
            "package_file": f"{task_id}.zip",
            "package_checksum": None,
            "version": None,
            "status": "completed",
            "summary": summary,
            "rules": rules,
            "customer": {},
        },
    }


def test_overview_summary_counts_tasks_rules_results_and_findings() -> None:
    registry.load_all()
    output = settings.output
    output.mkdir(parents=True, exist_ok=True)

    task1 = _task(
        "task-overview-1",
        {"total": 3, "pass": 2, "warn": 0, "fail": 1, "error": 0, "skip": 0},
        [
            _rule("rule.a", "pass", [_finding(1), _finding(2)]),
            _rule("rule.b", "fail", []),
        ],
    )
    task2 = _task(
        "task-overview-2",
        {"total": 2, "pass": 0, "warn": 0, "fail": 0, "error": 0, "skip": 2},
        [_rule("rule.c", "skip", [_finding(3)])],
    )
    before = client.get("/api/v1/overview").json()
    for task in (task1, task2):
        task_dir = output / task["task_id"]
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")

    resp = client.get("/api/v1/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    expected_rules = registry.all(include_hidden=True)
    assert body["task_count"] == before["task_count"] + 2
    assert body["registered_rule_count"] == len(expected_rules)
    assert body["registered_rule_count"] > len(registry.all(include_hidden=False))
    assert body["rule_result_count"] == before["rule_result_count"] + 5
    assert body["finding_count"] == before["finding_count"] + 3
    assert body["status_counts"]["total"] == before["status_counts"]["total"] + 5
    assert body["status_counts"]["pass"] == before["status_counts"]["pass"] + 2
    assert body["status_counts"]["warn"] == before["status_counts"]["warn"]
    assert body["status_counts"]["fail"] == before["status_counts"]["fail"] + 1
    assert body["status_counts"]["error"] == before["status_counts"]["error"]
    assert body["status_counts"]["skip"] == before["status_counts"]["skip"] + 2
