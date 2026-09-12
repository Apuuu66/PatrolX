# Implementation Plan: System Baseline

**Branch**: `001-system-baseline` | **Date**: 2026-09-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-system-baseline/spec.md`

## Summary

PatrolX already implements the core offline inspection flow. This baseline plan therefore does
not introduce a new product capability. It formalizes the existing business baseline and
defines the technical approach for validating, hardening, and documenting the flow: one
pre-collected package becomes one task and one system inspection; archive contents are safely
classified and extracted; rules run through a dependency-aware registry; results, findings,
artifacts, logs, and reports are retained in a traceable runtime layout; and local and online
experiences share the same inspection semantics.

The implementation approach is continuity, not a rewrite. Existing architecture is retained,
while work in the task phase will validate contract consistency, dual-mode behavior, rerun
behavior, extraction safety, evidence traceability, and report usability against this baseline
spec.

## Technical Context

**Language/Version**: Python 3.11+ (current local execution uses Python 3.12)

**Primary Dependencies**: FastAPI, Pydantic v2, React 18+, TypeScript, Vite, Ant Design,
ECharts, Jinja2, structlog, pytest, Ruff

**Storage**: SQLite for lightweight task metadata; files under `uploads/` and `output/` for
packages, extraction, artifacts, rule results, logs, and reports

**Testing**: pytest for backend and contract tests; Ruff for lint and format checks; local
pipeline verification through `make verify`; frontend build through `make web-build`

**Target Platform**: Internal desktop-browser users and single-node local/server deployment

**Project Type**: Modular monolith with local CLI pipeline, FastAPI service, and React web UI

**Performance Goals**: Baseline correctness first. A supported local package should complete
the full pipeline without manual intervention. No new concurrency or throughput target is
introduced in this baseline.

**Constraints**:

- Offline-only inspection: no connection to inspected systems.
- One package = one task = one system.
- Local and online modes share inspection behavior and contract output.
- Single-node, sequential execution is the baseline.
- SQLite + files are the default storage.
- Rules interact only through declared artifacts.
- Extraction must enforce path, link, depth, count, size, and total-size safety.
- Findings must retain source location and evidence.
- Task deletion must remove both retained input and generated output.

**Scale/Scope**: Internal team usage; multiple sequential tasks; the baseline covers the
existing offline pipeline, online API/Web surface, six inspection categories, rule rerun,
reporting, logs, and task lifecycle. Cross-task trend analysis, online rule editing, PDF
export, report download, distributed execution, and mobile support are out of scope.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Evidence / Impact |
| --- | --- | --- |
| Offline First | PASS | Baseline consumes pre-collected packages only. |
| One Package, One Task, One System | PASS | Task/system isolation is preserved. |
| Contract Driven | PASS | OpenAPI remains the API contract source; output contracts are unchanged. |
| Mode Isomorphism | PASS | CLI/API consistency remains a required validation. |
| Inspector Plugin Architecture | PASS | Rules remain registry-based; no scheduler hardcoding is added. |
| Consumption Is Dependency | PASS | Rules consume only declared artifacts. |
| Incremental Rerun | PASS | Target-rule rerun and artifact versioning are retained. |
| Filter Before Analysis | PASS | Log analysis remains artifact-based. |
| Idempotent and Traceable | PASS | Extraction manifest, source locations, evidence, and rule metadata are preserved. |
| Lightweight by Default | PASS | SQLite + files and sequential execution remain the default. |
| Fault Tolerant | PASS | Per-file/category failures produce skip/error results or structured logs. |
| Secure Extraction | PASS | Extraction guards and resource limits are mandatory. |

The plan introduces no Constitution violations. It does not add an external dependency, new
persistence model, online collection capability, rule coupling, or parallel/distributed
scheduler.

## Project Structure

### Documentation (this feature)

```text
specs/001-system-baseline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output; not created by $speckit-plan
```

### Source Code (repository root)

```text
app/
├── main.py
├── cli.py
├── api/
├── core/
│   ├── archive.py
│   ├── classify.py
│   ├── config.py
│   ├── dicts.py
│   ├── logging.py
│   └── metrics.py
├── models/
├── services/
│   ├── artifacts.py
│   ├── executor.py
│   ├── report.py
│   ├── store.py
│   └── tasks.py
├── inspectors/
│   ├── base.py
│   ├── registry.py
│   ├── pkg.py
│   ├── log/
│   ├── kpi/
│   ├── traffic/
│   ├── alarm/
│   ├── config/
│   └── resource/
└── reports/

web/
└── src/
    ├── api/
    ├── components/
    ├── hooks/
    ├── layouts/
    └── pages/

deploy/
└── config/
    ├── classify_rules.yaml
    └── dicts.yaml

tests/
├── fixtures/
├── test_api.py
├── test_archive.py
├── test_contract.py
├── test_consistency.py
├── test_executor.py
├── test_pipeline.py
├── test_rules.py
└── ...
```

**Structure Decision**: Keep the existing modular monolith. Backend logic stays in `app/`,
frontend in `web/`, configuration in `deploy/config/`, and tests/fixtures in `tests/`. No new
top-level project, service, or package boundary is introduced by this baseline.

## Complexity Tracking

No Constitution violations or unjustified complexity were introduced.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| N/A | N/A | N/A |
