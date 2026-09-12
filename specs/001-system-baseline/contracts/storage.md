# Storage Contract: System Baseline

## Storage Model

| Concern | Location / Mechanism | Baseline Requirement |
| --- | --- | --- |
| Original package | `uploads/<task_id>/` | Immutable input evidence; retained until deletion. |
| Extracted package content | `output/<task_id>/<system_id>/<category>/` | Organized by category and source-relative path. |
| Prepared data | `output/<task_id>/<system_id>/artifacts/<rule_code>/` | Runtime artifacts, not contract result JSON. |
| Rule result | `output/<task_id>/<system_id>/rules/<code>.json` | One file per rule; supports independent update. |
| Execution log | `output/<task_id>/execution.log` | Structured, task-scoped execution history. |
| Report | `output/<task_id>/report.html` | Human-readable online preview report. |
| Metadata | SQLite | Lightweight task/system status and operational metadata. |

## Categories

```text
logs/
kpi/
traffic/
alarm/
config/
resource/
other/
```

A category directory exists for recognizable data of that type. Data that cannot be classified
falls under `other/`.

## Lifecycle Rules

1. Task creation retains the original package under the task input area.
2. Extraction reads the original package but never modifies it.
3. Processing output remains under the task output area.
4. Completed tasks and evidence are retained until explicit deletion.
5. Task deletion removes both the task input directory and task output directory.
6. No automatic retention cleanup is introduced by the baseline.

## Extraction Manifest

Each system maintains extraction state sufficient to ensure:

- The same nested package is not extracted repeatedly.
- Checksum, target directory, and file count are recorded.
- Reuse and extraction decisions are traceable.
- Unsafe or rejected items are reported rather than silently ignored.

## Metadata Versus Files

SQLite stores only lightweight operational metadata. It is not the authority for every finding,
metric, artifact, or extracted file. The filesystem remains the authoritative runtime evidence
layout so local mode and online mode can share the same result semantics.
