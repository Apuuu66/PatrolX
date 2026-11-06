"""CLI 无子命令入口回归测试。"""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import cli
from app.models.schemas import PackageKind, Product
from tests.baseline_helpers import SAMPLE, setup_env


def test_main_without_subcommand_uses_default_task_id(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []

    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main([]) == 0
    assert calls == [(packages[0], {"task_id": None})]


def test_main_run_subcommand_accepts_task_id(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []

    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main(["run", "--task-id", "task-sample", "--product", "UMF"]) == 0
    assert calls == [
        (
            packages[0],
            {"task_id": "task-sample", "customer": {"product": Product.UMF}, "package_kind": PackageKind.INSPECTION},
        )
    ]


@pytest.mark.parametrize(
    ("command", "entrypoint"),
    [
        (["run"], "run_task"),
        (["run-one", "--rule", "rule.sample"], "run_single_rule"),
        (["explain-match", "--rule", "rule.sample"], "explain_match"),
    ],
)
@pytest.mark.parametrize(
    ("metadata_args", "expected_code"),
    [
        ([], "missing_product"),
        (["--product", "  "], "missing_product"),
        (["--product", " XYZ "], "invalid_product"),
        (["--package-kind", "log_supplement", "--product", "UMF"], "metadata_not_applicable"),
    ],
)
def test_task_commands_reject_invalid_metadata(
    command: list[str],
    entrypoint: str,
    metadata_args: list[str],
    expected_code: str,
    monkeypatch,
    capsys,
) -> None:
    """三个任务子命令使用同一套稳定元数据错误码。"""
    calls: list[object] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [Path("sample.zip")])
    monkeypatch.setattr(cli, entrypoint, lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main([*command, *metadata_args]) == 1
    assert calls == []
    assert f"[{expected_code}]" in capsys.readouterr().out


def test_main_run_forwards_normalized_product_and_package_kind(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main(["run", "--product", " umf ", "--package-kind", "inspection", "--task-id", "task-1"]) == 0

    assert calls == [
        (
            packages[0],
            {
                "task_id": "task-1",
                "customer": {"product": Product.UMF},
                "package_kind": PackageKind.INSPECTION,
            },
        )
    ]


def test_main_run_one_forwards_normalized_product_and_package_kind(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_single_rule", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main(["run-one", "--rule", "rule.sample", "--product", "csp", "--package-kind", "inspection"]) == 0

    assert calls == [
        (
            ("rule.sample", packages[0]),
            {"task_id": None, "product": Product.CSP, "package_kind": PackageKind.INSPECTION},
        )
    ]


def test_main_explain_match_forwards_normalized_product_and_package_kind(monkeypatch, capsys) -> None:
    packages = [Path("sample.zip")]
    calls = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(
        cli,
        "explain_match",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True},
    )

    assert cli.main(["explain-match", "--rule", "rule.sample", "--product", "csp"]) == 0

    assert calls == [
        (
            ("rule.sample",),
            {"package": packages[0], "task_id": None, "product": Product.CSP, "package_kind": PackageKind.INSPECTION},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_log_supplement_without_product_is_forwarded(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main(["run", "--package-kind", "log_supplement"]) == 0

    assert calls == [
        (
            packages[0],
            {"task_id": None, "customer": {}, "package_kind": PackageKind.LOG_SUPPLEMENT},
        )
    ]


def test_cli_run_infers_persisted_log_supplement_kind(tmp_path, monkeypatch, capsys) -> None:
    """全量运行未显式指定 kind 时，必须沿用已有日志补充包任务类型。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-persisted-log", package_kind=PackageKind.LOG_SUPPLEMENT)
    calls = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main(["run", "--task-id", task.task_id]) == 0

    assert calls == [
        (
            SAMPLE,
            {
                "task_id": task.task_id,
                "customer": {},
                "package_kind": PackageKind.LOG_SUPPLEMENT,
            },
        )
    ]
    capsys.readouterr()


def test_cli_run_can_supply_product_for_existing_failed_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """失败任务沿用同一 task_id 时，显式 product 应补齐缺失元数据而不是误报冲突。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    failed = run_task(SAMPLE, task_id="task-failed-without-product")
    assert failed.status == "failed"
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    monkeypatch.setattr(cli, "run_task", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main(["run", "--task-id", failed.task_id, "--product", "UMF"]) == 0

    assert calls == [
        (
            (SAMPLE,),
            {
                "task_id": failed.task_id,
                "customer": {"product": Product.UMF},
                "package_kind": PackageKind.INSPECTION,
            },
        )
    ]
    capsys.readouterr()


def test_cli_run_returns_nonzero_when_task_fails_after_metadata_validation(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """全量运行必须把任务失败传播为命令退出码，避免门禁假通过。"""
    setup_env(tmp_path, monkeypatch)
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip archive")
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [broken])

    assert cli.main(["run", "--task-id", "task-broken-package", "--product", "UMF"]) == 1

    output = capsys.readouterr().out
    assert "任务 task-broken-package 失败" in output


def test_cli_rejects_product_for_persisted_log_supplement(tmp_path, monkeypatch, capsys) -> None:
    """已有日志补充包任务不得因为默认 kind 而误报冲突，应稳定返回元数据不适用。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-persisted-log-product", package_kind=PackageKind.LOG_SUPPLEMENT)
    calls: list[object] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main(["run", "--task-id", task.task_id, "--product", "UMF"]) == 1

    assert "[metadata_not_applicable]" in capsys.readouterr().out
    assert calls == []


@pytest.mark.parametrize(
    ("command", "entrypoint"),
    [
        (["run-one", "--rule", "kpi.measurement_units"], "run_single_rule"),
        (["explain-match", "--rule", "kpi.measurement_units"], "explain_match"),
    ],
)
def test_existing_task_allows_verify_without_product(
    command: list[str],
    entrypoint: str,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """历史 task.json 没有 product 时，verify-one 仍必须读取现场并继续执行。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-legacy-without-product")
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    if entrypoint == "run_single_rule":
        monkeypatch.setattr(
            cli,
            entrypoint,
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )
    else:
        monkeypatch.setattr(
            cli,
            entrypoint,
            lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True},
        )

    assert cli.main([*command, "--task-id", task.task_id]) == 0

    assert calls
    assert calls[0][1]["product"] is None
    assert calls[0][1]["package_kind"] == PackageKind.INSPECTION
    capsys.readouterr()


@pytest.mark.parametrize(
    ("command", "entrypoint"),
    [
        (["run-one", "--rule", "kpi.measurement_units"], "run_single_rule"),
        (["explain-match", "--rule", "kpi.measurement_units"], "explain_match"),
    ],
)
def test_existing_task_reuses_persisted_product_without_explicit_argument(
    command: list[str],
    entrypoint: str,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """verify-one 未传 --product 时必须复用 task.json 中的持久化网元类型。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-persisted-product", customer={"product": Product.CSP})
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    if entrypoint == "run_single_rule":
        monkeypatch.setattr(cli, entrypoint, lambda *args, **kwargs: calls.append((args, kwargs)))
    else:
        monkeypatch.setattr(
            cli,
            entrypoint,
            lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True},
        )

    assert cli.main([*command, "--task-id", task.task_id]) == 0

    assert calls
    assert calls[0][1]["product"] == Product.CSP
    assert calls[0][1]["package_kind"] == PackageKind.INSPECTION
    capsys.readouterr()


def test_existing_log_supplement_never_forwards_legacy_product(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """日志补充包即使存在历史脏 product，也不得继续传播到执行上下文。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(
        SAMPLE,
        task_id="task-legacy-log-product",
        customer={"product": Product.CSP},
        package_kind=PackageKind.LOG_SUPPLEMENT,
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    monkeypatch.setattr(
        cli,
        "run_single_rule",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert cli.main(["run-one", "--rule", "kpi.measurement_units", "--task-id", task.task_id]) == 0

    assert calls
    assert calls[0][1]["product"] is None
    assert calls[0][1]["package_kind"] == PackageKind.LOG_SUPPLEMENT
    capsys.readouterr()


@pytest.mark.parametrize(
    ("command", "entrypoint"),
    [
        (["run-one", "--rule", "kpi.measurement_units"], "run_single_rule"),
        (["explain-match", "--rule", "kpi.measurement_units"], "explain_match"),
    ],
)
def test_cli_rejects_persisted_product_conflict(
    command: list[str],
    entrypoint: str,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """同一 task_id 显式 product 与持久化值不同时必须拒绝，不得静默覆盖。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-product-conflict", customer={"product": Product.UMF})
    calls: list[object] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    monkeypatch.setattr(cli, entrypoint, lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main([*command, "--task-id", task.task_id, "--product", "CSP"]) == 1

    output = capsys.readouterr().out
    assert "[package_product_conflict]" in output
    assert calls == []


@pytest.mark.parametrize(
    ("command", "entrypoint"),
    [
        (["run-one", "--rule", "kpi.measurement_units"], "run_single_rule"),
        (["explain-match", "--rule", "kpi.measurement_units"], "explain_match"),
    ],
)
def test_cli_rejects_persisted_package_kind_conflict(
    command: list[str],
    entrypoint: str,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """同一 task_id 显式 package kind 与持久化值不同时必须拒绝。"""
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-kind-conflict", customer={"product": Product.UMF})
    calls: list[object] = []
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [SAMPLE])
    monkeypatch.setattr(cli, entrypoint, lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main([*command, "--task-id", task.task_id, "--package-kind", "log_supplement"]) == 1

    output = capsys.readouterr().out
    assert "[package_kind_conflict]" in output
    assert calls == []


def test_cli_run_initializes_fresh_sqlite_before_task_execution(tmp_path: Path) -> None:
    """本地全流程在全新 SQLite 上必须先建表，再执行会产生任务记录的任务。"""
    repo_root = Path(__file__).resolve().parents[1]
    sqlite_path = tmp_path / "patrolx.db"
    output_dir = tmp_path / "output"
    env = os.environ.copy()
    env.update(
        {
            "PATROLX_SQLITE_PATH": str(sqlite_path),
            "PATROLX_OUTPUT_DIR": str(output_dir),
            "PATROLX_UPLOADS_DIR": str(SAMPLE.parent),
            "PATROLX_LOCAL_RUN_DIR": str(tmp_path / "local_run"),
            "PATROLX_CONFIG_DIR": str(repo_root / "deploy" / "config"),
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "run",
            "--task-id",
            "task-fresh-database",
            "--product",
            "UMF",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(sqlite_path) as connection:
        row = connection.execute(
            "SELECT status FROM tasks WHERE task_id = ?",
            ("task-fresh-database",),
        ).fetchone()
    assert row == ("completed",)
