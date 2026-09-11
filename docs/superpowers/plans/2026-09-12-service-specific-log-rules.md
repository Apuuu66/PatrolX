# Service Specific Log Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit AppService and AAAService log inspection rules that consume the common normalized log artifact and run service-specific checks.

**Architecture:** Keep `pkg.extract.*` and `log.filter` generic. The two new P1 rules consume `log.filter.artifacts.filtered_logs`, select records by service name, compute service-specific metrics/findings, and skip cleanly when the service is absent. Shared artifact reading remains in `app/inspectors/log/common.py`.

**Tech Stack:** Python 3.12, Pydantic v2, PatrolX Inspector registry, pytest, uv.

**Spec:** Agreed in conversation: extraction remains generic; service differences live in explicit rules. First implement AppService and AAAService, retain generic rules as fallback.

## Global Constraints

- Rule codes are stable and lowercase: `log.app_service` and `log.aaa_service`.
- Rules must declare non-empty `description` and `recommendation`.
- Rules consuming `filtered.jsonl` must declare `inputs=["log.filter.artifacts.filtered_logs"]`.
- `pass/warn/fail` results must emit every metric declared in `outputs_metrics`.
- Service absence is `skip` with a human-readable `skip_reason`.
- Do not duplicate generic extraction logic or add service-specific extraction rules.
- Run all validation through `UV_CACHE_DIR=.uv-cache uv run ...`.

---

### Task 1: AppService Rule

**Files:**
- Create: `app/inspectors/log/app_service.py`
- Modify: `app/inspectors/log/common.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `filtered_path(ctx)`, `read_records(path)`, and filtered artifact key from existing log helpers.
- Produces: registered rule code `log.app_service`; metrics `error_count`, `pool_exhausted_count`, `sctp_error_count`.

- [ ] **Step 1: Write failing AppService tests**

Add tests that run `log.filter`, load its artifact, run `log.app_service`, and assert detection plus service absence skip behavior.

- [ ] **Step 2: Run AppService tests and confirm failure**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_rules.py -k app_service -q`
Expected: FAIL because `log.app_service` is not registered.

- [ ] **Step 3: Implement AppService rule**

Create the Inspector and run function. Select `AppService` records, calculate the three metrics, create targeted findings for database connection pool and SCTP errors, list only AppService source files, and skip when absent.

- [ ] **Step 4: Run AppService tests and confirm pass**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_rules.py -k app_service -q`
Expected: PASS.

### Task 2: AAAService Rule

**Files:**
- Create: `app/inspectors/log/aaa_service.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: same filtered artifact and shared helpers as AppService.
- Produces: registered rule code `log.aaa_service`; metrics `error_count`, `auth_failure_count`, `retry_timer_count`.

- [ ] **Step 1: Write failing AAAService tests**

Add tests for auth/retry detection and absence skip behavior.

- [ ] **Step 2: Run AAAService tests and confirm failure**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_rules.py -k aaa_service -q`
Expected: FAIL because `log.aaa_service` is not registered.

- [ ] **Step 3: Implement AAAService rule**

Create the Inspector and run function. Select `AAAService` records, calculate the three metrics, create an auth-failure finding, list only AAAService source files, and skip when absent.

- [ ] **Step 4: Run AAAService tests and confirm pass**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_rules.py -k aaa_service -q`
Expected: PASS.

### Task 3: Full Regression and Offline Flow

**Files:**
- No production changes expected.

**Interfaces:**
- Consumes: real fixture package in `uploads/ZZapp01BCN_app_problem_scene_333.zip` when present, otherwise tests fixture `tests/fixtures/sample/sample.zip`.
- Produces: refreshed local output, HTML report, and two new rule result JSON files.

- [ ] **Step 1: Run full test suite**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest`
Expected: all tests pass.

- [ ] **Step 2: Run lint and format checks**

Run: `UV_CACHE_DIR=.uv-cache uv run ruff check app tests && UV_CACHE_DIR=.uv-cache uv run ruff format --check app tests`
Expected: clean.

- [ ] **Step 3: Run full offline inspection**

Run: `UV_CACHE_DIR=.uv-cache uv run python main.py`
Expected: task completes; report generated; `log.app_service.json` and `log.aaa_service.json` exist with expected statuses.

- [ ] **Step 4: Inspect generated rule results**

Read the two new rule JSON files and report path. Confirm metrics/findings are populated and processed files are service-specific.
