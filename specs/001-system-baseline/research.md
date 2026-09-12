# Research: System Baseline

## 1. Runtime Architecture

**Decision**: Keep the current modular monolith with local CLI, FastAPI service, React web UI,
and shared inspector/service/core layers.

**Rationale**: The baseline capability is already cohesive. Splitting services or adding a
separate orchestration system would increase deployment and contract complexity without a new
business need.

**Alternatives considered**:

- Rebuild as separate backend/frontend packages: rejected because it adds repository and
  deployment complexity without improving the current user flows.
- Introduce a task queue/worker service: rejected because sequential single-node execution is
  the baseline and correctness must be stabilized first.
- Embed business rules in the scheduler: rejected by Constitution; it would break inspector
  extensibility.

## 2. Input Model

**Decision**: Preserve the one-package/one-task/one-system model.

**Rationale**: It provides clear isolation, traceability, and simple deletion semantics. It
also gives future cross-task trends a stable `system_id` grouping model.

**Alternatives considered**:

- Multi-package tasks: rejected for baseline because ownership and failure attribution become
  ambiguous.
- Global package registry without task isolation: rejected because it weakens traceability and
  lifecycle deletion.

## 3. Extraction and Classification

**Decision**: Continue name-rule-based classification through `deploy/config/classify_rules.yaml`,
with safe extraction, category directories, checksum manifest, and nested-package deduplication.

**Rationale**: Real customer package names vary. A configurable rule table allows new formats to
be supported without changing core extraction logic.

**Alternatives considered**:

- Hardcode known package layouts: rejected because it reduces extensibility.
- Immediately extract every nested archive: rejected because it does unnecessary work and can
  increase exposure to archive bombs.
- Infer category only from directory names: rejected because real package directory names are
  natural language and not stable category enums.

## 4. Execution Model

**Decision**: Keep P0 preparation, P1 basic inspection, and P2 advanced analysis with
dependency edges derived from declared artifact consumption.

**Rationale**: This supports fast single-rule debugging, artifact reuse, and predictable
ordering without direct rule-to-rule imports.

**Alternatives considered**:

- Static dependency lists in scheduler code: rejected because rules would not be independently
  extensible.
- Full rerun for every rule change: rejected because it is wasteful and slows rule iteration.
- Same-priority dependency graphs: rejected by Constitution because they complicate ordering
  and can introduce cycles.

## 5. Rule Contract

**Decision**: Continue registry metadata plus Pydantic-style result contracts. Every rule
declares code, version, category, priority, inputs, outputs, description, recommendation, and
severity. `pass`/`warn`/`fail` must satisfy declared metrics; `skip`/`error` are exempt from
metric contract validation but must explain their state.

**Rationale**: Stable metadata and metric keys allow the UI and future trend features to consume
results without coupling to rule internals.

**Alternatives considered**:

- Free-form rule output: rejected because the frontend would need rule-specific parsing.
- Contract only on API response: rejected because CLI must share the same semantics.
- In-code rule chaining: rejected because it violates inspector isolation.

## 6. Storage Layout

**Decision**: Retain SQLite for lightweight metadata and files under `uploads/`/`output/` for
packages, extraction, artifacts, rule results, logs, and reports.

**Rationale**: This preserves zero-install operation and makes every inspection artifact directly
inspectable. It also allows rule results to be updated independently.

**Alternatives considered**:

- Store all findings and metrics in SQLite: rejected because it increases schema customization
  and weakens file-oriented task lifecycle management.
- External object store or database service: rejected for baseline because it violates
  lightweight default deployment.
- Single monolithic JSON result file: rejected because it prevents independent rule updates.

## 7. Report

**Decision**: Continue server-rendered HTML reports for online preview. PDF and download remain
out of scope.

**Rationale**: HTML is already part of the baseline and is sufficient for internal review. The
Web UI can provide navigation while the report remains a human-readable aggregate.

**Alternatives considered**:

- Add PDF export: rejected because it is explicitly out of scope.
- Recreate the report fully in frontend charts only: rejected because a retained HTML report is
  useful for historical review and does not require an active frontend session.

## 8. Frontend

**Decision**: Preserve the current React/TypeScript/Ant Design/ECharts implementation and
contract-generated API client.

**Rationale**: The existing pages already cover tasks, rules, reports, logs, inspectors, and
dictionaries. Rebuilding them would risk regressions without changing business value.

**Alternatives considered**:

- Mobile-first UI: rejected because desktop is the target usage.
- Handwritten API calls: rejected because they drift from OpenAPI.
- A separate UI for local mode: rejected because mode isomorphism is a baseline requirement.

## 9. Quality and Verification

**Decision**: Use pytest, Ruff, contract export, local pipeline verification, and existing
sample fixtures. Add baseline-specific checks only where current tests do not already cover
traceability, skip reasons, rerun, deletion, or dual-mode consistency.

**Rationale**: The code already has focused tests. The baseline should strengthen verification
without duplicating the suite.

**Alternatives considered**:

- Manual-only validation: rejected because baseline semantics must be repeatable.
- Require a real internal customer package for every test: rejected because unavailable data
  would block automated verification; sanitized fixtures should represent real structure.
- UI screenshot tests as the sole source of validation: rejected because they do not verify
  contract and executor semantics.

## 10. Observability

**Decision**: Retain structured logging, task execution logs, health endpoint, and Prometheus
metrics.

**Rationale**: Execution traceability is required for package processing, rule failures, and
report generation.

**Alternatives considered**:

- Console-only logging: rejected because task history must be inspectable after execution.
- External tracing backend: rejected because it is not a baseline dependency.
