"""分类配置严格 schema、默认行为与冲突校验测试。"""

from pathlib import Path

import pytest

from app.services.extraction.config import (
    ClassificationConfigError,
    load_classification_config,
    loads_classification_config,
)


def _profile_block(key: str, anchors: list[str] | None = None) -> str:
    """生成测试用 profile YAML 片段。"""
    values = anchors if anchors is not None else (["Anchor"] if key != "GENERIC" else [])
    items = ", ".join(f'"{value}"' for value in values)
    return f"{key}: {{scene_anchors: [{items}]}}"


def _valid_yaml() -> str:
    """返回包含三个 profile 且默认行为均可达的最小配置。"""
    return f"""
version: 1
profiles:
  {_profile_block("UMF", ["UMF Root"])}
  {_profile_block("CSP", ["CSP Root"])}
  {_profile_block("GENERIC")}
routes:
  - id: umf.root
    phase: precise
    priority: 100
    profiles: [UMF]
    source:
      scope: scene
      directory: "UMF Root/**"
      file: "*"
      capture_root: "UMF Root"
    action: copy
    category: config
    target: "basic/{{suffix}}"
  - id: umf.fallback
    phase: fallback
    priority: 10
    profiles: [UMF]
    source:
      scope: scene
      directory: "**"
      file: "*"
    action: fallback
    category: other
    target: "other/{{suffix}}"
  - id: csp.ignore
    phase: fallback
    priority: 0
    profiles: [CSP]
    source:
      scope: evidence
      directory: "**"
      file: "*"
    action: ignore
    category: null
    target: null
  - id: generic.fallback
    phase: fallback
    priority: 0
    profiles: [GENERIC]
    source:
      scope: evidence
      directory: "**"
      file: "*"
    action: fallback
    category: log
    target: "logs/{{suffix}}"
"""


def test_valid_config_normalizes_profiles_and_routes() -> None:
    """有效配置返回三个 profile，并将大小写不敏感字段规范化为内部枚举。"""
    config = loads_classification_config(_valid_yaml())

    assert config.version == 1
    assert set(config.profiles) == {"UMF", "CSP", "GENERIC"}
    assert config.profiles["UMF"].scene_anchors == ("UMF Root",)
    assert [route.id for route in config.routes] == [
        "umf.root",
        "umf.fallback",
        "csp.ignore",
        "generic.fallback",
    ]
    assert config.routes[0].profiles == ("UMF",)
    assert config.fingerprint


def test_top_level_keys_are_strict() -> None:
    """顶层键必须完整且只允许 version/profiles/routes。"""
    text = f"{_valid_yaml()}\nextra: true\n"

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    assert exc_info.value.code == "invalid_classification_config"
    assert exc_info.value.path == ""
    assert exc_info.value.route_id is None
    assert "未知顶层字段" in exc_info.value.message


def test_missing_top_level_key_fails() -> None:
    """缺少顶层键时配置整体失败。"""
    text = _valid_yaml().replace("version: 1\n", "", 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    assert exc_info.value.code == "invalid_classification_config"
    assert "缺少顶层字段" in exc_info.value.message


@pytest.mark.parametrize(
    "yaml_text",
    [
        """
        version: 1
        version: 2
        profiles: {}
        routes: []
        """,
        """
        version: 1
        profiles:
          UMF: {scene_anchors: [A]}
          UMF: {scene_anchors: [B]}
        routes: []
        """,
    ],
)
def test_duplicate_yaml_keys_fail(yaml_text: str) -> None:
    """顶层或 profile 的重复 YAML key 必须被拒绝。"""
    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(yaml_text)

    assert exc_info.value.code == "invalid_classification_config"
    assert "重复" in exc_info.value.message


def test_unknown_action_fails_with_route_detail() -> None:
    """未知动作必须携带 route 与字段路径。"""
    text = _valid_yaml().replace("action: copy", "action: sniff", 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    error = exc_info.value
    assert error.code == "invalid_classification_config"
    assert error.path == "routes[0].action"
    assert error.route_id == "umf.root"
    assert "未知动作" in error.message


def test_non_ignore_route_requires_known_category() -> None:
    """普通 route 的 category 必须来自冻结业务分类集合。"""
    text = _valid_yaml().replace("category: config", "category: network", 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    error = exc_info.value
    assert error.path == "routes[0].category"
    assert error.route_id == "umf.root"
    assert "非法业务分类" in error.message


def test_ignore_route_requires_null_category() -> None:
    """ignore route 不得携带业务分类。"""
    text = _valid_yaml().replace(
        "    action: ignore\n    category: null\n    target: null",
        "    action: ignore\n    category: other\n    target: null",
        1,
    )

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    error = exc_info.value
    assert error.path == "routes[2].category"
    assert error.route_id == "csp.ignore"
    assert "ignore" in error.message


def test_target_first_segment_match_allowlist() -> None:
    """目标首段不在 allowlist 时必须按稳定字段路径报错。"""
    text = _valid_yaml().replace('target: "basic/{suffix}"', 'target: "payload/{suffix}"', 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    error = exc_info.value
    assert error.code == "invalid_classification_config"
    assert error.path == "routes[0].target"
    assert error.route_id == "umf.root"
    assert "目标首段不在 allowlist" in error.message
    assert "payload" in error.message


def test_target_traversal_is_rejected() -> None:
    """相对目标包含 .. 时不得绕过工作根边界。"""
    text = _valid_yaml().replace('target: "basic/{suffix}"', 'target: "basic/../{suffix}"', 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    assert exc_info.value.path == "routes[0].target"
    assert "目标路径非法" in exc_info.value.message


def test_unknown_target_variable_is_rejected() -> None:
    """目标模板中的未知变量必须在启动时失败。"""
    text = _valid_yaml().replace('target: "basic/{suffix}"', 'target: "basic/{device}/{suffix}"', 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    assert exc_info.value.path == "routes[0].target"
    assert "未知目标变量" in exc_info.value.message


def test_unknown_route_profile_fails() -> None:
    """route 只能引用已冻结 profile。"""
    text = _valid_yaml().replace("profiles: [UMF]", "profiles: [UNKNOWN]", 1)

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    error = exc_info.value
    assert error.path == "routes[0].profiles[0]"
    assert error.route_id == "umf.root"
    assert "未知 profile" in error.message


def test_every_used_profile_requires_reachable_default() -> None:
    """移除 catch-all fallback 后，UMF profile 必须被判定为默认行为不可达。"""
    text = _valid_yaml()
    start = text.index("  - id: umf.fallback")
    end = text.index("  - id: csp.ignore")
    text = text[:start] + text[end:]

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(text)

    error = exc_info.value
    assert error.path == "profiles.UMF"
    assert error.route_id is None
    assert "默认行为不可达" in error.message


def test_selection_include_overlap_with_different_services_fails() -> None:
    """同一成员命中不同 service 的 include 时必须整体拒绝。"""
    selection_route = """
  - id: select.route
    phase: precise
    priority: 50
    profiles: [UMF]
    source:
      scope: evidence
      directory: "**"
      file: "*.zip"
    action: select_and_decompress
    category: chr
    target: "chr/{member}"
    selection:
      include:
        - pattern: "**/*.log"
          service: ALPHA
        - pattern: "**/shared.log"
          service: BETA
      exclude: []
"""

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(_valid_yaml() + selection_route)

    error = exc_info.value
    assert error.code == "invalid_classification_config"
    assert error.path == "routes[4].selection.include"
    assert error.route_id == "select.route"
    assert "不同 service" in error.message


def test_load_uses_default_configuration_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未指定路径时从当前配置目录读取 classify_rules.yaml。"""
    from app.core.config import settings

    config_file = tmp_path / "classify_rules.yaml"
    config_file.write_text(_valid_yaml(), encoding="utf-8")
    monkeypatch.setattr(settings, "config_dir", tmp_path)

    assert load_classification_config().version == 1


def _route_yaml(
    route_id: str,
    phase: str,
    priority: int,
    profiles: str,
    scope: str,
    directory: str,
    file_name: str,
    *,
    action: str = "copy",
    category: str = "config",
    target: str = '"basic/{suffix}"',
    capture_root: str | None = None,
) -> str:
    """生成一条测试 route。"""
    capture = "" if capture_root is None else f'\n      capture_root: "{capture_root}"'
    return f"""
  - id: {route_id}
    phase: {phase}
    priority: {priority}
    profiles: [{profiles}]
    source:
      scope: {scope}
      directory: \"{directory}\"
      file: \"{file_name}\"{capture}
    action: {action}
    category: {category}
    target: {target}
"""


def _config_with_routes(routes: list[str]) -> str:
    """在默认可达配置后追加测试 route；route 顺序不得影响静态校验。"""
    return _valid_yaml() + "".join(routes)


@pytest.mark.parametrize(
    ("left_file", "right_file"),
    [
        ("*", "a?"),
        ("a?", "ab"),
        ("a*", "*b"),
    ],
)
def test_same_phase_priority_and_overlapping_file_globs_fail(
    left_file: str,
    right_file: str,
) -> None:
    """`*` 与 `?` 的静态交集必须通过 ε-NFA 乘积识别。"""
    routes = [
        _route_yaml("left", "precise", 50, "UMF", "scene", "UMF Root", left_file),
        _route_yaml("right", "precise", 50, "UMF", "scene", "UMF Root", right_file),
    ]

    with pytest.raises(ClassificationConfigError) as exc_info:
        loads_classification_config(_config_with_routes(routes))

    error = exc_info.value
    assert error.code == "invalid_classification_config"
    assert error.path == "routes"
    assert error.route_id == "left"
    assert error.conflict_routes == ("left", "right")
    assert error.phase == "precise"
    assert error.priority == 50
    assert error.profile_intersection == ("UMF",)
    assert "pattern 重叠" in error.message


def test_double_star_and_scene_evidence_equivalent_prefix_overlap() -> None:
    """scene 必须隐式补 `**/`，并与 evidence 的任意前缀和零段 `**` 重叠。"""
    routes = [
        _route_yaml(
            "scene.left",
            "precise",
            50,
            "UMF",
            "scene",
            "UMF Root/**",
            "*",
            target='"basic/{suffix}"',
        ),
        _route_yaml(
            "evidence.right",
            "precise",
            50,
            "UMF",
            "evidence",
            "**/wrapper/UMF Root",
            "child.txt",
            target='"config/{suffix}"',
        ),
    ]

    with pytest.raises(ClassificationConfigError, match="pattern 重叠"):
        loads_classification_config(_config_with_routes(routes))


def test_double_star_zero_segments_matches_direct_parent() -> None:
    """`dir/**` 必须能匹配 dir 下的普通文件，即 `**` 可匹配零个目录段。"""
    routes = [
        _route_yaml("left", "precise", 50, "UMF", "evidence", "a/**", "*"),
        _route_yaml("right", "precise", 50, "UMF", "evidence", "a", "file.txt"),
    ]

    with pytest.raises(ClassificationConfigError, match="pattern 重叠"):
        loads_classification_config(_config_with_routes(routes))


@pytest.mark.parametrize(
    ("left_directory", "left_file", "right_directory", "right_file"),
    [
        ("a", "??", "a", "b"),
        ("a", "*", "b", "*"),
        ("a/**", "*", "b/**", "*"),
    ],
)
def test_disjoint_patterns_do_not_conflict(
    left_directory: str,
    left_file: str,
    right_directory: str,
    right_file: str,
) -> None:
    """字面段、单字符 `?` 和不同根目录不可重叠时配置应保持有效。"""
    routes = [
        _route_yaml("left", "precise", 50, "UMF", "evidence", left_directory, left_file),
        _route_yaml("right", "precise", 50, "UMF", "evidence", right_directory, right_file),
    ]

    config = loads_classification_config(_config_with_routes(routes))

    assert {route.id for route in config.routes} >= {"left", "right"}


def test_overlap_without_profile_intersection_is_allowed() -> None:
    """不同 profile 的同优先级 pattern 即使重叠也互不冲突。"""
    routes = [
        _route_yaml("left", "precise", 50, "UMF", "evidence", "a", "*"),
        _route_yaml("right", "precise", 50, "CSP", "evidence", "a", "*"),
    ]

    config = loads_classification_config(_config_with_routes(routes))

    assert {route.id for route in config.routes} >= {"left", "right"}


def test_overlap_with_different_priority_is_allowed() -> None:
    """同 phase 不同 priority 的重叠由高优先级获胜，不属于配置冲突。"""
    routes = [
        _route_yaml("left", "precise", 100, "UMF", "evidence", "a", "*"),
        _route_yaml("right", "precise", 50, "UMF", "evidence", "a", "*"),
    ]

    config = loads_classification_config(_config_with_routes(routes))

    assert {route.id for route in config.routes} >= {"left", "right"}


def test_alarm_overlapping_ignore_phase_is_not_static_conflict() -> None:
    """告警与 ignore 位于不同 phase；配置校验不得把二者误判为同优先级冲突。"""
    alarm = _route_yaml(
        "alarm.route",
        "alarm",
        1000,
        "CSP",
        "evidence",
        "**/0/Alarm Data/**",
        "*",
        action="expand_recursive",
        category="alarm",
        target='"alarm/{member}"',
        capture_root="Alarm Data",
    )
    ignore = _route_yaml(
        "zero.ignore",
        "ignore",
        0,
        "CSP",
        "evidence",
        "**/0/**",
        "*",
        action="ignore",
        category="null",
        target="null",
    )

    config = loads_classification_config(_config_with_routes([alarm, ignore]))

    assert {route.id for route in config.routes} >= {"alarm.route", "zero.ignore"}
