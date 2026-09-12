# API Contract: System Baseline

The authoritative interface is already defined in
[`docs/api/openapi.yaml`](../../../docs/api/openapi.yaml). This document records the baseline
behavior that the OpenAPI contract and implementation must continue to satisfy.

## General Contract Rules

- API paths remain versioned under `/api/v1`.
- Resource responses return the resource JSON directly.
- Creation/rerun operations use accepted-response semantics with a location for polling.
- Errors use the established `{code, message, detail}` error shape.
- List responses use pagination and return a total.
- Breaking changes require a new version, not a semantic change to `/api/v1`.
- Generated frontend clients must remain synchronized with OpenAPI.

## Baseline Endpoints

| Capability | Method and Path | Baseline Requirement |
| --- | --- | --- |
| Health check | `GET /healthz` | Reports service liveness. |
| Metrics | `GET /metrics` | Exposes Prometheus-compatible operational metrics. |
| Create task | `POST /api/v1/tasks` | Accepts one package; returns accepted response and polling location. |
| List tasks | `GET /api/v1/tasks` | Returns paginated task summaries and total. |
| Task detail | `GET /api/v1/tasks/{task_id}` | Returns task status, stats, and system summary. |
| Delete task | `DELETE /api/v1/tasks/{task_id}` | Removes task input and output as one lifecycle unit. |
| Rerun rules | `POST /api/v1/tasks/{task_id}/rerun` | Supports all or selected rule codes; returns accepted response. |
| Report | `GET /api/v1/tasks/{task_id}/report` | Provides HTML report for online preview. |
| Execution logs | `GET /api/v1/tasks/{task_id}/logs` | Provides task execution history. |
| System inspection | `GET /api/v1/tasks/{task_id}/system` | Returns system summary and rule statuses. |
| Rule result | `GET /api/v1/tasks/{task_id}/rules/{rule_code}` | Returns one full rule result. |
| Overview | `GET /api/v1/overview` | Returns aggregate dashboard/overview data. |
| Inspector metadata | `GET /api/v1/inspectors` | Returns registered rule metadata and output contracts. |
| Dictionary list | `GET /api/v1/dicts` | Returns built-in/configured dictionary groups. |
| Update dictionary | `PUT /api/v1/dicts/{dict_name}` | Maintains a dictionary group. |

## Baseline Invariants

1. One uploaded package maps to one task.
2. A task exposes one system inspection.
3. Rule results are addressable by stable rule code.
4. Rule metadata includes description, recommendation, inputs, outputs, and version.
5. Rerun may update target rules without discarding unrelated results.
6. Deletion is task-wide and covers retained package input plus generated output.
7. No endpoint may introduce online collection from the inspected system.
