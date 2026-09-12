# Feature Specification: System Baseline

**Feature Branch**: `001-system-baseline`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: "建立 PatrolX 当前系统的 baseline 规格，固化离线巡检、任务模型、规则执行、报告查看和本地/在线共用体验的核心业务能力。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run an Offline Inspection (Priority: P1)

A maintainer collects a system data package and places it in the offline input area. The
system recognizes the package, creates one isolated inspection context, extracts and
organizes package contents, runs the applicable inspection rules, and produces a readable
inspection report. The maintainer can understand overall health, problem areas, evidence,
and recommended follow-up actions without connecting to the inspected system.

**Why this priority**: This is the core business flow. PatrolX delivers value only when a
pre-collected package can be transformed into trustworthy inspection results and findings.

**Independent Test**: Provide one supported package, run the offline flow, and verify that
exactly one task and one system context are produced, inspection results exist, and a human
readable report is available.

**Acceptance Scenarios**:

1. **Given** the offline input area contains one supported package, **When** the user starts
   the offline inspection flow, **Then** the system creates exactly one inspection task for
   that package and processes its contents without connecting to the inspected system.
2. **Given** the package contains recognizable log, KPI, traffic, alarm, configuration, or
   resource data, **When** processing completes, **Then** the applicable inspection rules
   produce results and the report summarizes status, findings, and recommendations.
3. **Given** a rule category has no matching data in the package, **When** processing
   completes, **Then** that category is clearly marked as skipped with a human-readable
   reason instead of being silently omitted or reported as healthy.

---

### User Story 2 - Review Results by Task, System, Rule, and Finding (Priority: P2)

A maintainer opens an inspection context and drills down from the overall task status to the
system summary, individual rule results, and concrete findings. For each problem, they can
see the source location, supporting evidence, severity, and recommendation.

**Why this priority**: Inspection is only actionable when users can navigate from a high-level
status to traceable evidence and a concrete next action.

**Independent Test**: From a completed inspection, verify that every displayed problem can be
traced to its rule, source location, evidence, and recommendation.

**Acceptance Scenarios**:

1. **Given** a completed inspection, **When** the user opens the task view, **Then** the user
   sees aggregate status counts and can navigate to system and rule results.
2. **Given** a rule result with findings, **When** the user opens the rule detail, **Then**
   the user sees the rule summary, relevant metrics, findings, source locations, and
   recommendations.
3. **Given** a rule was skipped, **When** the user views its result, **Then** the reason for
   skipping is visible.

---

### User Story 3 - Keep Local and Online Inspection Experiences Consistent (Priority: P3)

A maintainer can use the same package in local mode for quick validation and in online mode
for shared review. The inspection meaning, task structure, rule results, findings, and report
concept remain the same across both experiences.

**Why this priority**: Consistency protects user trust and prevents local-only behavior from
becoming a divergent product.

**Independent Test**: Process the same supported package through local and online flows and
compare that the same business result structure and rule outcomes are represented in both.

**Acceptance Scenarios**:

1. **Given** the same supported package is inspected locally and online, **When** both
   executions complete, **Then** the same applicable rules produce the same business
   outcomes, excluding execution identity and timing.
2. **Given** a completed inspection exists in either mode, **When** the user views it, **Then**
   the task → system → rule → finding model is recognizable and consistent.

---

### User Story 4 - Rerun a Target Rule (Priority: P4)

A rule developer changes an inspection rule and wants to validate it without rerunning every
rule. The developer can rerun the target rule; if required preparation data is missing or
stale, the system handles the necessary dependency work first. Existing unrelated results
remain available.

**Why this priority**: Fast rule iteration improves inspection quality, but it depends on the
baseline inspection flow already working.

**Independent Test**: After an inspection exists, rerun one rule and verify that only the
target result is refreshed while other results remain identifiable.

**Acceptance Scenarios**:

1. **Given** a completed inspection, **When** the developer reruns one rule, **Then** that
   rule is reevaluated and its result is updated.
2. **Given** the target rule depends on prepared data that is missing or produced by an older
   rule version, **When** the rerun starts, **Then** the system obtains fresh dependency data
   before evaluating the target rule.
3. **Given** a rerun completes, **When** the user views the task, **Then** unrelated rule
   results remain available.

---

### Edge Cases

- A package is corrupted, unsupported, exceeds limits, or contains unsafe archive paths; the
  system must reject or contain the problem with a clear user-facing outcome.
- A nested archive repeats data or has already been processed; the system must avoid
  duplicating extraction work.
- A file uses an unrecognized or malformed format; processing must not lose the rest of the
  inspection.
- A package contains no data for one or more categories; those rules must be visibly skipped
  with reasons.
- Two tasks use the same system identifier over time; each task remains isolated while still
  supporting later comparison.
- A user requests deletion of a task; both retained input and generated output must be removed
  together.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept one pre-collected package as one inspection task.
- **FR-002**: The system MUST NOT require access to the inspected system to perform
  inspection.
- **FR-003**: The system MUST keep package data, inspection context, artifacts, logs, and
  reports isolated by task and system.
- **FR-004**: The system MUST organize package contents into recognizable inspection
  categories, including log, KPI, traffic, alarm, configuration, resource, and other.
- **FR-005**: The system MUST safely extract package content, including nested supported
  packages, without allowing path traversal or unsafe archive expansion.
- **FR-006**: The system MUST avoid repeatedly extracting the same nested package within a
  task.
- **FR-007**: The system MUST execute inspection rules in an order that satisfies declared
  data dependencies.
- **FR-008**: The system MUST record rule results with status, summary, metrics where
  applicable, findings where applicable, execution time, and duration.
- **FR-009**: The system MUST support pass, warning, failure, error, and skipped rule
  outcomes.
- **FR-010**: The system MUST require a visible reason when a rule is skipped.
- **FR-011**: The system MUST retain source location and evidence for findings so users can
  trace conclusions back to package data.
- **FR-012**: The system MUST provide a human-readable inspection report summarizing overall
  status, rule results, findings, and recommendations.
- **FR-013**: The system MUST allow users to review results by task, system, rule, and
  finding.
- **FR-014**: The system MUST allow a target rule to be rerun without requiring unrelated
  rules to lose their results.
- **FR-015**: The system MUST refresh or regenerate missing or outdated dependency data before
  evaluating a rerun target rule.
- **FR-016**: The system MUST preserve inspection meaning when the same package is processed
  through local and shared/online experiences.
- **FR-017**: The system MUST retain completed tasks and their inspection evidence until a
  user explicitly deletes the task.
- **FR-018**: The system MUST remove both retained package input and generated inspection
  output when a task is deleted.

### Key Entities *(include if feature involves data)*

- **Inspection Task**: One execution triggered by one package; has identity, lifecycle state,
  trigger source, timing, and aggregate result counts.
- **System Inspection**: One inspected system context associated with the task; has package
  identity, optional customer/version context, status, and rule summaries.
- **Inspection Rule**: A named, versioned inspection capability with category, priority,
  declared inputs, outputs, status, summary, metrics, findings, and produced data references.
- **Finding**: A concrete issue identified by a rule; has severity, source location, evidence,
  details, and recommendation.
- **Prepared Data**: Intermediate inspection data produced by preparation rules and consumed
  only through explicit declared dependencies.
- **Report**: A human-readable summary of task, system, rules, findings, evidence, and
  recommendations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can place one supported package and obtain a completed inspection with a
  report in a single local flow.
- **SC-002**: 100% of displayed findings can be traced to a rule, source location, and
  evidence.
- **SC-003**: 100% of skipped rules expose a readable skip reason.
- **SC-004**: A rule developer can validate one changed rule without rerunning every rule in
  the system.
- **SC-005**: The same supported package produces the same business rule outcomes in local and
  online experiences, excluding execution identity and timing.
- **SC-006**: A user can identify overall task health and at least the top actionable findings
  from the report without reading raw package files.
- **SC-007**: 100% of deleted tasks leave no retained task input or generated output behind.

## Assumptions

- Users are internal maintainers or rule developers; no public customer authentication is
  assumed.
- Packages are pre-collected by an existing customer-side or maintainer process.
- The first release prioritizes correctness, traceability, and simple operation over
  concurrency and distributed execution.
- Report download and PDF export are out of scope.
- Online rule editing, rule enablement, and parameter configuration are out of scope.
- Cross-task trend analysis is a future capability, not part of this baseline.
