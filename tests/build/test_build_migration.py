"""旧构建入口迁移看护测试。"""

from __future__ import annotations

from pathlib import Path

from tests.build.conftest import build  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_build_entries_removed() -> None:
    for name in ("Makefile", "run-offline.sh", "run-online.sh", "uv.lock"):
        assert not (ROOT / name).exists(), name


def test_requirements_txt_removed() -> None:
    assert not (ROOT / "requirements.txt").exists()


def test_active_docs_use_python_entry() -> None:
    for relative in ("README.md", "AGENTS.md", "docs/architecture.md", "docs/roadmap.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "python build.py" in text
        assert "make " not in text
        assert "uv " not in text
        assert "uv.lock" not in text


def test_subprocess_contract_has_no_shell() -> None:
    text = build.ROOT.joinpath("build.py").read_text(encoding="utf-8")
    assert "shell=True" not in text
