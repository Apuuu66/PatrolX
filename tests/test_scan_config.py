"""扫描配置加载与 source_refs 解析契约测试。"""

from pathlib import Path

import pytest
import yaml

from app.core.scan_config import load_scan_groups


def _write_config(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_load_scan_groups_returns_normalized_groups(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path / "scan_rules.yaml",
        {
            "version": 1,
            "groups": {
                "alarm_history": {
                    "description": "告警历史 CSV",
                    "source_patterns": [r"^alarm/(?:.*/)?alarm_history_\d+\.csv$"],
                }
            },
        },
    )

    assert load_scan_groups(path) == {"alarm_history": [r"^alarm/(?:.*/)?alarm_history_\d+\.csv$"]}


@pytest.mark.parametrize(
    "payload",
    [
        {"groups": {}},
        {"version": 2, "groups": {}},
        {"version": 1},
        {"version": 1, "groups": []},
        {"version": 1, "groups": {"alarm_history": None}},
        {"version": 1, "groups": {"alarm/history": {"source_patterns": [r"^alarm/.*$"]}}},
        {"version": 1, "groups": {"alarm_history": {"source_patterns": []}}},
        {"version": 1, "groups": {"alarm_history": {"source_patterns": [""]}}},
        {"version": 1, "groups": {"alarm_history": {"source_patterns": ["/alarm/.*"]}}},
        {"version": 1, "groups": {"alarm_history": {"source_patterns": [r"alarm\\history"]}}},
        {"version": 1, "groups": {"alarm_history": {"source_patterns": ["alarm/("]}}},
        {"version": 1, "groups": {"alarm_history": {"source_patterns": ["^alarm/.*$", "^alarm/.*$"]}}},
    ],
)
def test_load_scan_groups_rejects_invalid_config(tmp_path: Path, payload: dict) -> None:
    path = _write_config(tmp_path / "scan_rules.yaml", payload)
    with pytest.raises(ValueError, match="扫描配置"):
        load_scan_groups(path)


def test_load_scan_groups_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="无法读取扫描配置"):
        load_scan_groups(tmp_path / "missing.yaml")
