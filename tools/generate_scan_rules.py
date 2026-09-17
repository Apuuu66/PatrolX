#!/usr/bin/env python3
"""扫描解压目录，生成便于人工整改的 source_patterns 草稿。

工具只读取本地目录，不连接被检系统，也不修改解压目录。
默认按目录 + 文件名数字段泛化，输出 YAML 草稿；用户可直接修改正则后使用 validate 子命令回验。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

DIGIT_PLACEHOLDER = "\0"
RULE_CODE_PREFIX = "scan"


def list_files(source_dir: Path, excludes: set[Path] | None = None) -> list[str]:
    """列出 POSIX 相对路径；目录为空时报错。"""
    root = source_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"解压目录不存在或不是目录: {source_dir}")

    excluded = excludes or set()
    files: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path in excluded:
            continue
        files.append(relative)
    if not files:
        raise ValueError(f"解压目录中没有文件: {source_dir}")
    return sorted(files)


def _escape_segment(value: str) -> str:
    return re.escape(value)


def _generalize_filename(filename: str) -> str:
    """把文件名中的连续数字泛化为 \\d+，保留其他业务语义。"""
    replaced = re.sub(r"\d+", DIGIT_PLACEHOLDER, filename)
    escaped = re.escape(replaced)
    return escaped.replace(re.escape(DIGIT_PLACEHOLDER), r"\d+")


def _exact_pattern(relative_path: str) -> str:
    return f"^{_escape_segment(relative_path)}$"


def _file_pattern(directory: str, generalized_filename: str) -> str:
    if directory == ".":
        return f"^{generalized_filename}$"
    return f"^{_escape_segment(directory)}/{generalized_filename}$"


def _directory_pattern(directory: str) -> str:
    if directory == ".":
        return r"^[^/]+$"
    return f"^{_escape_segment(directory)}/.*$"


def _build_rules(files: list[str], granularity: str) -> list[dict[str, Any]]:
    """按指定粒度构建规则；matched_files 用于人工核对，不参与运行时匹配。"""
    if granularity == "file":
        grouped: dict[str, list[str]] = {_exact_pattern(file): [file] for file in files}
    elif granularity == "directory":
        grouped = defaultdict(list)
        for file in files:
            directory = Path(file).parent.as_posix()
            grouped[_directory_pattern(directory)].append(file)
    elif granularity == "digit":
        grouped = defaultdict(list)
        for file in files:
            path = Path(file)
            grouped[_file_pattern(path.parent.as_posix(), _generalize_filename(path.name))].append(file)
    else:
        raise ValueError(f"不支持的粒度: {granularity}")

    rules: list[dict[str, Any]] = []
    for index, (pattern, matched_files) in enumerate(sorted(grouped.items()), start=1):
        rules.append(
            {
                "code": f"{RULE_CODE_PREFIX}.{index:03d}",
                "source_patterns": [pattern],
                "matched_files": sorted(matched_files),
            }
        )
    return rules


def generate_rules(
    source_dir: Path,
    granularity: str = "digit",
    excludes: set[Path] | None = None,
) -> dict[str, Any]:
    """生成可编辑的扫描规则草稿。"""
    files = list_files(source_dir, excludes)
    return {
        "version": 1,
        "source_dir": source_dir.resolve().name,
        "granularity": granularity,
        "rules": _build_rules(files, granularity),
    }


def _load_rules(path: Path) -> list[dict[str, Any]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取规则文件: {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError("规则文件必须是包含 rules 列表的 YAML 对象")

    rules: list[dict[str, Any]] = []
    for index, item in enumerate(payload["rules"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"rules[{index}] 必须是对象")
        code = item.get("code")
        patterns = item.get("source_patterns")
        if not isinstance(code, str) or not code.strip():
            raise ValueError(f"rules[{index}].code 必须是非空字符串")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f"rules[{index}].source_patterns 必须是非空数组")
        rules.append({"code": code.strip(), "source_patterns": patterns})
    return rules


def validate_rules(source_dir: Path, rules_path: Path) -> dict[str, Any]:
    """回验人工修改后的规则，输出命中、漏配和非法正则。"""
    excludes = {rules_path.resolve()} if rules_path.exists() else None
    files = list_files(source_dir, excludes)
    file_set = set(files)
    rules = _load_rules(rules_path)

    matched_by_file: dict[str, list[str]] = defaultdict(list)
    invalid_patterns: list[dict[str, str]] = []
    rule_reports: list[dict[str, Any]] = []

    for rule in rules:
        matched: list[str] = []
        for pattern_index, raw_pattern in enumerate(rule["source_patterns"], start=1):
            if not isinstance(raw_pattern, str) or not raw_pattern.strip():
                invalid_patterns.append(
                    {
                        "rule_code": rule["code"],
                        "pattern_index": str(pattern_index),
                        "pattern": str(raw_pattern),
                        "error": "正则必须是非空字符串",
                    }
                )
                continue
            try:
                compiled = re.compile(raw_pattern)
            except re.error as exc:
                invalid_patterns.append(
                    {
                        "rule_code": rule["code"],
                        "pattern_index": str(pattern_index),
                        "pattern": raw_pattern,
                        "error": str(exc),
                    }
                )
                continue

            current = [file for file in files if compiled.fullmatch(file)]
            matched.extend(current)
            for file in current:
                matched_by_file[file].append(rule["code"])

        rule_reports.append(
            {
                "code": rule["code"],
                "matched_files": sorted(set(matched)),
                "match_count": len(set(matched)),
            }
        )

    unmatched_files = sorted(file_set - set(matched_by_file))
    return {
        "summary": {
            "total_files": len(files),
            "matched_files": len(matched_by_file),
            "unmatched_files": unmatched_files,
            "invalid_patterns": invalid_patterns,
        },
        "rules": rule_reports,
    }


def _print_validation_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        f"校验完成: {summary['matched_files']}/{summary['total_files']} 个文件命中，"
        f"{len(summary['unmatched_files'])} 个漏配，{len(summary['invalid_patterns'])} 个非法正则"
    )
    if summary["unmatched_files"]:
        print("漏配文件:")
        for file in summary["unmatched_files"]:
            print(f"  - {file}")
    if summary["invalid_patterns"]:
        print("非法正则:")
        for item in summary["invalid_patterns"]:
            print(f"  - {item['rule_code']} 第 {item['pattern_index']} 条: {item['error']}")


def _write_output(payload: dict[str, Any], output: Path | None, as_json: bool) -> None:
    text = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if as_json
        else yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    )
    if output is None or output == Path("-"):
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"已生成: {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="扫描解压目录并生成可整改的 source_patterns 草稿")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="扫描文件并生成规则草稿")
    generate.add_argument("--source-dir", type=Path, required=True, help="解压目录")
    generate.add_argument("--output", type=Path, help="输出 YAML；省略时输出 stdout")
    generate.add_argument(
        "--granularity",
        choices=("digit", "directory", "file"),
        default="digit",
        help="digit=按目录+文件名数字段泛化，directory=按目录泛化，file=每个文件精确匹配",
    )
    generate.add_argument("--json", action="store_true", help="以 JSON 输出")

    validate = subparsers.add_parser("validate", help="校验人工修改后的规则")
    validate.add_argument("--source-dir", type=Path, required=True, help="解压目录")
    validate.add_argument("--rules", type=Path, required=True, help="规则 YAML 文件")
    validate.add_argument("--json", action="store_true", help="以 JSON 输出")
    return parser


def _expand_cli_path(path: Path) -> Path:
    """展开 CLI 路径中的用户目录；Windows/Unix 分隔符交给 pathlib 处理。"""
    return path.expanduser()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.source_dir = _expand_cli_path(args.source_dir)
    if args.command == "generate" and args.output is not None:
        args.output = _expand_cli_path(args.output)
    if args.command == "validate":
        args.rules = _expand_cli_path(args.rules)
    try:
        if args.command == "generate":
            excludes = {args.output.resolve()} if args.output and args.output != Path("-") else None
            payload = generate_rules(args.source_dir, args.granularity, excludes)
            _write_output(payload, args.output, args.json)
        else:
            payload = validate_rules(args.source_dir, args.rules)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                _print_validation_report(payload)
        return 0
    except (OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
