# Rule Contract: System Baseline

This contract defines how inspectors plug into the baseline executor and how their outputs are
validated and consumed.

## Registration Metadata

Every registered rule MUST declare:

| Field | Requirement |
| --- | --- |
| `code` | Stable lowercase dot-delimited identifier; usable as a filename. |
| `name` | Human-readable display name. |
| `category` | `log`, `kpi`, `traffic`, `alarm`, `config`, `resource`, or `other`. |
| `severity` | Rule-level severity. |
| `priority` | P0 for preparation, P1 for basic inspection, P2 for advanced analysis. |
| `rule_version` | Bumped when logic changes. |
| `description` | Non-empty explanation of what is checked. |
| `recommendation` | Non-empty follow-up guidance. |
| `hidden` | Whether the rule is internal and excluded from normal UI display. |
| `inputs[]` | Artifact keys consumed by the rule. |
| `outputs.metrics[]` | Metric keys/units the rule is expected to produce. |
| `outputs.artifacts[]` | Artifact keys the rule is expected to produce. |
| `params[]` | Optional parameter metadata. |

## Dependency Rules

1. A rule may consume only artifact keys declared in `inputs[]`.
2. The executor derives dependencies from `inputs[]`.
3. Dependencies must point to higher-priority rules.
4. Same-priority rule-to-rule dependency is forbidden.
5. Hidden `pkg.extract.*` rules are the permitted infrastructure exception.
6. Circular, missing, or priority-invalid dependencies must be rejected at registration/startup.
7. Rules must not import or call other rules' implementations.

## Execution Status Contract

| Status | Meaning | Output Contract |
| --- | --- | --- |
| `pass` | Rule ran and found no issue | Must produce declared metrics. |
| `warn` | Rule ran and found warning-level issue | Must produce declared metrics. |
| `fail` | Rule ran and found failing issue | Must produce declared metrics. |
| `error` | Rule execution failed | Contract metric output is exempt; failure must be recorded/logged. |
| `skip` | Rule did not apply | Contract metric output is exempt; `skip_reason` is required. |

## Finding Contract

A finding must provide:

- Stable result-local `finding_id`.
- Title.
- Severity.
- Source file or package-relative location.
- Evidence, truncated to a safe display size.
- Optional details.
- Recommendation or clear reference to rule-level recommendation.

Generic conclusions without traceable evidence are not valid baseline findings.

## Artifact Contract

Artifacts are the only supported channel for inter-rule data.

- Producer declares its artifact keys in output metadata.
- Consumer declares each consumed key in `inputs[]`.
- The executor records the producer rule and rule version.
- A consumer may reuse an artifact only when its producer version is current.
- A stale or missing dependency must be regenerated before target-rule rerun.
- Artifacts live outside rule result JSON.

## Rerun Contract

1. The target rule can be requested independently.
2. The executor resolves all transitive artifact dependencies.
3. Missing or version-stale dependencies are regenerated.
4. Valid current dependencies may be reused.
5. The target result is rewritten.
6. Unrelated rule results are not erased.
