"""KPI 资源指标库服务测试。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from app.inspectors.kpi.catalog import load_kpi_catalog
from app.services.kpi_resources import (
    KpiResourceError,
    classify_resource_metrics,
    import_resource_metrics,
    list_resource_metrics,
    load_resource_registry,
    read_resource_csv,
)


def _config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config" / "kpi"
    shutil.copytree(Path("deploy/config/kpi"), config_dir)
    return config_dir


def _resource_csv(tmp_path: Path, content: str | None = None) -> Path:
    path = tmp_path / "resource.csv"
    path.write_text(
        content
        or (
            "资源id,中文描述,英文描述\n"
            "UNIT_1,次,times\n"
            "ME_21002,创建媒体资源请求次数(次),Create Media Resource Request Count\n"
            "ME_21003,媒体成功率,对应英文\n"
        ),
        encoding="utf-8",
    )
    return path


def test_import_resource_csv_registers_unclassified_basic_metrics(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    csv_path = _resource_csv(tmp_path)

    rows = read_resource_csv(csv_path)
    report = import_resource_metrics(rows, config_dir=config_dir)
    registry = load_resource_registry(config_dir)

    assert set(registry.metrics) == {"me_21002", "me_21003"}
    metric = registry.metrics["me_21002"]
    assert metric.resource_id == "ME_21002"
    assert metric.name_zh == "创建媒体资源请求次数"
    assert metric.name_en == "Create Media Resource Request Count"
    assert metric.unit == "次"
    assert metric.metric_type == "count"
    assert metric.domain is None

    rate = registry.metrics["me_21003"]
    assert rate.name_en == "TODO: 媒体成功率"
    assert rate.metric_type == "rate"
    assert rate.unit == "%"
    assert rate.domain is None

    assert report["summary"]["row_count"] == 3
    assert report["summary"]["new_metrics"] == 2
    assert report["summary"]["updated_metrics"] == 0
    assert report["summary"]["skipped_units"] == 1
    assert report["summary"]["invalid_rows"] == 0
    assert report["summary"]["missing_registered"] == 0
    assert report["revision"] == registry.revision

    catalog = load_kpi_catalog(config_dir)
    for domain in ("call", "api", "media"):
        assert not (set(catalog.domains[domain].metrics) & {"me_21002", "me_21003"})


def test_reimport_is_idempotent_and_preserves_classification(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    first = import_resource_metrics(rows, config_dir=config_dir)
    classify_resource_metrics(
        ["me_21002"],
        domain="media",
        expected_revision=first["revision"],
        config_dir=config_dir,
    )

    second = import_resource_metrics(rows, config_dir=config_dir)
    registry = load_resource_registry(config_dir)

    assert second["summary"]["new_metrics"] == 0
    assert second["summary"]["updated_metrics"] == 2
    assert registry.revision == first["revision"] + 2
    assert registry.metrics["me_21002"].domain == "media"
    assert registry.metrics["me_21003"].domain is None

    catalog = load_kpi_catalog(config_dir)
    assert list(catalog.domains["media"].metrics) == ["me_21002"]


def test_import_reports_missing_registered_metrics_without_deleting(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    full_rows = read_resource_csv(_resource_csv(tmp_path))
    import_resource_metrics(full_rows, config_dir=config_dir)

    partial_csv = tmp_path / "partial.csv"
    partial_csv.write_text("资源id,中文描述,英文描述\nME_21002,创建媒体资源请求次数(次),times\n", encoding="utf-8")
    report = import_resource_metrics(read_resource_csv(partial_csv), config_dir=config_dir)

    assert report["summary"]["missing_registered"] == 1
    assert set(load_resource_registry(config_dir).metrics) == {"me_21002", "me_21003"}


def test_import_rejects_invalid_header_empty_file_and_duplicate_conflict(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)

    bad_header = tmp_path / "header.csv"
    bad_header.write_text("资源id,描述,英文描述\n", encoding="utf-8")
    with pytest.raises(KpiResourceError) as exc:
        import_resource_metrics(read_resource_csv(bad_header), config_dir=config_dir)
    assert exc.value.code == "invalid_resource_csv"

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(KpiResourceError) as exc:
        import_resource_metrics(read_resource_csv(empty), config_dir=config_dir)
    assert exc.value.code == "invalid_resource_csv"

    conflict = tmp_path / "conflict.csv"
    conflict.write_text(
        "资源id,中文描述,英文描述\nME_1,请求次数,count\nME_1,失败次数,failure count\n",
        encoding="utf-8",
    )
    with pytest.raises(KpiResourceError) as exc:
        import_resource_metrics(read_resource_csv(conflict), config_dir=config_dir)
    assert exc.value.code == "resource_id_conflict"
    assert not (config_dir / "resource_metrics.yaml").exists()


def test_import_reports_invalid_and_unsupported_rows(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_text(
        "资源id,中文描述,英文描述\n"
        "ME_,缺少资源编号,metric\n"
        "OTHER_1,其他资源,other\n"
        "ME_21002,,No Chinese\n"
        "ME_21003,请求次数(),empty unit\n"
        "ME_21004,请求次数(次),Request Count\n",
        encoding="utf-8",
    )

    report = import_resource_metrics(read_resource_csv(csv_path), config_dir=config_dir)
    reasons = {item["reason"] for item in report["invalid_rows"]}

    assert report["summary"]["new_metrics"] == 1
    assert report["summary"]["invalid_rows"] == 4
    assert reasons == {
        "invalid_resource_id",
        "unsupported_resource_id",
        "missing_name_zh",
        "empty_unit",
    }
    assert set(load_resource_registry(config_dir).metrics) == {"me_21004"}


def test_identical_duplicate_resource_rows_merge_once(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_text(
        "资源id,中文描述,英文描述\nME_1,请求次数,count\nME_1,请求次数,count\n",
        encoding="utf-8",
    )

    report = import_resource_metrics(read_resource_csv(csv_path), config_dir=config_dir)
    assert report["summary"]["new_metrics"] == 1
    assert set(load_resource_registry(config_dir).metrics) == {"me_1"}


def test_list_resource_metrics_searches_filters_and_paginates(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    report = import_resource_metrics(rows, config_dir=config_dir)
    classify_resource_metrics(["me_21002"], domain="api", expected_revision=report["revision"], config_dir=config_dir)

    page = list_resource_metrics(config_dir=config_dir, page=1, page_size=1)
    assert page["total"] == 2
    assert page["page_size"] == 1
    assert page["revision"] == report["revision"] + 1
    assert page["summary"] == {"unclassified": 1, "call": 0, "api": 1, "media": 0}

    by_domain = list_resource_metrics(config_dir=config_dir, domain="unclassified")
    assert [item["key"] for item in by_domain["items"]] == ["me_21003"]

    by_search = list_resource_metrics(config_dir=config_dir, search="Create Media")
    assert [item["key"] for item in by_search["items"]] == ["me_21002"]


def test_classification_writes_domain_and_reclassifies_unreferenced_metric(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    report = import_resource_metrics(rows, config_dir=config_dir)

    result = classify_resource_metrics(
        ["me_21002", "me_21003"],
        domain="media",
        expected_revision=report["revision"],
        config_dir=config_dir,
    )
    registry = load_resource_registry(config_dir)
    catalog = load_kpi_catalog(config_dir)

    assert result["metric_keys"] == ["me_21002", "me_21003"]
    assert all(metric.domain == "media" for metric in registry.metrics.values())
    assert set(catalog.domains["media"].metrics) == {"me_21002", "me_21003"}
    assert catalog.domains["media"].metrics["me_21002"].formula is None
    assert catalog.domains["media"].thresholds == {}

    result = classify_resource_metrics(
        ["me_21002"],
        domain="api",
        expected_revision=result["revision"],
        config_dir=config_dir,
    )
    registry = load_resource_registry(config_dir)
    catalog = load_kpi_catalog(config_dir)
    assert registry.metrics["me_21002"].domain == "api"
    assert set(catalog.domains["api"].metrics) == {"me_21002"}
    assert set(catalog.domains["media"].metrics) == {"me_21003"}


def test_classification_rejects_expired_revision_and_bad_request(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    report = import_resource_metrics(rows, config_dir=config_dir)

    with pytest.raises(KpiResourceError) as exc:
        classify_resource_metrics(["me_21002"], domain="media", expected_revision=0, config_dir=config_dir)
    assert exc.value.code == "resource_revision_conflict"

    with pytest.raises(KpiResourceError) as exc:
        classify_resource_metrics([], domain="media", expected_revision=report["revision"], config_dir=config_dir)
    assert exc.value.code == "bad_request"

    with pytest.raises(KpiResourceError) as exc:
        classify_resource_metrics(
            ["me_21002"], domain="other", expected_revision=report["revision"], config_dir=config_dir
        )
    assert exc.value.code == "bad_request"

    assert load_resource_registry(config_dir).revision == report["revision"]


def test_classification_batch_is_atomic_when_any_metric_is_missing(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    report = import_resource_metrics(rows, config_dir=config_dir)
    registry_path = config_dir / "resource_metrics.yaml"
    media_path = config_dir / "media.yaml"
    before = (registry_path.read_bytes(), media_path.read_bytes())

    with pytest.raises(KpiResourceError) as exc:
        classify_resource_metrics(
            ["me_21002", "missing"],
            domain="media",
            expected_revision=report["revision"],
            config_dir=config_dir,
        )
    assert exc.value.code == "resource_metric_not_found"
    assert (registry_path.read_bytes(), media_path.read_bytes()) == before


def test_classification_blocks_metric_referenced_by_formula_or_threshold(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    report = import_resource_metrics(rows, config_dir=config_dir)
    classify_resource_metrics(["me_21002"], domain="api", expected_revision=report["revision"], config_dir=config_dir)

    api_path = config_dir / "api.yaml"
    raw = yaml.safe_load(api_path.read_text(encoding="utf-8"))
    raw["metrics"].append(
        {
            "key": "me_21002_rate",
            "name_zh": "媒体请求成功率",
            "name_en": "Media Request Success Rate",
            "metric_type": "rate",
            "semantic_group": "quality",
            "display_role": "highlight",
            "unit": "%",
            "source_type": "derived",
            "aggregation": {"kind": "ratio_from_inputs"},
            "formula": {
                "kind": "ratio",
                "numerator": "me_21002",
                "denominator": "me_21002",
                "scale": 100,
            },
        }
    )
    raw["thresholds"]["me_21002"] = {
        "label": "媒体请求次数",
        "direction": "min",
        "unit": "次",
        "default": 1,
    }
    api_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    registry = load_resource_registry(config_dir)
    before = (api_path.read_bytes(), (config_dir / "media.yaml").read_bytes())
    with pytest.raises(KpiResourceError) as exc:
        classify_resource_metrics(
            ["me_21002"],
            domain="media",
            expected_revision=registry.revision,
            config_dir=config_dir,
        )
    assert exc.value.code == "resource_metric_referenced"
    assert (api_path.read_bytes(), (config_dir / "media.yaml").read_bytes()) == before


def test_classification_blocks_capacity_reference(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_text("资源id,中文描述,英文描述\nME_1,统计峰值(个),Stat Peak\n", encoding="utf-8")
    report = import_resource_metrics(read_resource_csv(csv_path), config_dir=config_dir)
    classify_resource_metrics(["me_1"], domain="api", expected_revision=report["revision"], config_dir=config_dir)

    api_path = config_dir / "api.yaml"
    raw = yaml.safe_load(api_path.read_text(encoding="utf-8"))
    raw["capacity_metrics"] = {"统计峰值": {"metric": "me_1", "semantics": "peak", "status": "confirmed"}}
    api_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(KpiResourceError) as exc:
        classify_resource_metrics(
            ["me_1"], domain="media", expected_revision=report["revision"] + 1, config_dir=config_dir
        )
    assert exc.value.code == "resource_metric_referenced"
    assert load_resource_registry(config_dir).metrics["me_1"].domain == "api"


def test_unknown_yaml_is_ignored_by_kpi_catalog(tmp_path: Path) -> None:
    config_dir = _config_dir(tmp_path)
    rows = read_resource_csv(_resource_csv(tmp_path))
    import_resource_metrics(rows, config_dir=config_dir)

    catalog = load_kpi_catalog(config_dir)
    assert set(catalog.domains) == {"call", "api", "media"}
