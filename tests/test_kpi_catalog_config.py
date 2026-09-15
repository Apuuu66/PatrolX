"""KPI 目录化配置契约测试。"""

from pathlib import Path

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
