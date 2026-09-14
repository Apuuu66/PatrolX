"""TaskFileCatalog 现场清单契约测试。"""

from pathlib import Path

import pytest

from app.services.scanning import TaskFileCatalog


def _make_file(root: Path, relative: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(relative, encoding="utf-8")
    return path


def test_catalog_scans_only_seven_category_roots_in_stable_posix_order(tmp_path: Path) -> None:
    _make_file(tmp_path, "kpi/b.csv")
    _make_file(tmp_path, "logs/sub/a.log")
    _make_file(tmp_path, "alarm/high.log")
    _make_file(tmp_path, "config/app.conf")
    _make_file(tmp_path, "other/unknown.txt")
    _make_file(tmp_path, "resource/cpu.txt")
    _make_file(tmp_path, "traffic/pdp.txt")

    catalog = TaskFileCatalog.build(tmp_path)

    assert [path.as_posix() for path in catalog.paths()] == [
        "alarm/high.log",
        "config/app.conf",
        "kpi/b.csv",
        "logs/sub/a.log",
        "other/unknown.txt",
        "resource/cpu.txt",
        "traffic/pdp.txt",
    ]


def test_catalog_excludes_infrastructure_and_non_work_paths(tmp_path: Path) -> None:
    excluded = [
        ".main/evidence.log",
        ".main.staging/evidence.log",
        ".main.previous/evidence.log",
        ".patrolx-extracted.json",
        "prepared/logs/prepared.csv",
        "metadata/task.json",
        "rules/logs/rule.json",
        "reports/report.html",
        "execution.log",
        "uploads/package.zip",
    ]
    for relative in excluded:
        _make_file(tmp_path, relative)
    _make_file(tmp_path, "logs/inspectable.log")

    catalog = TaskFileCatalog.build(tmp_path)

    assert [path.as_posix() for path in catalog.paths()] == ["logs/inspectable.log"]


def test_catalog_ignores_missing_category_roots(tmp_path: Path) -> None:
    _make_file(tmp_path, "logs/a.log")

    catalog = TaskFileCatalog.build(tmp_path)

    assert [path.as_posix() for path in catalog.paths()] == ["logs/a.log"]


def test_catalog_rejects_category_root_symlink(tmp_path: Path) -> None:
    real = _make_file(tmp_path.parent / "outside-root", "a.log")
    (tmp_path / "logs").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").symlink_to(real.parent, target_is_directory=True)

    with pytest.raises(ValueError, match="分类目录不是合法目录"):
        TaskFileCatalog.build(tmp_path)


def test_catalog_rejects_nested_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-nested"
    _make_file(outside, "a.log")
    _make_file(tmp_path, "logs/keep.log")
    (tmp_path / "logs" / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="目录链接被拒绝"):
        TaskFileCatalog.build(tmp_path)


def test_catalog_rejects_file_symlink(tmp_path: Path) -> None:
    outside = _make_file(tmp_path.parent / "outside-file", "a.log")
    _make_file(tmp_path, "logs/keep.log")
    (tmp_path / "logs" / "linked.log").symlink_to(outside)

    with pytest.raises(ValueError, match="文件链接被拒绝"):
        TaskFileCatalog.build(tmp_path)


def test_catalog_match_uses_shared_matcher(tmp_path: Path) -> None:
    _make_file(tmp_path, "logs/a.log")
    _make_file(tmp_path, "logs/b.log")

    catalog = TaskFileCatalog.build(tmp_path)

    assert [path.as_posix() for path in catalog.match([r"logs/a\.log"])] == ["logs/a.log"]


def test_catalog_resolve_rejects_paths_outside_catalog(tmp_path: Path) -> None:
    _make_file(tmp_path, "logs/a.log")

    catalog = TaskFileCatalog.build(tmp_path)

    assert catalog.resolve(Path("logs/a.log")) == (tmp_path / "logs/a.log").resolve()
    with pytest.raises(ValueError, match="匹配路径越界"):
        catalog.resolve(Path("../logs/a.log"))
    with pytest.raises(ValueError, match="不在任务文件清单中"):
        catalog.resolve(Path("prepared/a.csv"))
