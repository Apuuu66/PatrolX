# Quickstart: System Baseline Validation

This guide validates the baseline business flow without prescribing implementation changes.

## Prerequisites

- Repository checkout.
- Python environment prepared by repository tooling.
- Node.js/npm for frontend build or Web review.
- At least one supported sample package.

The repository sample fixture is available at:

```text
tests/fixtures/sample/sample.zip
```

For real-format validation, use a sanitized internal package and compare its structure with
[`docs/example/real-package-structure.md`](../../docs/example/real-package-structure.md).

## 1. Verify Environment

```bash
make lint
make test
make contract
```

Expected:

- Ruff check/format passes.
- All backend tests pass.
- OpenAPI contract and implementation agree.

## 2. Run the Offline Baseline Flow

Place one supported package in the default offline input area:

```bash
cp /path/to/package.zip uploads/
make verify
```

Alternatively, point to another package directory:

```bash
PACKAGE_DIR=/path/to/packages make verify
```

Expected:

1. The package is recognized as one task.
2. Exactly one system inspection context is produced.
3. Package contents are safely classified and extracted.
4. Applicable rules execute.
5. Rule JSON results, execution log, and HTML report are created.
6. Categories with no applicable data are skipped with reasons.

## 3. Inspect Results

Check the task output layout:

```bash
find output/<task_id> -maxdepth 3 -type f | sort
```

Confirm that:

- Original package remains under `uploads/`.
- Rule results exist under `output/<task_id>/<system_id>/rules/`.
- Execution log exists at `output/<task_id>/execution.log`.
- Report exists at `output/<task_id>/report.html`.

Open the report and verify that it shows:

- Overall status counts.
- Rule outcomes.
- Findings with source/evidence.
- Recommendations.
- Skip reasons where applicable.

## 4. Validate Single-Task Isolation

Add a second differently named supported package to the input directory and run:

```bash
make verify
```

Expected:

- A second task is created.
- Each task has its own system/output directory.
- Results, findings, logs, and report for one task do not merge into another.

## 5. Validate Rule Rerun

Choose a rule code from the existing task output:

```bash
make verify-one RULE=<rule_code> SYSTEM=<system_id>
```

Expected:

- The requested rule result is refreshed.
- Missing or stale dependency artifacts are regenerated.
- Valid dependency artifacts may be reused.
- Unrelated rule result files remain available.

## 6. Validate Local/Online Semantics

Start the online service:

```bash
python run_online.py
```

Then upload the same supported package through the Web UI and compare with the local run.

Expected:

- Task/system/rule/finding structure has the same business meaning.
- Rule outcomes match for the same package, excluding execution identity and timing.
- Report and rule detail remain reviewable in the browser.

## 7. Validate Deletion

Delete a completed task through the online task flow or its equivalent API operation.

Expected:

- Task input under `uploads/<task_id>/` is removed.
- Task output under `output/<task_id>/` is removed.
- No partial task remains.

## 8. Failure-Handling Checks

Use a fixture or temporary copy that contains malformed/unrecognized content.

Expected:

- A malformed file does not abort the entire task when processing can continue.
- The issue is visible in rule result or structured execution log.
- Unaffected categories and rules still produce results.
- Unsupported/no-data categories are skipped with reasons.
