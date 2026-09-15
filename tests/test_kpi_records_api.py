"""KPI 原始记录查询 API 测试。"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.schemas import (
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
)
from app.services.store import save_rule_result, save_system

client = TestClient(app)


def _rule(code: str, metadata: dict) -> RuleResult:
    return RuleResult(
        code=code,
        name=code,
        category=RuleCategory.KPI,
        priority=Priority.P1,
        execution_order=10,
        status=RuleStatus.FAIL,
        severity=Severity.MEDIUM,
        metadata=metadata,
    )


def _metadata() -> dict:
    return {
        "version": 2,
        "domain": "call",
        "metric_catalog": [
            {
                "key": "call_attempts",
                "name_zh": "呼叫请求次数",
                "name_en": "Call Attempts",
                "aliases": [{"language": "zh", "value": "呼叫请求次数"}],
                "metric_type": "count",
                "semantic_group": "traffic",
                "display_role": "context",
                "unit": "次",
                "source_type": "raw",
                "aggregation": {"kind": "sum"},
            },
            {
                "key": "call_success_count",
                "name_zh": "呼叫请求成功次数",
                "name_en": "Call Success Count",
                "aliases": [{"language": "zh", "value": "呼叫请求成功次数"}],
                "metric_type": "count",
                "semantic_group": "traffic",
                "display_role": "context",
                "unit": "次",
                "source_type": "raw",
                "aggregation": {"kind": "sum"},
            },
            {
                "key": "call_success_rate",
                "name_zh": "呼叫成功率",
                "name_en": "Call Success Rate",
                "aliases": [{"language": "zh", "value": "呼叫成功率"}],
                "metric_type": "rate",
                "semantic_group": "quality",
                "display_role": "highlight",
                "unit": "%",
                "source_type": "derived",
                "aggregation": {"kind": "ratio_from_inputs"},
                "formula": {
                    "kind": "ratio",
                    "numerator": "call_success_count",
                    "denominator": "call_attempts",
                    "scale": 100,
                },
            },
            {
                "key": "max_concurrency",
                "name_zh": "最大并发",
                "name_en": "Max Concurrency",
                "aliases": [{"language": "zh", "value": "最大并发"}],
                "metric_type": "capacity",
                "semantic_group": "capacity",
                "display_role": "context",
                "unit": "路",
                "source_type": "raw",
                "aggregation": {"kind": "max"},
            },
        ],
        "kpi_results": [
            {
                "key": "call_success_rate",
                "display_status": "fail",
                "threshold": {"direction": "min", "default": 99.0},
            }
        ],
        "unclassified_metrics": [],
        "kpi_files": [
            {
                "path": "kpi/kpi-call-5.csv",
                "domain": "call",
                "period_minutes": 5,
                "records": [
                    {
                        "line_number": 4,
                        "period_minutes": 5,
                        "start_at": "2026-09-14T02:00:00Z",
                        "end_at": "2026-09-14T02:05:00Z",
                        "values": {"呼叫请求次数": 100, "呼叫请求成功次数": 98, "最大并发": 20},
                        "errors": [],
                    },
                    {
                        "line_number": 5,
                        "period_minutes": 5,
                        "start_at": "2026-09-14T02:05:00Z",
                        "end_at": "2026-09-14T02:10:00Z",
                        "values": {"呼叫请求次数": 100, "呼叫请求成功次数": 100, "最大并发": 25},
                        "errors": [],
                    },
                ],
            }
        ],
    }


def _save(task_id: str, code: str, metadata: dict, *, with_system: bool = False) -> None:
    rule = _rule(code, metadata)
    save_rule_result(settings.output, task_id, rule)
    if with_system:
        save_system(
            settings.output,
            task_id,
            SystemInspection(
                package_file=f"{task_id}.zip",
                status="completed",
                summary=Summary(total=1, **{"pass": 0, "warn": 0, "fail": 1, "error": 0, "skip": 0}),
                rules=[rule],
            ),
        )


def test_kpi_records_filters_and_paginates() -> None:
    task_id = "records-filter"
    metadata = _metadata()
    metadata["kpi_results"][0]["threshold"] = {
        "direction": "min",
        "default": 99.0,
    }
    _save(task_id, "kpi.call", metadata)

    response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 8
    assert page["page_size"] == 50
    assert [item["metric_key"] for item in page["items"]] == [
        "call_attempts",
        "call_success_count",
        "call_success_rate",
        "max_concurrency",
        "call_attempts",
        "call_success_count",
        "call_success_rate",
        "max_concurrency",
    ]
    assert page["items"][0]["value"] == 100.0
    assert page["items"][2]["value"] == 98.0
    assert page["items"][2]["status"] == "fail"
    assert page["items"][3]["value"] == 20.0
    assert page["items"][3]["status"] == "neutral"

    filtered = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"metric_key": "call_success_rate", "status": "fail", "page_size": 1},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["line_number"] == 4

    source = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"source_file": "kpi/kpi-call-5.csv", "period_minutes": 5},
    )
    assert source.status_code == 200
    assert source.json()["total"] == 8

    no_source = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"source_file": "kpi/missing.csv"},
    )
    assert no_source.status_code == 200
    assert no_source.json()["total"] == 0

    paged = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"page": 2, "page_size": 3},
    )
    assert paged.status_code == 200
    assert paged.json()["page"] == 2
    assert paged.json()["page_size"] == 3
    assert len(paged.json()["items"]) == 3

    invalid = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"period_minutes": 7},
    )
    assert invalid.status_code == 422


def test_kpi_records_returns_empty_for_legacy_metadata() -> None:
    task_id = "records-legacy"
    _save(task_id, "kpi.call", {"version": 1, "kpi_files": [{"records": [{"line_number": 1}]}]})

    response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records")
    assert response.status_code == 200
    assert response.json() == {"total": 0, "page": 1, "page_size": 50, "items": []}


def test_rule_result_can_exclude_kpi_records() -> None:
    task_id = "records-exclude"
    _save(task_id, "kpi.call", _metadata(), with_system=True)

    default = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call")
    assert default.status_code == 200
    assert default.json()["metadata"]["kpi_files"][0]["records"]

    excluded = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call", params={"exclude_records": "true"})
    assert excluded.status_code == 200
    assert excluded.json()["metadata"]["kpi_files"][0]["records"] == []
    assert excluded.json()["metadata"]["metric_catalog"]


def test_kpi_records_returns_empty_for_non_kpi_metadata() -> None:
    task_id = "records-non-kpi"
    _save(task_id, "log.error_density", {"version": 2, "kpi_files": []})

    response = client.get(f"/api/v2/tasks/{task_id}/rules/log.error_density/kpi/records")
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


def test_kpi_records_missing_rule_returns_404() -> None:
    response = client.get("/api/v2/tasks/missing/rules/kpi.call/kpi/records")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
