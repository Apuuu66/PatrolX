import importlib.util
import json
from pathlib import Path

import yaml


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "generate_scan_rules.py"
    spec = importlib.util.spec_from_file_location("generate_scan_rules", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_files(root: Path) -> None:
    (root / "alarm" / "Alarm Information").mkdir(parents=True)
    (root / "logs" / "AppService").mkdir(parents=True)
    (root / "alarm" / "Alarm Information" / "alarm_history_20260901.csv").write_text("a", encoding="utf-8")
    (root / "alarm" / "Alarm Information" / "alarm_history_20260902.csv").write_text("a", encoding="utf-8")
    (root / "logs" / "AppService" / "app_service_20260901.log").write_text("a", encoding="utf-8")


def test_generate_digit_rules_preserve_semantic_names(tmp_path: Path) -> None:
    tool = _load_tool()
    source = tmp_path / "extracted"
    _create_files(source)

    payload = tool.generate_rules(source, "digit")

    assert len(payload["rules"]) == 2
    assert payload["rules"][0]["matched_files"] == [
        "alarm/Alarm Information/alarm_history_20260901.csv",
        "alarm/Alarm Information/alarm_history_20260902.csv",
    ]
    assert payload["rules"][0]["source_patterns"] == [r"^alarm/Alarm\ Information/alarm_history_\d+\.csv$"]
    assert payload["rules"][1]["matched_files"] == ["logs/AppService/app_service_20260901.log"]


def test_generate_directory_and_exact_rules(tmp_path: Path) -> None:
    tool = _load_tool()
    source = tmp_path / "extracted"
    _create_files(source)

    directory_payload = tool.generate_rules(source, "directory")
    exact_payload = tool.generate_rules(source, "file")

    assert {item["source_patterns"][0] for item in directory_payload["rules"]} == {
        r"^alarm/Alarm\ Information/.*$",
        r"^logs/AppService/.*$",
    }
    assert len(exact_payload["rules"]) == 3


def test_validate_reports_unmatched_and_invalid_pattern(tmp_path: Path) -> None:
    tool = _load_tool()
    source = tmp_path / "extracted"
    _create_files(source)
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "rules": [
                    {
                        "code": "scan.edited",
                        "source_patterns": [r"^alarm/Alarm\ Information/alarm_history_\d+\.csv$"],
                    },
                    {
                        "code": "scan.invalid",
                        "source_patterns": ["^logs/("],
                    },
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    report = tool.validate_rules(source, rules_path)

    assert report["summary"]["total_files"] == 3
    assert report["summary"]["matched_files"] == 2
    assert report["summary"]["unmatched_files"] == ["logs/AppService/app_service_20260901.log"]
    assert report["summary"]["invalid_patterns"][0]["rule_code"] == "scan.invalid"


def test_cli_generate_and_validate(tmp_path: Path, capsys) -> None:
    tool = _load_tool()
    source = tmp_path / "extracted"
    _create_files(source)
    output = tmp_path / "scan-rules.yaml"

    assert tool.main(["generate", "--source-dir", str(source), "--output", str(output)]) == 0
    capsys.readouterr()
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert len(payload["rules"]) == 2

    assert tool.main(["validate", "--source-dir", str(source), "--rules", str(output), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["matched_files"] == 3
    assert report["summary"]["unmatched_files"] == []


def test_cli_expands_user_paths_with_spaces(tmp_path: Path, capsys, monkeypatch) -> None:
    tool = _load_tool()
    home = tmp_path / "user home"
    source = home / "extracted package"
    _create_files(source)
    output = home / "scan rules.yaml"
    monkeypatch.setenv("HOME", str(home))

    assert tool.main(["generate", "--source-dir", "~/extracted package", "--output", "~/scan rules.yaml"]) == 0
    capsys.readouterr()
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert len(payload["rules"]) == 2

    assert (
        tool.main(
            [
                "validate",
                "--source-dir",
                "~/extracted package",
                "--rules",
                "~/scan rules.yaml",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["matched_files"] == 3
