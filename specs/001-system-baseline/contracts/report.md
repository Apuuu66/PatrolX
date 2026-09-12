# Report Contract: System Baseline

## Purpose

The report gives maintainers a human-readable inspection summary without opening raw package
files. It complements, but does not replace, task/system/rule drill-down in the Web UI.

## Required Report Content

1. Task identity and execution context.
2. System identity and package provenance.
3. Overall status and aggregate counts for pass, warn, fail, error, and skip.
4. Rule status summaries, including hidden-rule errors where operationally relevant.
5. Findings with severity, source location, evidence, and recommendation.
6. Skipped rules with reasons.
7. Execution time or duration where available.

## Baseline Constraints

- The report is HTML for online preview.
- PDF export is out of scope.
- Report download is out of scope.
- The report must not expose secrets or unrelated customer data.
- Every actionable finding must remain traceable to source data.
- The report must be generated from contract results and retained evidence, not ad-hoc
  unpersisted calculations.

## Review Outcomes

A report is acceptable when a maintainer can determine:

- Whether the inspection completed.
- The overall health/status distribution.
- Which rules failed, warned, errored, or skipped.
- Where the most important issues occurred.
- What follow-up action is recommended.
