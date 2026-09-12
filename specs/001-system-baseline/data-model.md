# Data Model: System Baseline

This model is the baseline business view. The machine-readable API schema remains
[`docs/api/openapi.yaml`](../../docs/api/openapi.yaml); the narrative contract is in
[`docs/data-model.md`](../../docs/data-model.md).

## Entity Relationships

```text
InspectionTask 1──1 SystemInspection
SystemInspection 1──N RuleResult
RuleResult 0──N Metric
RuleResult 0──N Finding
RuleResult 0──N ArtifactReference
InspectionTask 1──1 ExecutionLog
InspectionTask 1──1 Report
```

## InspectionTask

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Task ID | Stable task identity | Identifies retained input and output directories. |
| Name | Human-readable task name | Optional display label. |
| Mode | Local or online execution | Does not change inspection semantics. |
| Status | Pending, running, completed, failed | Task lifecycle state. |
| Trigger | CLI, API, or rerun | Records how execution began. |
| Created At / Completed At | UTC timestamps | Persisted in UTC; display may localize. |
| Stats | Aggregate rule counts | Includes hidden and skipped rules. |
| System | One system inspection context | Exactly one per package/task. |

### Lifecycle

```text
pending → running → completed
                 ↘ failed
```

## SystemInspection

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| System ID | Stable system context identity | Safe for directory naming. |
| System Name | Display name | Human-facing label. |
| Package File | Original package name | Retained for provenance. |
| Package Checksum | Package integrity identity | Supports reproducibility and deduplication. |
| Version | Optional version context | Provided by upload metadata where available. |
| Status | Completed or failed | Reflects the system run outcome. |
| Summary | Rule status counts | `total = pass + warn + fail + error + skip`. |
| Rules | One result per registered/executed rule | Includes hidden extraction rules in total. |
| Customer Context | Optional province/operator/product fields | Online upload metadata; offline uses package fallback. |

## InspectionRule

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Code | Stable rule identity | Lowercase, dot-delimited, filesystem-safe. |
| Name | Display name | Human-readable. |
| Category | Inspection domain | Log, KPI, traffic, alarm, config, resource, other. |
| Priority | P0/P1/P2 | P0 prepares, P1 checks, P2 analyzes. |
| Version | Rule logic version | Bump on logic change; validates artifact freshness. |
| Description | What the rule checks | Required. |
| Recommendation | What to do on issue | Required. |
| Inputs | Declared artifact dependencies | Sole coupling point. |
| Outputs | Declared metrics/artifacts | Used for result validation and UI. |
| Hidden | Internal execution flag | Hidden rules still count in summaries. |

## RuleResult

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Status | Pass, warn, fail, error, skip | Semantics are fixed by Constitution. |
| Summary | Short outcome | Human-readable. |
| Skip Reason | Why execution did not run | Required for skip. |
| Executed At / Duration | Timing metadata | UTC timestamp and duration. |
| Metrics | Structured numeric/series outcomes | Contract keys must be stable. |
| Findings | Traceable issues | Must include source and evidence. |
| Artifacts | Produced intermediate data references | Not embedded in result JSON. |
| Metadata | Rule-specific extension data | Must not redefine common fields. |

## Metric

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Key | Stable identity | Supports cross-task comparison later. |
| Label | Display label | Human-readable. |
| Value | Current numeric value | Required where applicable. |
| Unit | Measurement unit | Stable contract element. |
| Threshold | Reference bound(s) | Used for status and display. |
| Baseline | Reference value | Optional. |
| Series | Trend points | Optional in baseline. |

## Finding

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Finding ID | Result-local identity | Uniquely identifies an issue within the rule result. |
| Title | Short issue description | User-facing. |
| Severity | Issue severity | May differ from rule severity where appropriate. |
| Source File | Package-relative origin | Required for traceability. |
| Evidence | Concrete supporting excerpt | Truncated to safe display size. |
| Details | Explanation | Optional but useful. |
| Recommendation | Follow-up action | User-facing. |

## Prepared Data / Artifact

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Artifact Key | Dependency contract identity | Declared by producer and consumer. |
| Producer Rule Code | Producing rule | Recorded for traceability. |
| Producer Rule Version | Version at production | Must match current rule for reuse. |
| Target Directory | Runtime artifact location | `output/<task_id>/<system_id>/artifacts/<rule_code>/`. |
| Content | Intermediate normalized/filtered data | Not copied into rule result JSON. |

## Extraction Record

| Field / Concept | Description | Baseline Rule |
| --- | --- | --- |
| Package Checksum | Content identity | Deduplication key. |
| Relative Path | Package path identity | Helps avoid duplicate extraction. |
| Target Directory | Category/subpackage destination | Preserves source-relative context. |
| File Count | Extracted file count | Used for manifest integrity and limits. |
| Status | Extracted, reused, or issue | Recorded in execution/report details. |

## State Transitions

### Task

```text
pending → running
running → completed
running → failed
```

### Rule Result

```text
not executed → pass
not executed → warn
not executed → fail
not executed → error
not executed → skip
```

A rerun replaces the target rule result and may regenerate stale dependencies. It does not erase
unrelated rule results.

### Extraction Record

```text
pending → extracted
pending → reused
pending → rejected/failed
```

Rejected or failed extraction is reported but does not silently modify the original package.

## Validation Rules

1. Every task maps to exactly one system inspection.
2. Rule summary totals must add to total.
3. Task stats must agree with the system summary for a single-system task.
4. Every visible finding must have source location and evidence.
5. Every skipped rule must have a skip reason.
6. Rules may consume only artifacts declared in their inputs.
7. Artifact reuse requires a matching producer rule version.
8. Contracted rule outcomes must include declared metrics for pass/warn/fail.
9. Deletion removes both task input and output.
10. UTC is used for persisted timestamps.
