"""执行单元运行时的 product/package kind 传播测试。"""

import pickle
from pathlib import Path

import pytest

from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import PackageKind, Priority, Product, RuleCategory, RuleStatus, Severity
from app.services.unit_runtime import RuleContext, UnitKind, UnitRequest, execute_unit, make_result


def _log(_level: str, _message: str, _detail: dict | None = None) -> None:
    return None


def test_rule_context_and_request_carry_normalized_task_metadata(tmp_path: Path) -> None:
    ctx = RuleContext(
        task_id="task-context",
        data_dir=tmp_path,
        log=_log,
        product=" umf ",
        package_kind="inspection",
    )
    assert ctx.product == Product.UMF
    assert ctx.package_kind == PackageKind.INSPECTION

    request = UnitRequest(
        unit_kind=UnitKind.INSPECT,
        code="rule.context",
        owner_code="rule.context",
        task_id="task-context",
        data_dir=str(tmp_path),
        prepared_dir=str(tmp_path / "prepared"),
        product=None,
        package_kind="log_supplement",
    )
    restored = pickle.loads(pickle.dumps(request))
    assert restored == request
    assert restored.product is None
    assert restored.package_kind == "log_supplement"


@pytest.mark.parametrize("product", ["XYZ", "UMF2021", ""])
def test_rule_context_rejects_unknown_product(tmp_path: Path, product: str) -> None:
    """非法 product 不得静默保留为任意历史字符串。"""
    with pytest.raises(ValueError, match="product"):
        RuleContext(
            task_id="task-invalid-product",
            data_dir=tmp_path,
            log=_log,
            product=product,
        )


def test_rule_context_normalizes_legacy_umf2020_product(tmp_path: Path) -> None:
    """历史持久化值 UMF2020 只作为明确兼容值保留。"""
    ctx = RuleContext(
        task_id="task-legacy-product",
        data_dir=tmp_path,
        log=_log,
        product=" umf2020 ",
    )

    assert ctx.product == "UMF2020"


def test_worker_uses_request_metadata_despite_reverse_path_and_package_hints(tmp_path: Path) -> None:
    source = tmp_path / "UMF" / "inspection-package-umf.log"
    source.parent.mkdir(parents=True)
    source.write_text("payload", encoding="utf-8")
    captured: list[tuple[Product | None, PackageKind]] = []
    registry = RuleRegistry()

    def inspect(ctx: RuleContext) -> object:
        captured.append((ctx.product, ctx.package_kind))
        return make_result(registry.get("rule.context"), status=RuleStatus.PASS, summary="ok")

    registry.register(
        Inspector(
            code="rule.context",
            name="上下文传播",
            category=RuleCategory.OTHER,
            severity=Severity.LOW,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="验证 worker 只使用请求元数据",
            recommendation="无",
            source_patterns=[r"UMF/inspection-package-umf\.log"],
            run=inspect,
        )
    )
    request = UnitRequest(
        unit_kind=UnitKind.INSPECT,
        code="rule.context",
        owner_code="rule.context",
        task_id="task-worker",
        data_dir=str(tmp_path),
        prepared_dir=str(tmp_path / "prepared"),
        product="CSP",
        package_kind="inspection",
        files=("UMF/inspection-package-umf.log",),
    )

    outcome = execute_unit(request, registry)

    assert outcome.result is not None
    assert outcome.result.status == RuleStatus.PASS
    assert captured == [(Product.CSP, PackageKind.INSPECTION)]
