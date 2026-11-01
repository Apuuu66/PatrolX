"""执行单元运行时的 product/package kind 传播测试。"""

import pickle
from pathlib import Path

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
        product="CSP",
        package_kind="inspection",
    )
    restored = pickle.loads(pickle.dumps(request))
    assert restored == request
    assert restored.product == "CSP"
    assert restored.package_kind == "inspection"


def test_worker_uses_request_product_not_path_or_package_name(tmp_path: Path) -> None:
    source = tmp_path / "UMF" / "package-umf.log"
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
            source_patterns=[r"UMF/package-umf\.log"],
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
        files=("UMF/package-umf.log",),
    )

    outcome = execute_unit(request, registry)

    assert outcome.result is not None
    assert outcome.result.status == RuleStatus.PASS
    assert captured == [(Product.CSP, PackageKind.INSPECTION)]
