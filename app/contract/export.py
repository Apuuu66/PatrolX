"""python build.py contract：由 FastAPI 生成 OpenAPI，与 docs/api/openapi.yaml 双向校验/导出。

用法：
    python -m app.contract.export            # 校验模式：结构与契约一致则通过
    python -m app.contract.export --update   # 覆写 docs/api/openapi.yaml 为 FastAPI 生成结果
"""

import sys
from pathlib import Path

import yaml

from app.main import create_app

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.yaml"


def generate_openapi() -> dict:
    return create_app().openapi()


def _path_method_sets(spec: dict) -> dict[str, set[str]]:
    return {path: set(methods) for path, methods in spec.get("paths", {}).items()}


def diff_contracts(generated: dict, contract: dict) -> list[str]:
    issues: list[str] = []
    gen_paths = _path_method_sets(generated)
    con_paths = _path_method_sets(contract)
    for path in sorted(set(gen_paths) | set(con_paths)):
        gm, cm = gen_paths.get(path, set()), con_paths.get(path, set())
        if gm != cm:
            issues.append(f"path {path}: FastAPI={sorted(gm)} 契约={sorted(cm)}")
    for path in sorted(gen_paths):
        for method in gen_paths[path]:
            gen_op = generated["paths"][path][method]
            con_op = contract["paths"][path].get(method)
            if con_op and gen_op.get("operationId") != con_op.get("operationId"):
                issues.append(
                    f"{method.upper()} {path}: operationId "
                    f"FastAPI={gen_op.get('operationId')} 契约={con_op.get('operationId')}"
                )
    return issues


def main() -> int:
    generated = generate_openapi()
    update = "--update" in sys.argv
    if not CONTRACT_PATH.exists() or update:
        CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT_PATH.write_text(yaml.safe_dump(generated, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"已导出契约: {CONTRACT_PATH}")
        return 0

    contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    issues = diff_contracts(generated, contract)
    if issues:
        print("契约与实现不一致：")
        for issue in issues:
            print(f"  - {issue}")
        print("提示：先更新 docs/api/openapi.yaml（契约审查），或执行 --update 以实现为准覆写。")
        return 1
    print("契约与实现一致: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
