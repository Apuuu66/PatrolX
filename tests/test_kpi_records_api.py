"""KPI 原始记录查询 API 测试。"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.schemas import (
    InspectionTask,
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
)
from app.services.store import save_rule_result, save_system, save_task_meta

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
                "path": "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv",
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
        system = SystemInspection(
            package_file=f"{task_id}.zip",
            status="completed",
            summary=Summary(total=1, **{"pass": 0, "warn": 0, "fail": 1, "error": 0, "skip": 0}),
            rules=[rule],
        )
        save_system(settings.output, task_id, system)
        save_task_meta(
            settings.output,
            InspectionTask(
                task_id=task_id,
                name=task_id,
                mode="online",
                status="completed",
                trigger="api",
                created_at="2026-09-14T02:00:00Z",
                completed_at="2026-09-14T02:01:00Z",
                stats={"total": 1, "pass": 0, "warn": 0, "fail": 1, "error": 0, "skip": 0, "systems": 1},
                system=system,
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
        params={"source_file": "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv", "period_minutes": 5},
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
    metadata = _metadata()
    metadata["kpi_results"][0]["series"] = [
        {"start_at": f"2026-09-14T02:{index:02d}:00Z", "value": index} for index in range(501)
    ]
    metadata["kpi_results"][0]["provenance"] = {
        "formula": "call_success_count / call_attempts * 100",
        "direct_cross_reference": [
            {"source_file": "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv", "value": index}
            for index in range(501)
        ],
    }
    _save(task_id, "kpi.call", metadata, with_system=True)

    default = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call")
    assert default.status_code == 200
    assert len(default.json()["metadata"]["kpi_results"][0]["series"]) == 501
    assert default.json()["metadata"]["kpi_files"][0]["records"]

    excluded = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call", params={"exclude_records": "true"})
    assert excluded.status_code == 200
    assert excluded.json()["metadata"]["kpi_files"][0]["records"] == []
    assert excluded.json()["metadata"]["metric_catalog"]
    result = excluded.json()["metadata"]["kpi_results"][0]
    series = result["series"]
    assert len(series) <= 200
    assert series[0]["value"] == 0
    assert series[-1]["value"] == 500
    cross_reference = result["provenance"]["direct_cross_reference"]
    assert len(cross_reference) <= 200
    assert cross_reference[0]["value"] == 0
    assert cross_reference[-1]["value"] == 500


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


def test_kpi_records_rejects_invalid_pagination_and_status() -> None:
    task_id = "records-invalid-params"
    _save(task_id, "kpi.call", _metadata())

    invalid_queries: list[dict[str, object]] = [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 201},
        {"status": "unknown"},
    ]
    for params in invalid_queries:
        response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records", params=params)
        assert response.status_code == 422, (params, response.status_code, response.text)
        body = response.json()
        assert body["code"] == "validation_error", (params, body)
        assert body["message"], body
        assert body["detail"]["errors"], body


def test_kpi_records_treats_unknown_filters_as_empty_pages() -> None:
    task_id = "records-unknown-filters"
    _save(task_id, "kpi.call", _metadata())

    for params in (
        {"metric_key": "not_registered"},
        {"source_file": "kpi/not-found.csv"},
    ):
        response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records", params=params)
        assert response.status_code == 200, (params, response.text)
        assert response.json()["total"] == 0
        assert response.json()["items"] == []


def test_kpi_records_survives_malformed_metadata() -> None:
    task_id = "records-corrupt-metadata"
    metadata = _metadata()
    metadata["version"] = "not-a-number"
    metadata["kpi_files"] = {"unexpected": "shape"}
    _save(task_id, "kpi.call", metadata)

    response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


def test_kpi_records_skips_malformed_records() -> None:
    task_id = "records-corrupt-record"
    metadata = _metadata()
    metadata["kpi_files"] = [
        {
            "path": "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv",
            "domain": "call",
            "period_minutes": 5,
            "records": [
                {"line_number": "bad", "period_minutes": "bad", "values": "bad", "errors": []},
                metadata["kpi_files"][0]["records"][0],
            ],
        }
    ]
    _save(task_id, "kpi.call", metadata)

    response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records")
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 4
    assert [item["line_number"] for item in page["items"]] == [4, 4, 4, 4]


def test_kpi_records_survives_malformed_catalog_and_results() -> None:
    task_id = "records-corrupt-catalog"
    metadata = _metadata()
    metadata["metric_catalog"] = {"bad": "shape"}
    metadata["kpi_results"] = {"bad": "shape"}
    _save(task_id, "kpi.call", metadata)

    response = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


def test_system_summary_can_exclude_rule_details() -> None:
    task_id = "system-summary"
    _save(task_id, "kpi.call", _metadata(), with_system=True)

    default = client.get(f"/api/v2/tasks/{task_id}/system")
    assert default.status_code == 200
    assert default.json()["rules"][0]["metadata"]["kpi_files"]

    summarized = client.get(f"/api/v2/tasks/{task_id}/system", params={"exclude_details": "true"})
    assert summarized.status_code == 200
    rule = summarized.json()["rules"][0]
    assert rule["code"] == "kpi.call"
    assert rule["status"] == "fail"
    assert rule["metadata"] == {}
    assert rule["metrics"] == []
    assert rule["findings"] == []


def test_task_summary_excludes_rule_details() -> None:
    task_id = "task-summary"
    _save(task_id, "kpi.call", _metadata(), with_system=True)

    response = client.get(f"/api/v2/tasks/{task_id}")
    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "completed"
    assert task["stats"]["total"] == 1
    assert task["system"]["summary"]["total"] == 1
    rule = task["system"]["rules"][0]
    assert rule["code"] == "kpi.call"
    assert rule["status"] == "fail"
    assert rule["metadata"] == {}
    assert rule["metrics"] == []
    assert rule["findings"] == []
