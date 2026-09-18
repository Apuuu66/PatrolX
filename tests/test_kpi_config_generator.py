from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.inspectors.kpi.catalog import load_kpi_catalog
from app.services.kpi_resources import load_resource_registry


def _load_tool():
    path = Path(__file__).parents[1] / "tools" / "generate_kpi_config.py"
    spec = importlib.util.spec_from_file_location("generate_kpi_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _draft_by_name(metrics: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(item for item in metrics if item["name_zh"] == name)


def _write_config(config_dir: Path) -> None:
    source = Path(__file__).parents[1] / "deploy" / "config" / "kpi"
    shutil.copytree(source, config_dir)


def _write_csv(root: Path) -> None:
    content = """设备类型：XXX
测量单元名称：API统计
服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),api请求次数,api请求成功次数,api请求失败次数,api请求成功率,api请求失败率,api响应时延,api在线数
API,node-1,可信,,2026-08-15 00:00:00,2026-08-15 00:05:00,5,100,98,2,98.0,2.0,20,10
API,node-1,可信,,2026-08-15 00:05:00,2026-08-15 00:10:00,5,120,118,2,98.3,1.7,30,12
"""
    (root / "kpi").mkdir(parents=True)
    (root / "kpi" / "kpi-api-5.csv").write_text(content, encoding="utf-8")


def _by_name(metrics: list[dict[str, Any]], name: str) -> dict[str, Any]:
    match = next(item for item in metrics if item["source_name"] == name)
    return match


def test_scan_generates_new_metrics_and_ratio_formula(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    input_dir = tmp_path / "input"
    _write_config(config_dir)
    _write_csv(input_dir)

    report = tool.scan_kpi_csv(input_dir, config_dir=config_dir)

    assert report["summary"]["domains"] == ["api"]
    assert report["summary"]["csv_files"] == 1
    assert report["domains"]["api"]["registered_metrics"] == []
    assert report["domains"]["api"]["invalid_metrics"] == []
    metrics = report["domains"]["api"]["metrics"]

    total = _by_name(metrics, "api请求次数")
    success = _by_name(metrics, "api请求成功次数")
    failure = _by_name(metrics, "api请求失败次数")
    latency = _by_name(metrics, "api响应时延")
    concurrency = _by_name(metrics, "api在线数")

    assert total["metric_type"] == "count"
    assert total["aggregation"]["kind"] == "sum"
    assert latency["metric_type"] == "latency"
    assert latency["aggregation"]["kind"] == "percentile"
    assert concurrency["metric_type"] == "capacity"
    assert concurrency["aggregation"]["kind"] == "max"

    draft_metrics = tool.build_drafts(report, load_kpi_catalog(config_dir))["api"]["metrics"]
    draft_success_rate = _draft_by_name(draft_metrics, "api请求成功率")
    draft_failure_rate = _draft_by_name(draft_metrics, "api请求失败率")

    assert draft_success_rate["source_type"] == "derived"
    formula = draft_success_rate["formula"]
    assert formula["numerator"] == success["key"]
    assert formula["denominator"] == total["key"]
    assert formula["denominator_fallback"]["inputs"] == [success["key"], failure["key"]]
    assert draft_failure_rate["formula"]["numerator"] == failure["key"]
    assert draft_failure_rate["formula"]["denominator"] == total["key"]


def test_scan_supports_simple_kpi_header(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    input_dir = tmp_path / "input"
    _write_config(config_dir)
    (input_dir / "nested").mkdir(parents=True)
    (input_dir / "nested" / "kpi-api-15.csv").write_text(
        "API 会话统计\n测量周期,开始时间,结束时间,请求总数,请求成功,请求失败,平均时延\n"
        "15,2026-09-01 10:00:00,2026-09-01 10:15:00,120,117,3,38\n",
        encoding="utf-8",
    )

    report = tool.scan_kpi_csv(input_dir, config_dir=config_dir)
    metrics = report["domains"]["api"]["metrics"]
    names = {item["source_name"] for item in metrics}

    assert report["summary"]["csv_files"] == 1
    assert report["domains"]["api"]["row_count"] == 1
    assert names == {"请求总数", "请求成功", "请求失败", "平均时延"}
    assert _by_name(metrics, "请求总数")["metric_type"] == "count"
    assert _by_name(metrics, "平均时延")["metric_type"] == "latency"


def test_header_is_resolved_by_column_names(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    input_dir = tmp_path / "input"
    _write_config(config_dir)
    (input_dir / "kpi").mkdir(parents=True)
    (input_dir / "kpi" / "kpi-api-30.csv").write_text(
        "设备类型：XXX\n"
        "服务名,测量开始时间,结束时间,测量周期,请求总数,请求成功\n"
        "API,2026-09-01 10:00:00,2026-09-01 10:30:00,30,120,117\n",
        encoding="utf-8",
    )

    report = tool.scan_kpi_csv(input_dir, config_dir=config_dir)
    metrics = report["domains"]["api"]["metrics"]
    names = {item["source_name"] for item in metrics}

    assert names == {"请求总数", "请求成功"}
    assert _by_name(metrics, "请求总数")["metric_type"] == "count"


def test_apply_appends_new_metrics_without_changing_existing(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    input_dir = tmp_path / "input"
    _write_config(config_dir)
    _write_csv(input_dir)

    api_config = yaml.safe_load((config_dir / "api.yaml").read_text(encoding="utf-8"))
    api_config["metrics"].append(
        {
            "key": "registered_metric",
            "name_zh": "api请求次数",
            "name_en": "API Request Count",
            "metric_type": "count",
            "semantic_group": "traffic",
            "display_role": "context",
            "unit": "次",
            "source_type": "raw",
            "aggregation": {"kind": "sum"},
        }
    )
    (config_dir / "api.yaml").write_text(yaml.safe_dump(api_config, allow_unicode=True), encoding="utf-8")

    report = tool.scan_kpi_csv(input_dir, config_dir=config_dir)
    tool.apply_report(report, config_dir)

    config = load_kpi_catalog(config_dir)
    assert "registered_metric" in config.domains["api"].metrics
    assert len(config.domains["api"].metrics) == len(report["domains"]["api"]["metrics"]) + 1
    assert config.domains["api"].metrics["registered_metric"].aliases == []
    assert any(item.name_zh == "api请求成功率" for item in config.domains["api"].metrics.values())


def test_dry_run_writes_draft_outside_config_dir(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "drafts"
    _write_config(config_dir)
    _write_csv(input_dir)

    report = tool.scan_kpi_csv(input_dir, config_dir=config_dir)
    paths = tool.write_drafts(report, output_dir)

    assert set(paths) == {"api"}
    saved = yaml.safe_load(paths["api"].read_text(encoding="utf-8"))
    assert saved["domain"] == "api"
    assert len(saved["metrics"]) == len(report["domains"]["api"]["metrics"])
    assert not list(config_dir.glob("*.draft.yaml"))


def test_input_archive_resolves_task_kpi_directory(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    output_root = tmp_path / "output"
    task_kpi_dir = output_root / "task-sample_a" / "kpi"
    package = tmp_path / "local_run" / "sample-a.zip"
    _write_config(config_dir)
    task_kpi_dir.mkdir(parents=True)
    (task_kpi_dir / "kpi-api-5.csv").write_text(
        "测量周期,开始时间,结束时间,请求总数,请求成功\n5,2026-09-01 10:00:00,2026-09-01 10:05:00,120,117\n",
        encoding="utf-8",
    )
    package.parent.mkdir(parents=True)
    package.write_bytes(b"")

    input_dir = tool.resolve_input_dir(package, output_root=output_root)
    report = tool.scan_kpi_csv(input_dir, config_dir=config_dir)

    assert input_dir == task_kpi_dir
    assert report["summary"]["csv_files"] == 1
    assert report["summary"]["domains"] == ["api"]


def test_input_archive_requires_generated_task_site(tmp_path: Path) -> None:
    tool = _load_tool()
    package = tmp_path / "local_run" / "sample-a.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"")

    with pytest.raises(ValueError, match="请先执行 python main.py"):
        tool.resolve_input_dir(package, output_root=tmp_path / "output")


def _write_resource_csv(path: Path) -> None:
    path.write_text(
        "资源id,中文描述,英文描述\n"
        "UNIT_1,次,times\n"
        "ME_21002,创建媒体资源请求次数(次),Create Media Resource Request Count\n"
        "ME_21003,媒体成功率,对应英文\n",
        encoding="utf-8",
    )


def test_resource_csv_generates_unclassified_preview(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    output_dir = tmp_path / "drafts"
    resource_csv = tmp_path / "resource.csv"
    _write_config(config_dir)
    _write_resource_csv(resource_csv)

    report = tool.scan_resource_csv(resource_csv, config_dir=config_dir)
    metrics = report["metrics"]

    assert report["summary"]["csv_files"] == 1
    assert report["summary"]["new_metrics"] == 2
    assert report["summary"]["skipped_units"] == 1
    assert [item["key"] for item in metrics] == ["me_21002", "me_21003"]
    assert all(item["domain"] == "unclassified" for item in metrics)
    assert metrics[0]["resource_id"] == "ME_21002"
    assert metrics[0]["name_en"] == "Create Media Resource Request Count"

    preview_path = tool.write_resource_preview(report, output_dir)
    saved = yaml.safe_load(preview_path.read_text(encoding="utf-8"))
    assert set(saved["metrics"]) == {"me_21002", "me_21003"}
    assert saved["metrics"]["me_21002"]["domain"] == "unclassified"
    assert saved["metrics"]["me_21003"]["domain"] == "unclassified"
    assert not (config_dir / "resource_metrics.yaml").exists()


def test_resource_csv_uses_default_input_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "deploy" / "config" / "kpi")
    resource_csv = tmp_path / "local_run" / "resource_metrics.csv"
    resource_csv.parent.mkdir(parents=True)
    _write_resource_csv(resource_csv)

    exit_code = tool.main(["--output-dir", "drafts/kpi"])

    assert exit_code == 0
    draft = yaml.safe_load(Path("drafts/kpi/resource_metrics.draft.yaml").read_text(encoding="utf-8"))
    assert set(draft["metrics"]) == {"me_21002", "me_21003"}


def test_resource_csv_apply_imports_registry_once(tmp_path: Path) -> None:
    tool = _load_tool()
    config_dir = tmp_path / "config" / "kpi"
    resource_csv = tmp_path / "resource.csv"
    _write_config(config_dir)
    _write_resource_csv(resource_csv)

    tool.import_resource_metrics(tool.read_resource_csv(resource_csv), config_dir=config_dir)
    registry = load_resource_registry(config_dir)
    assert set(registry.metrics) == {"me_21002", "me_21003"}
    assert all(metric.domain is None for metric in registry.metrics.values())
    assert registry.revision == 1

    tool.import_resource_metrics(tool.read_resource_csv(resource_csv), config_dir=config_dir)
    registry = load_resource_registry(config_dir)
    assert set(registry.metrics) == {"me_21002", "me_21003"}
    assert len(registry.metrics) == 2
