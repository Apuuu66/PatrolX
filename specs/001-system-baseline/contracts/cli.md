# CLI Contract: System Baseline

The CLI is the local-mode entry point for rule development and offline verification.

## Commands

| Command | Purpose | Baseline Result |
| --- | --- | --- |
| `make verify` | Run the full local pipeline through `main.py` | Scans package input, creates/isolates tasks, runs rules, writes results/logs/report. |
| `make verify-one RULE=<rule_code>` | Rerun one target rule | Refreshes the target result and ensures stale/missing dependencies are handled. |
| `make verify-one RULE=<rule_code> SYSTEM=<system_id>` | Rerun one rule for one system | Narrows rerun to the specified system context. |
| `make contract` | Export/validate OpenAPI from implementation models | Fails if implementation and contract diverge. |
| `make test` | Run backend tests | Verifies rules, executor, archive safety, API, schemas, and consistency. |
| `make lint` | Run Ruff check/format validation | Enforces code style and static checks. |

## Environment Inputs

| Variable | Purpose | Default |
| --- | --- | --- |
| `PACKAGE_DIR` | Alternative offline package input directory | `uploads/` root |
| `PATROLX_PACKAGE_DIR` | Rule-file direct-run package source | Falls back to sample fixture when no package is available |

## Local Mode Invariants

1. Offline mode does not require database setup.
2. Packages placed at the root of the configured input directory are discovered and processed
   sequentially.
3. Each package produces one task and one system inspection.
4. Local output structure matches the online contract structure.
5. Rule results are written per rule so individual reruns can update them in place.
6. A missing category or dependency produces `skip` with a visible reason where appropriate.
7. No command may connect to an inspected system.

## Expected Local Outputs

```text
uploads/<task_id>/<package>              # retained original package
output/<task_id>/<system_id>/            # categorized package content
output/<task_id>/<system_id>/artifacts/  # intermediate prepared data
output/<task_id>/<system_id>/rules/      # contract JSON per rule
output/<task_id>/report.html             # human-readable report
output/<task_id>/execution.log           # structured task execution log
```
