"""KPI 目录化配置契约测试。"""

from pathlib import Path
import shutil

import pytest

from app.inspectors.kpi.common import KpiConfigError, load_kpi_config, normalize_metric_name

REPO_ROOT = Path(__file__).resolve().parents[1]
KPI_CONFIG_DIR = REPO_ROOT / "deploy/config/kpi"
EXPECTED_FILES = {"common.yaml", "call.yaml", "api.yaml", "media.yaml"}


def test_kpi_config_uses_domain_directory_and_removes_legacy_file() -> None:
    assert KPI_CONFIG_DIR.is_dir()
    assert {p.name for p in KPI_CONFIG_DIR.iterdir() if p.is_file()} == EXPECTED_FILES
    assert not (REPO_ROOT / "deploy/config/kpi_rules.yaml").exists()


def test_load_kpi_config_reads_common_and_registered_domains() -> None:
    config = load_kpi_config()
    assert config.version == 2
    assert config.input_timezone == "Asia/Shanghai"
    assert config.budgets["max_rows_per_file"] == 100_000
    assert set(config.domains) == {"call", "api", "media"}

    call = config.domains["call"]
    assert call.domain == "call"
    required_metrics = {
        "call_attempts",
        "call_success_count",
        "call_failure_count",
        "call_success_rate",
        "call_failure_rate",
    }
    assert required_metrics <= set(call.metrics)
    assert call.metrics["call_success_rate"].formula is not None
    assert "call_success_rate" in call.thresholds


def test_metric_aliases_are_indexed_by_normalized_name() -> None:
    config = load_kpi_config()
    call = config.domains["call"]
    assert call.alias_index[normalize_metric_name("呼叫请求次数")] == "call_attempts"
    assert call.alias_index[normalize_metric_name("  call   attempts ")] == "call_attempts"


@pytest.mark.parametrize(
    ("filename", "content", "context"),
    [
        ("common.yaml", "version: 1\n", "common.version"),
        ("call.yaml", "domain: api\n", "domain_mismatch"),
        ("call.yaml", "domain: call\nmetrics:\n- key: bad-key\n", "call.metrics.*key"),
        ("unknown.yaml", "domain: unknown\n", "unknown file"),
    ],
)
def test_load_kpi_config_rejects_invalid_files(tmp_path: Path, filename: str, content: str, context: str) -> None:
    base = REPO_ROOT / "deploy/config/kpi"
    for name in ("common.yaml", "call.yaml", "api.yaml", "media.yaml"):
        source = base / name
        target = tmp_path / name
        target.write_text(content if name == filename else source.read_text(encoding="utf-8"), encoding="utf-8")
    if filename == "unknown.yaml":
        (tmp_path / "unknown.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(KpiConfigError, match=context):
        load_kpi_config(tmp_path)


def _copy_kpi_config(tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "kpi"
    shutil.copytree(KPI_CONFIG_DIR, target)
    return target


def _read_domain(config_dir: Path, name: str = "api.yaml") -> dict:
    import yaml

    return yaml.safe_load((config_dir / name).read_text(encoding="utf-8"))


def _write_domain(config_dir: Path, raw: dict, name: str = "api.yaml") -> None:
    import yaml

    (config_dir / name).write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def test_new_metric_and_alias_only_affect_target_domain(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    raw["metrics"].append(
        {
            "key": "api_requests",
            "name_zh": "API 请求次数",
            "name_en": "API Requests",
            "metric_type": "count",
            "semantic_group": "traffic",
            "display_role": "context",
            "unit": "次",
            "source_type": "raw",
            "aggregation": {"kind": "sum"},
            "aliases": [
                {"language": "zh", "value": "API请求数"},
                {"language": "en", "value": "Total API Calls"},
            ],
        }
    )
    _write_domain(config_dir, raw)

    config = load_kpi_config(config_dir)
    api = config.domains["api"]
    call = config.domains["call"]

    assert "api_requests" in api.metrics
    assert api.alias_index[normalize_metric_name("API请求数")] == "api_requests"
    assert api.alias_index[normalize_metric_name("  api请求数 ")] == "api_requests"
    assert api.alias_index[normalize_metric_name("api requests")] == "api_requests"
    assert call.alias_index.get(normalize_metric_name("API请求数")) is None
    assert config.domains["api"].config_source.endswith("api.yaml")
    assert config.domains["call"].config_source.endswith("call.yaml")


def test_metric_names_and_aliases_are_exact_after_normalization() -> None:
    config = load_kpi_config()
    call = config.domains["call"]
    assert call.alias_index[normalize_metric_name("  CALL　ATTEMPTS ")] == "call_attempts"
    assert normalize_metric_name("CALL近似ATTEMPTS") != normalize_metric_name("call attempts")


def _valid_api_metrics() -> list[dict]:
    return [
        {
            "key": "api_requests",
            "name_zh": "API 请求次数",
            "name_en": "API Requests",
            "metric_type": "count",
            "semantic_group": "traffic",
            "display_role": "context",
            "unit": "次",
            "source_type": "raw",
            "aggregation": {"kind": "sum"},
            "aliases": [{"language": "zh", "value": "API请求次数"}],
        },
        {
            "key": "api_success_count",
            "name_zh": "API 成功次数",
            "name_en": "API Successes",
            "metric_type": "count",
            "semantic_group": "traffic",
            "display_role": "context",
            "unit": "次",
            "source_type": "raw",
            "aggregation": {"kind": "sum"},
            "aliases": [{"language": "zh", "value": "API成功次数"}],
        },
    ]


def test_config_rejects_duplicate_metric_key_and_alias_conflict(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    raw["metrics"] = _valid_api_metrics()
    raw["metrics"].append(dict(raw["metrics"][0]))
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match=": 重复"):
        load_kpi_config(config_dir)

    conflict_dir = tmp_path / "kpi-conflict"
    shutil.copytree(KPI_CONFIG_DIR, conflict_dir)
    config_dir = conflict_dir
    raw = _read_domain(config_dir)
    raw["metrics"] = _valid_api_metrics()
    raw["metrics"][1].setdefault("aliases", []).append({"language": "zh", "value": raw["metrics"][0]["name_zh"]})
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match="已映射到"):
        load_kpi_config(config_dir)


def test_config_rejects_cross_domain_formula(tmp_path: Path) -> None:
    config_dir = _copy_kpi_config(tmp_path)
    raw = _read_domain(config_dir)
    raw["metrics"].append(
        {
            "key": "api_bad_rate",
            "name_zh": "错误跨域成功率",
            "name_en": "Invalid Cross Domain Rate",
            "metric_type": "rate",
            "semantic_group": "quality",
            "display_role": "highlight",
            "unit": "%",
            "source_type": "derived",
            "aggregation": {"kind": "ratio_from_inputs"},
            "aliases": [{"language": "zh", "value": "错误跨域成功率"}],
            "formula": {"kind": "ratio", "numerator": "call_success_count", "denominator": "call_attempts"},
        }
    )
    _write_domain(config_dir, raw)
    with pytest.raises(KpiConfigError, match="api.metrics\\[key=api_bad_rate\\].formula: 引用未知输入"):
        load_kpi_config(config_dir)
