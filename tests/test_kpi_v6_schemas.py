"""041 v6 Pydantic Schema 与 OpenAPI 契约守卫。"""

from __future__ import annotations

import importlib
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml"
MODULE_NAME = "app.models.kpi_v6"

_OBJECT_SCHEMAS = {
    "KpiFocusIdentity",
    "KpiTeamFocusItemV6",
    "KpiTeamFocusPageV6",
    "KpiTeamFocusPatchRequestV6",
    "KpiTeamFocusPatchResponseV6",
    "KpiMeasurementUnitV6",
    "KpiMeasurementUnitPageV6",
    "KpiMeasurementInspectionPatchV6",
    "KpiMeasurementBindingV6",
    "KpiMeasurementBindingPageV6",
    "KpiMeasurementBindingPatchV6",
    "KpiLegacyRecoveryAuditV6",
    "KpiLegacyRecoveryAuditPageV6",
    "KpiLegacyRecoveryRetryRequestV6",
    "KpiPendingAttributionV6",
    "KpiPendingAttributionPageV6",
    "KpiPendingAttributionResolveRequestV6",
    "KpiMaintenanceOperationAcceptedV6",
    "KpiMaintenanceOperationItemV6",
    "KpiMaintenanceOperationV6",
    "KpiRuleNetworkAssignmentV6",
    "KpiRuleNetworkAssignmentPageV6",
    "KpiRuleAssignmentPatchRequestV6",
    "KpiRuleAssignmentWriteResultV6",
    "KpiRuleAssignmentBatchItemV6",
    "KpiRuleAssignmentBatchRequestV6",
    "KpiRuleAssignmentBatchResponseV6",
    "KpiRuleAssignmentAuditV6",
    "KpiRuleAssignmentAuditPageV6",
    "KpiRuleScopeStatusV6",
    "KpiSummaryCountsV6",
    "KpiNeedsAttentionGroupSummary",
    "KpiTaskSummaryV6",
    "KpiMetricResultV6",
    "KpiAppliedFiltersV6",
    "KpiMetricResultPageV6",
    "KpiThresholdEvidenceV6",
    "KpiDailyBucketV6",
    "KpiEvidenceComponentV6",
    "KpiEvidenceGroupV6",
    "KpiMetricEvidenceV6",
    "KpiHistoryPointV6",
    "KpiVersionComparisonV6",
    "KpiTechnicalAnalysisV6",
}

_ENUM_SCHEMAS = {
    "FocusAvailability",
    "FocusAvailabilityReason",
    "KpiConfigurationState",
    "KpiRecoveryState",
    "KpiBindingState",
    "KpiRecoveryResult",
    "KpiRecoveryObjectKind",
    "KpiRecoverySource",
    "KpiPendingResolutionState",
    "KpiPendingReason",
    "KpiRuleAssignmentState",
    "KpiRuleAssignmentAuditResult",
    "KpiRuleAssignmentAuditSource",
    "KpiResultView",
    "NeedsAttentionGroup",
    "CurrentHealthStatus",
    "TrendHealthStatus",
    "MetricRole",
    "MetricAvailability",
    "MetricSpecialState",
    "Importance",
}


@cache
def _contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _v6_module() -> Any:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        pytest.fail(f"缺少 v6 Schema 模块：{exc}")


def test_v6_schema_module_exposes_every_planned_object_and_enum() -> None:
    module = _v6_module()
    missing = sorted(name for name in _OBJECT_SCHEMAS | _ENUM_SCHEMAS if not hasattr(module, name))
    assert missing == []


@pytest.mark.parametrize("schema_name", sorted(_OBJECT_SCHEMAS))
def test_v6_object_fields_match_openapi(schema_name: str) -> None:
    module = _v6_module()
    schema = _contract()["components"]["schemas"][schema_name]
    model = getattr(module, schema_name)

    assert set(model.model_fields) == set(schema.get("properties", {}))
    required = {name for name, field in model.model_fields.items() if field.is_required()}
    assert required == set(schema.get("required", []))


@pytest.mark.parametrize("schema_name", sorted(_ENUM_SCHEMAS))
def test_v6_enum_values_match_openapi(schema_name: str) -> None:
    module = _v6_module()
    schema = _contract()["components"]["schemas"][schema_name]
    enum_type = getattr(module, schema_name)

    assert [item.value for item in enum_type] == schema["enum"]


def test_team_focus_patch_is_atomic_non_empty_and_disjoint() -> None:
    module = _v6_module()
    request_type = module.KpiTeamFocusPatchRequestV6
    item = {"measurement_unit_id": "mu-1", "metric_resource_id": "m-1"}

    with pytest.raises(ValidationError):
        request_type(task_id="task-1", expected_revision=0, add=[], remove=[])
    with pytest.raises(ValidationError):
        request_type(task_id="task-1", expected_revision=0, add=[item], remove=[item])
    with pytest.raises(ValidationError):
        request_type(task_id="task-1", expected_revision=0, add=[item, item], remove=[])

    request_type(task_id="task-1", expected_revision=0, add=[item], remove=[])
    request_type(task_id="task-1", expected_revision=0, add=[], remove=[item])


def test_rule_assignment_requires_explicit_last_unassign_confirmation() -> None:
    module = _v6_module()
    request_type = module.KpiRuleAssignmentPatchRequestV6

    with pytest.raises(ValidationError):
        request_type(expected_revision=3, network_element_types=[])
    request_type(expected_revision=3, network_element_types=[], confirm_unassign=True)
    request_type(expected_revision=3, network_element_types=["UMF"])
    with pytest.raises(ValidationError):
        request_type(expected_revision=3, network_element_types=["UMF", "UMF"])


def test_source_success_rate_evidence_remains_base_without_formula() -> None:
    module = _v6_module()
    evidence = module.KpiMetricEvidenceV6(
        task_id="task-1",
        network_element_type="UMF",
        measurement_unit_id="mu-media",
        metric_resource_id="metric-success-rate",
        metric={
            "name": "Media Resource Creation Success Rate(%)",
            "role": "base",
            "is_percentage": True,
            "formula": None,
            "daily_aggregation": "latest",
            "current_status": "normal",
            "trend_status": "stable",
        },
        current={
            "date": "2026-11-04",
            "value": 64.5,
            "numerator": None,
            "denominator": None,
            "valid_count": 1,
            "status": "ok",
        },
        previous={
            "date": "2026-11-03",
            "value": 65.2,
            "numerator": 130,
            "denominator": 199,
            "valid_count": 1,
            "status": "ok",
        },
        current_threshold={
            "direction": "higher_better",
            "warning_threshold": 90,
            "critical_threshold": 80,
            "source": "custom",
        },
        groups=[
            {
                "object_key": "__all__",
                "period_minutes": 1440,
                "today": {
                    "date": "2026-11-04",
                    "value": 64.5,
                    "numerator": 129,
                    "denominator": 200,
                    "valid_count": 1,
                    "status": "ok",
                },
                "yesterday": {
                    "date": "2026-11-03",
                    "value": 65.2,
                    "numerator": 130,
                    "denominator": 199,
                    "valid_count": 1,
                    "status": "ok",
                },
                "current_status": "normal",
                "trend_status": "stable",
                "source_files": ["media-rate.csv"],
            }
        ],
        seven_day_trend=[
            {
                "date": "2026-11-04",
                "value": 64.5,
                "numerator": 129,
                "denominator": 200,
                "valid_count": 1,
                "status": "ok",
            }
        ],
        components=[
            {
                "metric_resource_id": "metric-success",
                "name": "成功响应数",
                "role": "numerator",
                "value": 129,
            }
        ],
        sources=[],
    )

    assert evidence.metric.role.value == "base"
    assert evidence.metric.is_percentage is True
    assert evidence.metric.formula is None
    assert evidence.current.numerator is None
    assert evidence.current.denominator is None
    assert evidence.previous is not None
    assert evidence.previous.numerator is None
    assert evidence.previous.denominator is None
    assert evidence.groups[0].today is not None
    assert evidence.groups[0].today.numerator is None
    assert evidence.groups[0].today.denominator is None
    assert evidence.groups[0].yesterday is not None
    assert evidence.groups[0].yesterday.numerator is None
    assert evidence.groups[0].yesterday.denominator is None
    assert evidence.seven_day_trend[0].numerator is None
    assert evidence.seven_day_trend[0].denominator is None
    assert evidence.components == []
