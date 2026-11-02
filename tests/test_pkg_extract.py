"""两个隐藏解压单元的规则生命周期与分类状态契约。"""

import zipfile
from pathlib import Path

from app.models.schemas import RuleStatus
from app.services.executor import RuleContext


def _package(tmp_path: Path, files: dict[str, str | bytes], name: str = "sample.zip") -> Path:
    """创建包含指定成员的主数据包。"""
    package = tmp_path / name
    with zipfile.ZipFile(package, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    return package


def _context(
    tmp_path: Path,
    package: Path,
    *,
    product: str | None = "UMF",
    log=None,
) -> RuleContext:
    from app.core.checksum import sha256_file

    return RuleContext(
        task_id="task-classification",
        data_dir=tmp_path / "output/task-classification",
        log=log or (lambda *_args, **_kwargs: None),
        prepared_dir=tmp_path / "output/task-classification/prepared",
        package_path=package,
        package_checksum=sha256_file(package),
        product=product,
    )


def test_classification_without_package_returns_structured_error(tmp_path: Path) -> None:
    """分类单元缺少主包时不得猜测现场，必须返回结构化 ERROR。"""
    from app.inspectors.pkg import classification_inspector

    ctx = RuleContext(
        task_id="task-classification",
        data_dir=tmp_path / "output/task-classification",
        log=lambda *_args, **_kwargs: None,
        prepared_dir=tmp_path / "output/task-classification/prepared",
        product="UMF",
    )

    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.ERROR
    assert result.metadata["error_code"] == "archive_corrupt"
    assert "未找到数据包" in result.summary


def test_classification_rebuilds_invalid_v5_manifest_from_main_evidence(tmp_path: Path) -> None:
    """损坏的 manifest v5 不是可复用凭据，分类单元必须从 `.main/` 重建发布。"""
    from app.inspectors.pkg import classification_inspector, main_inspector
    from app.services.extraction.manifest import read_manifest

    package = _package(
        tmp_path,
        {"Basic Information About the UMF/config.txt": "config"},
        name="invalid-manifest.zip",
    )
    ctx = _context(tmp_path, package)

    assert main_inspector.run(ctx).status == RuleStatus.PASS
    (ctx.data_dir / "manifest.json").write_bytes(b"\xff")
    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["reused"] is False
    assert read_manifest(ctx.data_dir)["catalog"][0]["path"] == "basic/config.txt"
    assert ctx.catalog is not None
    assert ctx.catalog.paths() == [Path("basic/config.txt")]


def test_classification_local_archive_failure_is_warn(tmp_path: Path) -> None:
    """单个坏归档产生 failure 和 WARN，但分类现场与空 catalog 仍可发布。"""
    from app.inspectors.pkg import classification_inspector, main_inspector
    from app.services.extraction.manifest import read_manifest

    package = _package(
        tmp_path,
        {"Performance Measurement Results/PerfResult_bad.zip": b"not a zip"},
        name="local-failure.zip",
    )
    ctx = _context(tmp_path, package)

    assert main_inspector.run(ctx).status == RuleStatus.PASS
    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.WARN
    assert result.metadata["failed"] == 1
    assert result.metadata["catalog_count"] == 0
    manifest = read_manifest(ctx.data_dir)
    assert manifest["failures"][0]["route_id"] == "umf.kpi"
    assert manifest["failures"][0]["error_code"] == "archive_corrupt"


def test_classification_emits_structured_audit_event(tmp_path: Path) -> None:
    """分类发布必须记录汇总计数和逐项审计原因。"""
    from app.inspectors.pkg import classification_inspector, main_inspector

    package = _package(
        tmp_path,
        {
            "Basic Information About the UMF/config.txt": "config",
            "Performance Measurement Results/PerfResult_bad.zip": b"not a zip",
            "0/non-alarm.txt": "ignored",
        },
        name="audit-log.zip",
    )
    logs: list[tuple[str, str, dict]] = []

    def capture(level: str, message: str, detail: dict) -> None:
        logs.append((level, message, detail))

    ctx = _context(tmp_path, package, log=capture)

    assert main_inspector.run(ctx).status == RuleStatus.PASS
    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.WARN
    events = [detail for _level, message, detail in logs if message == "classification_audit"]
    assert len(events) == 1
    event = events[0]
    assert event["task_id"] == ctx.task_id
    assert event["rule_code"] == "pkg.extract.classification"
    assert event["reused"] is False
    assert event["counts"] == {
        "landed": 1,
        "ignored": 1,
        "conflicts": 0,
        "failures": 1,
        "catalog": 1,
    }
    assert event["by_route"] == {"ignore.zero": 1, "umf.basic": 1, "umf.kpi": 1}
    assert event["by_category"] == {"config": 1}
    assert event["by_action"] == {"copy": 1, "expand": 1, "ignore": 1}
    assert event["by_status"] == {"failed": 1, "ignored": 1, "landed": 1}
    assert [item["reason"] for item in event["ignored"]] == ["route_ignored"]
    assert [item["reason"] for item in event["failures"]] == ["压缩包读取失败: PerfResult_bad.zip"]


def test_classification_ignored_item_is_pass_and_publishes_empty_catalog(tmp_path: Path) -> None:
    """ignore 是成功审计结果，PASS 时 catalog 可以为空且仍必须通过 catalog 校验。"""
    from app.inspectors.pkg import classification_inspector, main_inspector

    package = _package(tmp_path, {"Other/report.txt": "ignored"}, name="ignored.zip")
    ctx = _context(tmp_path, package, product="CSP")

    assert main_inspector.run(ctx).status == RuleStatus.PASS
    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert result.metadata["failed"] == 0
    assert result.metadata["ignored"] == 1
    assert result.metadata["catalog_count"] == 0
    assert ctx.catalog is not None
    assert ctx.catalog.paths() == []


def test_classification_catalog_failure_is_error(tmp_path: Path) -> None:
    """PASS/WARN 后 catalog 构建失败必须升级为 ERROR。"""
    from app.inspectors.pkg import classification_inspector, main_inspector

    package = _package(tmp_path, {"Basic Information About the UMF/config.txt": "config"})
    ctx = _context(tmp_path, package)

    assert main_inspector.run(ctx).status == RuleStatus.PASS

    def broken_catalog() -> object:
        raise ValueError("catalog 损坏")

    ctx.ensure_catalog = broken_catalog  # type: ignore[method-assign]
    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.ERROR
    assert "catalog 损坏" in result.summary


def _package_with_member(tmp_path: Path, member: str, content: bytes = b"payload\n") -> Path:
    package = tmp_path / "sample.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(member, content)
    return package


def test_main_inspector_never_loads_classification_config(tmp_path: Path, monkeypatch) -> None:
    """主包单元只保证证据现场，不得读取分类配置。"""
    from app.core.checksum import sha256_file
    from app.inspectors import pkg as pkg_module

    package = _package_with_member(tmp_path, "Basic Information About the UMF/config.txt")
    ctx = RuleContext(
        task_id="task-main-only",
        data_dir=tmp_path / "output/task-main-only",
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=sha256_file(package),
        product="UMF",
    )

    def unexpected_config(*_args, **_kwargs):
        raise AssertionError("主包单元不得读取分类配置")

    monkeypatch.setattr(pkg_module, "load_classification_config", unexpected_config)

    result = pkg_module.main_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    assert set(result.metadata) == {"count", "checksum", "evidence_fingerprint", "evidence_path", "reused"}
    assert not (ctx.data_dir / "manifest.json").exists()


def test_classification_inspector_builds_and_publishes_manifest_v5(tmp_path: Path) -> None:
    """主包完成后分类单元必须构建 staging、发布 v5 并重建 catalog。"""
    from app.core.checksum import sha256_file
    from app.inspectors.pkg import classification_inspector, main_inspector
    from app.services.extraction.manifest import read_manifest

    package = _package_with_member(tmp_path, "Basic Information About the UMF/config.txt")
    data_dir = tmp_path / "output/task-classification-v5"
    ctx = RuleContext(
        task_id="task-classification-v5",
        data_dir=data_dir,
        log=lambda *_args, **_kwargs: None,
        package_path=package,
        package_checksum=sha256_file(package),
        product="UMF",
    )

    assert main_inspector.run(ctx).status == RuleStatus.PASS
    result = classification_inspector.run(ctx)

    assert result.status == RuleStatus.PASS
    manifest = read_manifest(data_dir)
    assert manifest["version"] == 5
    assert manifest["classification"]["profile"] == "UMF"
    assert manifest["classification"]["snapshot"]["package_kind"] == "inspection"
    assert manifest["catalog"] == [
        {
            "path": "basic/config.txt",
            "category": "config",
            "route_id": "umf.basic",
            "source_relative": "Basic Information About the UMF/config.txt",
            "sha256": manifest["catalog"][0]["sha256"],
            "size": len(b"payload\n"),
        }
    ]
    assert (data_dir / "basic/config.txt").read_bytes() == b"payload\n"
    assert not (data_dir / ".classification.staging").exists()
    assert ctx.catalog is not None
    assert ctx.catalog.paths() == [Path("basic/config.txt")]
