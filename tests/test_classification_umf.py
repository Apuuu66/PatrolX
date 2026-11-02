"""UMF 按真实来源目录分类的 US1 行为测试。"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

from app.services.extraction.audit import conflict_digest
from app.services.extraction.classification import (
    ClassificationRun,
    SceneRoot,
    _relative_to_scene,
    classify_main_evidence,
    infer_scene_root,
)
from app.services.extraction.config import load_classification_config, loads_classification_config


def _write(path: Path, content: bytes = b"fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _corrupt_zip_member_crc(payload: bytes, member_name: str) -> bytes:
    """修改指定 ZIP 成员的中央目录 CRC，保留其他成员可读。"""
    corrupted = bytearray(payload)
    eocd_offset = payload.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    entry_count = struct.unpack_from("<H", payload, eocd_offset + 10)[0]
    central_offset = struct.unpack_from("<I", payload, eocd_offset + 16)[0]
    target_name = member_name.encode()

    for _ in range(entry_count):
        assert payload[central_offset : central_offset + 4] == b"PK\x01\x02"
        name_length = struct.unpack_from("<H", payload, central_offset + 28)[0]
        extra_length = struct.unpack_from("<H", payload, central_offset + 30)[0]
        comment_length = struct.unpack_from("<H", payload, central_offset + 32)[0]
        name_start = central_offset + 46
        if payload[name_start : name_start + name_length] == target_name:
            crc = struct.unpack_from("<I", payload, central_offset + 16)[0]
            struct.pack_into("<I", corrupted, central_offset + 16, crc ^ 1)
            return bytes(corrupted)
        central_offset += 46 + name_length + extra_length + comment_length

    raise AssertionError(f"未找到 ZIP 成员: {member_name}")


def _classify(
    tmp_path: Path,
    files: dict[str, bytes | str],
    *,
    product: str = "UMF",
    config=None,
) -> ClassificationRun:
    data_dir = tmp_path / "task"
    evidence_root = data_dir / ".main"
    evidence_root.mkdir(parents=True)
    for relative, content in files.items():
        payload = content.encode("utf-8") if isinstance(content, str) else content
        _write(evidence_root / relative, payload)
    return classify_main_evidence(data_dir, product=product, config=config)


def _entry(run: ClassificationRun, source_suffix: str):
    matches = [entry for entry in run.entries if entry.source_relative.endswith(source_suffix)]
    assert len(matches) == 1, [entry.source_relative for entry in run.entries]
    return matches[0]


def _scene(anchor: str = "UMF Problem scene") -> str:
    return f"Outer Network/Problem 333/{anchor}"


def test_infer_scene_root_clusters_anchor_parents(tmp_path: Path) -> None:
    """多层包装下，场景根按 profile anchor 父目录聚类推导。"""
    evidence_root = tmp_path / "task" / ".main"
    _write(evidence_root / _scene() / "Operation Logs/operationlog_history_01.csv")
    _write(evidence_root / _scene() / "MML Configurations/EXP MML.txt")

    scene_root = infer_scene_root(
        evidence_root,
        ("Operation Logs", "MML Configurations"),
    )

    assert isinstance(scene_root, SceneRoot)
    assert scene_root.relative_to_evidence == Path(_scene())
    assert scene_root.matched_anchors == ("MML Configurations", "Operation Logs")


def test_infer_scene_root_requires_anchor_parent_not_outer_wrapper(tmp_path: Path) -> None:
    """仅有 Operation Logs/MML Configurations 时也必须剥离设备、问题号和包装层。"""
    evidence_root = tmp_path / "task" / ".main"
    _write(evidence_root / "device-a/331/wrapper/scene-a/Operation Logs/operationlog_history_01.csv")
    _write(evidence_root / "device-a/331/wrapper/scene-a/MML Configurations/EXP MML.txt")

    scene_root = infer_scene_root(evidence_root, ("Operation Logs", "MML Configurations"))

    assert scene_root.relative_to_evidence == Path("device-a/331/wrapper/scene-a")


def test_infer_scene_root_without_anchor_is_evidence_root(tmp_path: Path) -> None:
    """没有 profile anchor 命中时，场景根固定为证据根。"""
    evidence_root = tmp_path / "task" / ".main"
    _write(evidence_root / "unrelated/file.txt")

    scene_root = infer_scene_root(evidence_root, ("Operation Logs",))

    assert scene_root.relative_to_evidence == Path(".")
    assert scene_root.matched_anchors == ()


def test_scene_root_uses_only_current_profile_anchors(tmp_path: Path) -> None:
    """CSP anchor 不得影响 UMF 场景根推导。"""
    evidence_root = tmp_path / "task" / ".main"
    _write(evidence_root / _scene() / "Basic Information About the UMF/config.ini")
    _write(evidence_root / "csp-device/Alarm Data/alarm.csv")

    scene_root = infer_scene_root(evidence_root, ("Basic Information About the UMF",))

    assert scene_root.relative_to_evidence == Path(_scene())
    assert scene_root.matched_anchors == ("Basic Information About the UMF",)


def test_scene_root_ignores_isolated_shared_anchor_in_other_tree(tmp_path: Path) -> None:
    """其他网元树中的孤立共享 anchor 不得把真实 UMF 场景根拉回证据根。"""
    evidence_root = tmp_path / "task" / ".main"
    _write(evidence_root / _scene() / "Basic Information About the UMF/config.ini")
    _write(evidence_root / _scene() / "Operation Logs/operationlog_history_01.csv")
    _write(evidence_root / _scene() / "Performance Measurement Results/PerfResult_01.zip")
    _write(evidence_root / "csp-device/0/Problems/Operation Logs/operationlog_history_other.csv")

    scene_root = infer_scene_root(
        evidence_root,
        (
            "Basic Information About the UMF",
            "Operation Logs",
            "Performance Measurement Results",
        ),
    )

    assert scene_root.relative_to_evidence == Path(_scene())
    assert scene_root.matched_anchors == (
        "Basic Information About the UMF",
        "Operation Logs",
        "Performance Measurement Results",
    )


def test_capture_root_uses_rightmost_complete_segment_and_preserves_case(tmp_path: Path) -> None:
    """重复目录段时取最右 capture_root，匹配不敏感但目标保留原始大小写。"""
    source = f"{_scene()}/Basic Information About the UMF/Nested/basic information about the umf/Sub/Config.TXT"
    run = _classify(tmp_path, {source: "config"})

    entry = _entry(run, "Config.TXT")
    assert entry.route_id == "umf.basic"
    assert entry.category == "config"
    assert entry.original_target == "basic/Sub/Config.TXT"
    assert entry.target == "basic/Sub/Config.TXT"


def test_outer_wrapping_is_not_included_in_fallback_target(tmp_path: Path) -> None:
    """UMF fallback 只使用场景相对路径，外层设备和包装目录不得污染目标。"""
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/Basic Information About the UMF/config.ini": "anchor",
            f"{_scene()}/Unlisted/CollectAndCheck.INI": "unknown",
        },
    )

    entry = _entry(run, "CollectAndCheck.INI")
    assert entry.route_id == "umf.other"
    assert entry.category == "other"
    assert entry.target == "other/Unlisted/CollectAndCheck.INI"


def test_umf_precise_routes_land_in_frozen_targets_and_categories(tmp_path: Path) -> None:
    """Basic、调试、设备/MESH/系统状态和操作日志使用各自冻结路线。"""
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/Basic Information About the UMF/config.ini": "basic",
            f"{_scene()}/Debugging Commands/debug.txt": "debug",
            f"{_scene()}/Equipment Status/equipment.csv": "equipment",
            f"{_scene()}/MESH Information (Problem)/mesh.txt": "mesh",
            f"{_scene()}/System Resources/resources.txt": "resources",
            f"{_scene()}/Operation Logs/operationlog_history_20260918.csv": "operation",
        },
    )

    assert {entry.source_relative: (entry.route_id, entry.category, entry.target) for entry in run.entries} == {
        f"{_scene()}/Basic Information About the UMF/config.ini": (
            "umf.basic",
            "config",
            "basic/config.ini",
        ),
        f"{_scene()}/Debugging Commands/debug.txt": (
            "umf.debug",
            "status",
            "debug/debug.txt",
        ),
        f"{_scene()}/Equipment Status/equipment.csv": (
            "umf.equipment-status",
            "status",
            "status/equipment.csv",
        ),
        f"{_scene()}/MESH Information (Problem)/mesh.txt": (
            "umf.mesh-status",
            "status",
            "status/mesh.txt",
        ),
        f"{_scene()}/System Resources/resources.txt": (
            "umf.system-resources",
            "status",
            "status/resources.txt",
        ),
        f"{_scene()}/Operation Logs/operationlog_history_20260918.csv": (
            "umf.operation-log",
            "operation",
            "operation-log/operationlog_history_20260918.csv",
        ),
    }


def test_scene_relative_path_comparison_is_case_insensitive() -> None:
    """场景根与来源包装大小写不同时仍应得到场景相对路径。"""
    assert _relative_to_scene(
        Path("device/problem/scene/MML Configurations/EXP MML.txt"),
        Path("Device/Problem/Scene"),
    ) == Path("MML Configurations/EXP MML.txt")
    assert _relative_to_scene(Path("another/scene/file.txt"), Path("Device/Problem/Scene")) is None


def test_directory_segments_and_file_globs_are_case_insensitive(tmp_path: Path) -> None:
    """来源目录和文件模式大小写不敏感，落位保留原始大小写。"""
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/debugging commands/Diagnostic.JSON": "debug",
            f"{_scene()}/operation logs/OPERATIONLOG_HISTORY_20260918.CSV": "operation",
        },
    )

    assert _entry(run, "Diagnostic.JSON").target == "debug/Diagnostic.JSON"
    operation = _entry(run, "OPERATIONLOG_HISTORY_20260918.CSV")
    assert operation.route_id == "umf.operation-log"
    assert operation.target == "operation-log/OPERATIONLOG_HISTORY_20260918.CSV"


def test_mml_file_and_archive_land_without_extension_guessing(tmp_path: Path) -> None:
    """MML 普通文件复制，ZIP 成员只继承当前路线且不按扩展名二次分类。"""
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/MML Configurations/EXP MML.txt": "text",
            f"{_scene()}/MML Configurations/EXPMML_20260918.zip": _zip_bytes(
                {
                    "Config/Fragment.txt": b"plain",
                    "Unexpected/PerfResult_fake.zip": b"not-a-real-archive",
                }
            ),
        },
    )

    text = _entry(run, "EXP MML.txt")
    assert (text.route_id, text.category, text.target) == ("umf.mml-file", "config", "mml/EXP MML.txt")
    for member in run.entries:
        if member.source_relative.endswith("EXPMML_20260918.zip"):
            assert member.route_id == "umf.mml-archive"
            assert member.category == "config"
            assert member.target.startswith("mml/")
    assert {entry.member_relative for entry in run.entries if entry.route_id == "umf.mml-archive"} == {
        "Config/Fragment.txt",
        "Unexpected/PerfResult_fake.zip",
    }


def test_kpi_archive_expands_all_members_into_flat_kpi_namespace(tmp_path: Path) -> None:
    """PerfResult 所有成员直接进入 kpi/，成员名称和扩展名不得触发二次分类。"""
    members = {
        "part-01.csv": b"csv",
        "Debugging Commands/not-kpi.txt": b"txt",
        "nested/PerfResult_fake.zip": b"zip-data",
    }
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/Performance Measurement Results/PerfResult_20260918.zip": _zip_bytes(members),
        },
    )

    expanded = [entry for entry in run.entries if entry.route_id == "umf.kpi"]
    assert {entry.member_relative for entry in expanded} == set(members)
    assert all(entry.category == "kpi" and entry.target.startswith("kpi/") for entry in expanded)
    assert {entry.target for entry in expanded} == {
        "kpi/part-01.csv",
        "kpi/Debugging Commands/not-kpi.txt",
        "kpi/nested/PerfResult_fake.zip",
    }


def test_expanded_member_corruption_records_member_relative(tmp_path: Path) -> None:
    """KPI 归档成员损坏时，失败审计必须指向具体成员且保留其他成功成员。"""
    source = f"{_scene()}/Performance Measurement Results/PerfResult_corrupt_member.zip"
    member_relative = "nested/Corrupted.csv"
    archive = _corrupt_zip_member_crc(
        _zip_bytes({"valid.csv": b"valid", member_relative: b"corrupt"}),
        member_relative,
    )

    run = _classify(tmp_path, {source: archive})

    assert [entry.member_relative for entry in run.entries if entry.source_relative == source] == ["valid.csv"]
    failures = [failure for failure in run.failures if failure.source_relative == source]
    assert len(failures) == 1
    assert failures[0].member_relative == member_relative
    assert failures[0].member_relative != source
    assert failures[0].error_code == "archive_corrupt"


def test_mesh_metrics_archive_uses_archive_stem_namespace_once(tmp_path: Path) -> None:
    """CollectExport 成员进入 MESH namespace，伪 KPI 文件名不得改变分类。"""
    members = {
        "mesh-01.csv": b"one",
        "nested/PerfResult_fake.csv": b"two",
    }
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/MESH Application Metrics/CollectExport_20260918.zip": _zip_bytes(members),
        },
    )

    expanded = [entry for entry in run.entries if entry.route_id == "umf.mesh-metrics"]
    assert {entry.member_relative for entry in expanded} == set(members)
    assert all(entry.category == "other" for entry in expanded)
    assert {entry.target for entry in expanded} == {
        "other/MESH Application Metrics/CollectExport_20260918/mesh-01.csv",
        "other/MESH Application Metrics/CollectExport_20260918/nested/PerfResult_fake.csv",
    }


def test_unknown_zip_is_copied_whole_and_members_are_not_inspected(tmp_path: Path) -> None:
    """未声明展开的归档按 fallback 原样复制，不得读取成员后猜测分类。"""
    archive = _zip_bytes({"PerfResult_should_not_route.csv": b"inner"})
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/Basic Information About the UMF/config.ini": "anchor",
            f"{_scene()}/Unlisted/UnknownBundle.ZIP": archive,
        },
    )

    entry = _entry(run, "UnknownBundle.ZIP")
    assert (entry.route_id, entry.category, entry.action) == ("umf.other", "other", "fallback")
    assert entry.member_relative is None
    assert entry.target == "other/Unlisted/UnknownBundle.ZIP"
    assert (run.data_dir / entry.target).read_bytes() == archive


def test_umf_fallback_keeps_collectandcheck_and_unmatched_file(tmp_path: Path) -> None:
    """UMF 未命中普通文件全部按场景相对路径进入 other，不静默丢弃。"""
    run = _classify(
        tmp_path,
        {
            f"{_scene()}/Basic Information About the UMF/config.ini": "anchor",
            f"{_scene()}/collectandcheck.ini": "check",
            f"{_scene()}/Unlisted/custom.dat": "data",
        },
    )

    assert {entry.source_relative: entry.target for entry in run.entries if entry.route_id == "umf.other"} == {
        f"{_scene()}/collectandcheck.ini": "other/collectandcheck.ini",
        f"{_scene()}/Unlisted/custom.dat": "other/Unlisted/custom.dat",
    }


def test_umf_file_outside_scene_uses_explicit_ignore_route(tmp_path: Path) -> None:
    """真实包中场景根上一级的 collectandcheck 必须有稳定 ignore route，不能产生 null route。"""
    scene = Path("device/331/UMF Problem scene")
    outside = Path("device/331/collectandcheck.ini")
    run = _classify(
        tmp_path,
        {
            (scene / "Basic Information About the UMF/config.ini").as_posix(): "anchor",
            outside.as_posix(): "outside",
        },
    )

    assert [entry.target for entry in run.entries] == ["basic/config.ini"]
    assert len(run.ignored) == 1
    ignored = run.ignored[0]
    assert (
        ignored.source_relative,
        ignored.route_id,
        ignored.product,
        ignored.action,
        ignored.reason,
    ) == (outside.as_posix(), "umf.ignore-outside-scene", "UMF", "ignore", "route_ignored")
    assert (ignored.category, ignored.original_target, ignored.target) == (None, None, None)
    assert not (run.data_dir / "other/collectandcheck.ini").exists()


def test_csp_non_alarm_is_ignored_and_not_published(tmp_path: Path) -> None:
    """CSP 非告警内容只写 ignore 审计，不进入工作分类现场。"""
    source = "csp-device/configuration/Inventory/inventory.csv"
    run = _classify(tmp_path, {source: "csp"}, product="CSP")

    assert run.entries == ()
    assert len(run.ignored) == 1
    ignored = run.ignored[0]
    assert ignored.source_relative == source
    assert ignored.route_id == "csp.ignore-non-alarm"
    assert ignored.action == "ignore"
    assert ignored.reason == "route_ignored"
    assert ignored.category is None
    assert ignored.target is None
    assert not (run.data_dir / "other").exists()


def test_priority_breaks_same_phase_ties(tmp_path: Path) -> None:
    """同一阶段内按 priority 降序选择，高优先级 copy 胜过低优先级 ignore。"""
    config = loads_classification_config(
        """
version: 1
profiles:
  UMF: {scene_anchors: [Unlisted]}
  CSP: {scene_anchors: [CSP Scene]}
  GENERIC: {scene_anchors: []}
routes:
  - id: test.high
    phase: precise
    priority: 20
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*.txt"}
    action: copy
    category: other
    target: "other/high/{suffix}"
  - id: test.low
    phase: precise
    priority: 10
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*"}
    action: ignore
    category: null
    target: null
  - id: test.fallback
    phase: fallback
    priority: 0
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*"}
    action: fallback
    category: other
    target: "other/fallback/{suffix}"
  - id: csp.ignore-non-alarm
    phase: fallback
    priority: 0
    profiles: [CSP]
    source: {scope: evidence, directory: "**", file: "*"}
    action: ignore
    category: null
    target: null
  - id: generic.fallback
    phase: fallback
    priority: 0
    profiles: [GENERIC]
    source: {scope: evidence, directory: "**", file: "*"}
    action: fallback
    category: log
    target: "logs/{suffix}"
"""
    )
    run = _classify(
        tmp_path,
        {
            "Outer/Scene/Unlisted/report.txt": "report",
            "Outer/Scene/Unlisted/data.bin": "data",
        },
        config=config,
    )

    report = _entry(run, "report.txt")
    assert (report.route_id, report.target) == ("test.high", "other/high/Unlisted/report.txt")
    assert len(run.ignored) == 1
    assert (run.ignored[0].source_relative, run.ignored[0].route_id) == ("Outer/Scene/Unlisted/data.bin", "test.low")


def test_phase_order_is_precise_then_ignore_then_fallback(tmp_path: Path) -> None:
    """前一阶段未命中后，ignore 必须优先于 fallback。"""
    config = loads_classification_config(
        """
version: 1
profiles:
  UMF: {scene_anchors: [Unlisted]}
  CSP: {scene_anchors: [CSP Scene]}
  GENERIC: {scene_anchors: []}
routes:
  - id: test.precise
    phase: precise
    priority: 10
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*.txt"}
    action: copy
    category: other
    target: "other/precise/{suffix}"
  - id: test.ignore
    phase: ignore
    priority: 100
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*"}
    action: ignore
    category: null
    target: null
  - id: test.fallback
    phase: fallback
    priority: 0
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*"}
    action: fallback
    category: other
    target: "other/fallback/{suffix}"
  - id: csp.ignore-non-alarm
    phase: fallback
    priority: 0
    profiles: [CSP]
    source: {scope: evidence, directory: "**", file: "*"}
    action: ignore
    category: null
    target: null
  - id: generic.fallback
    phase: fallback
    priority: 0
    profiles: [GENERIC]
    source: {scope: evidence, directory: "**", file: "*"}
    action: fallback
    category: log
    target: "logs/{suffix}"
"""
    )
    run = _classify(
        tmp_path,
        {
            "Outer/Scene/Unlisted/report.txt": "report",
            "Outer/Scene/Unlisted/data.bin": "data",
        },
        config=config,
    )

    report = _entry(run, "report.txt")
    assert (report.route_id, report.target) == ("test.precise", "other/precise/Unlisted/report.txt")
    assert len(run.ignored) == 1
    assert (run.ignored[0].source_relative, run.ignored[0].route_id) == ("Outer/Scene/Unlisted/data.bin", "test.ignore")


def test_deployed_config_contains_us1_us2_and_us3_routes_and_profile_defaults() -> None:
    """部署配置声明完整 anchors、US1-US3 路线及 CSP/GENERIC 可达默认行为。"""
    config = load_classification_config()

    assert config.profiles["UMF"].scene_anchors == tuple(
        sorted(
            {
                "Basic Information About the UMF",
                "Debugging Commands",
                "Equipment Status",
                "MESH Information (Problem)",
                "System Resources",
                "Operation Logs",
                "MML Configurations",
                "Performance Measurement Results",
                "MESH Application Metrics",
                "CHR Information",
                "Host Debugging Logs",
                "Host System Logs",
                "Service Logs (Problem)",
            }
        )
    )
    assert {route.id for route in config.routes} == {
        "alarm.umf",
        "alarm.csp",
        "ignore.zero",
        "umf.basic",
        "umf.debug",
        "umf.equipment-status",
        "umf.mesh-status",
        "umf.system-resources",
        "umf.operation-log",
        "umf.mml-file",
        "umf.mml-archive",
        "umf.kpi",
        "umf.mesh-metrics",
        "umf.service-logs",
        "umf.chr",
        "umf.host-debug",
        "umf.host-system",
        "umf.other",
        "umf.ignore-outside-scene",
        "csp.ignore-non-alarm",
        "generic.fallback",
    }


def test_duplicate_targets_are_stably_disambiguated_without_overwrite(tmp_path: Path) -> None:
    """不同来源映射到同一目标时保留首项，并用来源摘要稳定消歧第二项。"""
    first_source = f"{_scene()}/Equipment Status/duplicate.txt"
    second_source = f"{_scene()}/System Resources/duplicate.txt"
    run = _classify(tmp_path, {first_source: "first", second_source: "second"})

    entries = {entry.source_relative: entry for entry in run.entries}
    assert entries[first_source].target == "status/duplicate.txt"
    digest = conflict_digest("UMF", second_source, "")
    assert entries[second_source].original_target == "status/duplicate.txt"
    assert entries[second_source].target == f"status/duplicate__{digest}.txt"
    assert (run.data_dir / entries[first_source].target).read_bytes() == b"first"
    assert (run.data_dir / entries[second_source].target).read_bytes() == b"second"
    assert len(run.conflicts) == 1
    conflict = run.conflicts[0]
    assert (conflict.source_relative, conflict.original_target, conflict.target, conflict.status) == (
        second_source,
        "status/duplicate.txt",
        f"status/duplicate__{digest}.txt",
        "resolved",
    )
    assert conflict.digest == digest


def test_target_root_outside_manifest_allowlist_records_target_conflict(tmp_path: Path) -> None:
    """配置解析允许但 manifest 不允许发布的目标根必须局部失败且不落位。"""
    config = loads_classification_config(
        """
version: 1
profiles:
  UMF: {scene_anchors: [Scene]}
  CSP: {scene_anchors: [CSP Scene]}
  GENERIC: {scene_anchors: []}
routes:
  - id: test.config-root
    phase: precise
    priority: 10
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*"}
    action: copy
    category: config
    target: "config/{suffix}"
  - id: test.fallback
    phase: fallback
    priority: 0
    profiles: [UMF]
    source: {scope: scene, directory: "**", file: "*"}
    action: fallback
    category: other
    target: "other/{suffix}"
  - id: csp.ignore-non-alarm
    phase: fallback
    priority: 0
    profiles: [CSP]
    source: {scope: evidence, directory: "**", file: "*"}
    action: ignore
    category: null
    target: null
  - id: generic.fallback
    phase: fallback
    priority: 0
    profiles: [GENERIC]
    source: {scope: evidence, directory: "**", file: "*"}
    action: fallback
    category: log
    target: "logs/{suffix}"
"""
    )
    source = "Outer/Scene/Unlisted/settings.ini"
    run = _classify(tmp_path, {source: "config"}, config=config)

    assert run.entries == ()
    assert len(run.failures) == 1
    failure = run.failures[0]
    assert (failure.source_relative, failure.route_id, failure.error_code) == (
        source,
        "test.config-root",
        "target_conflict",
    )
    assert not (run.data_dir / "config").exists()


def test_classification_can_write_to_explicit_staging_output(tmp_path: Path) -> None:
    """证据根与分类输出根可分离，分类器不得把 staging 结果直接写入任务根。"""
    data_dir = tmp_path / "task"
    output_dir = data_dir / ".classification.staging"
    source = f"{_scene()}/Basic Information About the UMF/system.ini"
    _write(data_dir / ".main" / source, b"[app]\n")

    run = classify_main_evidence(data_dir, product="UMF", output_dir=output_dir)

    assert run.data_dir == output_dir
    assert run.entries[0].target == "basic/system.ini"
    assert (output_dir / "basic/system.ini").read_bytes() == b"[app]\n"
    assert not (data_dir / "basic").exists()


def test_log_supplement_without_product_uses_generic_audit_and_profile(tmp_path: Path) -> None:
    """日志补充包没有 product，必须使用 GENERIC profile 且审计 product 为 null。"""
    source = "supplement/node/app.log"
    run = _classify(tmp_path, {source: "log\n"}, product=None)

    assert run.entries[0].route_id == "generic.fallback"
    assert run.entries[0].product is None
    assert run.entries[0].target == f"logs/{source}"
    assert (run.data_dir / run.entries[0].target).read_bytes() == b"log\n"
