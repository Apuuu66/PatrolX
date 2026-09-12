# PatrolX Constitution

## Core Principles

### Offline First

PatrolX MUST consume pre-collected, uploaded, or locally placed archive packages only. The
system MUST NOT connect to inspected systems, collect telemetry online, or require access to
the customer environment. Inspection behavior MUST remain deterministic from the package and
declared parameters.

### One Package, One Task, One System

One archive package MUST map to exactly one inspection task and exactly one system inspection
context. Data, artifacts, rules, logs, and reports MUST be isolated by `task_id` and
`system_id`. Cross-system trend analysis MUST aggregate separately; it MUST NOT merge data
inside a task.

### Contract Driven

OpenAPI is the single source of truth for online API structure. `docs/api/openapi.yaml` MUST
be updated before or together with backend interface changes. Backend Pydantic/FastAPI schemas
and generated frontend API clients MUST remain synchronized with the contract. Breaking API
changes MUST be delivered under a new version prefix instead of changing the meaning of
existing `/api/v1` fields.

Contracted inspection output is also a public boundary. Existing `RuleResult`, `Metric`,
`Finding`, state, and field semantics MUST NOT be changed incompatibly. New inspection
capabilities MUST add rule codes, metric keys, or metadata rather than redefine existing
contract fields.

### Mode Isomorphism

Local mode and online mode MUST share the same inspectors, rule registry, package-processing
pipeline, inspection contracts, and output semantics. Local CLI execution MUST be capable of
producing the same contract JSON as API execution for the same package, except for execution
identity and timestamps. Product behavior MUST NOT be implemented only in one mode when it
belongs to the shared inspection domain.

### Inspector Plugin Architecture

Inspection capabilities MUST be implemented as registered inspectors/rules. The scheduler
MUST load and orchestrate rules through registry metadata rather than hardcoded business
logic. A new rule MUST be addable without changing core scheduling code. Rule registration
MUST declare complete metadata, inputs, outputs, version, description, and recommendation.

### Consumption Is Dependency

Rules MUST interact only through explicitly declared artifact keys. A rule MUST declare every
artifact it consumes in `inputs[]`; the executor MUST derive dependency edges from those keys.
Rules MUST NOT import, instantiate, or read another rule's implementation or undeclared
artifacts. Registration MUST reject circular, missing, or priority-invalid dependencies.

### Incremental Rerun

Rule results MUST be persisted at rule granularity so that one rule can be rerun without
rewriting unrelated results. When rerunning a rule, the executor MUST resolve and rerun only
its missing or stale dependency chain while reusing valid artifacts. A changed inspection
logic MUST increment `rule_version`; artifacts produced by an older version MUST be treated
as stale.

### Filter Before Analysis

Large data domains, especially logs, MUST be prepared into filtered or normalized artifacts
before analysis. Analysis rules MUST consume prepared artifacts instead of repeatedly scanning
raw packages. Single-rule debugging MUST be able to run the relevant preparation rules and the
target rule without executing every rule in the system.

### Idempotent and Traceable

Repeated processing of the same package MUST reuse or reproduce equivalent results. Nested
subpackages and extraction state MUST be deduplicated by checksum or manifest. Every finding
MUST retain source location, evidence, rule identity, and relevant values or thresholds
sufficient to trace the conclusion back to package data.

### Lightweight by Default

The default deployment MUST require no external database, broker, or cluster service. SQLite
plus file storage MUST be the default. The system MUST favor single-node, sequential execution
until correctness and architecture are stable. Optional PostgreSQL, concurrency, distributed
execution, or infrastructure MAY be introduced later only without breaking contracts or rule
isolation.

### Fault Tolerant

One malformed file, unsupported format, or failed artifact MUST NOT abort the entire task when
the task can continue safely. The failure MUST be represented in structured execution logs or
a rule result with an explicit status and reason. Silent swallowing of unexpected errors is
forbidden.

### Secure Extraction

All archive extraction MUST guard against path traversal, unsafe links, and archive bombs.
The system MUST enforce nested depth, file count, single-file size, total size, and path-safety
limits. Extraction limits MUST be recorded or reported rather than silently ignored. Original
packages MUST be treated as immutable input evidence.

## Additional Constraints

### Technology Baseline

The enforced baseline is Python 3.11+, FastAPI, Pydantic v2, React + TypeScript + Vite +
Ant Design + ECharts, SQLite, and file storage. Ruff MUST be used for lint/format support.
Jinja2 MUST generate HTML reports; PDF export and file download are out of scope. Additional
libraries such as pandas or pyarrow MAY be introduced when they materially reduce parsing or
analysis complexity. PostgreSQL and Docker are optional deployment extensions and MUST NOT
become default dependencies.

### Storage and Runtime Data

Uploaded original packages MUST remain under `uploads/`; runtime extraction, artifacts, rule
results, execution logs, and reports MUST remain under `output/`. Rule results MUST be stored
as contract JSON files at task/system/rule granularity. Runtime artifacts MUST stay out of
contract result documents. Deleting a task MUST cascade across both task locations.

### Time, Naming, and Logging

Persisted timestamps MUST use UTC and use `*_at` field names. Display MAY convert timezone.
Directory and package names MUST use lowercase singular wording. Rule codes MUST use lowercase
dot-delimited category names and MUST be filesystem-safe. Operational logs MUST use structured
JSON logging and include task/rule context where applicable.

### Finding Evidence

Finding evidence MUST be truncated to a safe display size while retaining the source file
needed for full-context investigation. Findings MUST prefer concrete, reproducible evidence
over generic summaries.

### Language Policy

All specification artifacts (`spec.md`, `plan.md`, `tasks.md`, checklists, and related
feature documents) MUST be written in Chinese. Identifiers, interface fields, code, file
paths, rule codes, and technical terms MUST remain in English. Inline comments, commit
messages, and documentation MUST also use Chinese. This policy ensures consistency with
the project's existing documentation language and reduces ambiguity for Chinese-speaking
maintainers.

## Development Workflow and Quality Gates

### Change Workflow

Large features, contract changes, data-model evolution, scheduler changes, and complex
interaction design MUST go through the Spec Kit flow: specify → plan → tasks → implement.
Small fixes MAY proceed directly with tests and verification. Documentation-only edits MAY be
made directly when they do not alter implementation semantics.

### Required Verification

Backend changes MUST pass `make lint` and `make test`. Full local pipeline changes MUST pass
`make verify` or an equivalent entry point. Inspection rule changes MUST be validated through
local rule execution and MUST have unit tests plus representative sample data. Interface
changes MUST include OpenAPI synchronization. Logic-changing inspector updates MUST increment
`rule_version`.

### Dual-Mode Compatibility

Changes affecting shared inspection behavior MUST preserve CLI/API output compatibility.
A change that intentionally changes contract output MUST update the contract, schema, tests,
and frontend consumers as one coherent change.

## Governance

This constitution supersedes conflicting implementation preferences, convenience shortcuts,
and ad-hoc agent instructions. Spec plans and tasks MUST cite compliance with these
principles when introducing or changing architecture, contracts, storage, execution, or
inspection behavior.

Amendments MUST be written into this file, reviewed explicitly, and versioned semantically:

- MAJOR: incompatible principle removal or redefinition.
- MINOR: new principle, materially expanded constraint, or new mandatory workflow.
- PATCH: clarification, typo, wording, or non-semantic refinement.

Reviewers and agents MUST verify constitution compliance before merge. A conflict between a
feature plan and this constitution MUST be resolved by changing the plan unless the project
formally amends this constitution first.

**Version**: 1.1.0 | **Ratified**: 2026-09-12 | **Last Amended**: 2026-09-12
