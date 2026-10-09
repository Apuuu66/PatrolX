import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { TaskStats, TaskSummary } from "../api/http";
import { deriveTaskConclusion } from "./taskConclusion.ts";

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1, ...overrides };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task-001",
    name: "样例任务",
    mode: "local",
    status: "completed",
    trigger: "api",
    created_at: "2026-10-10T00:00:00Z",
    completed_at: "2026-10-10T00:01:00Z",
    stats: makeStats(),
    ...overrides,
  };
}

describe("deriveTaskConclusion", () => {
  it("任务失败时优先给出失败结论与日志入口", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ status: "failed" }),
      "解压失败：包文件损坏",
    );

    assert.equal(conclusion.tone, "danger");
    assert.equal(conclusion.label, "任务失败");
    assert.equal(conclusion.sentence, "解压失败：包文件损坏");
    assert.equal(conclusion.nextAction, "logs");
    assert.notEqual(conclusion.detail, null);
  });

  it("任务失败但没有失败原因时使用兜底说明", () => {
    const conclusion = deriveTaskConclusion(makeTask({ status: "failed" }));

    assert.equal(conclusion.tone, "danger");
    assert.equal(conclusion.label, "任务失败");
    assert.ok(conclusion.sentence.length > 0);
    assert.equal(conclusion.nextAction, "logs");
  });

  it("排队中任务给出中性结论且无下一步动作", () => {
    const conclusion = deriveTaskConclusion(makeTask({ status: "pending", completed_at: null }));

    assert.equal(conclusion.tone, "neutral");
    assert.equal(conclusion.label, "排队中");
    assert.equal(conclusion.nextAction, null);
  });

  it("执行中任务给出进行中结论且无下一步动作", () => {
    const conclusion = deriveTaskConclusion(makeTask({ status: "running", completed_at: null }));

    assert.equal(conclusion.tone, "processing");
    assert.equal(conclusion.label, "执行中");
    assert.equal(conclusion.nextAction, null);
  });

  it("存在失败或异常规则时给出需要关注结论并跳转规则", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ stats: makeStats({ pass: 1, fail: 2, error: 1 }) }),
    );

    assert.equal(conclusion.tone, "danger");
    assert.equal(conclusion.label, "需要关注");
    assert.match(conclusion.sentence, /失败 2/);
    assert.match(conclusion.sentence, /异常 1/);
    assert.equal(conclusion.nextAction, "rules");
  });

  it("失败与异常并存时只表达非零状态", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ stats: makeStats({ pass: 1, fail: 2, error: 1 }) }),
    );

    assert.equal(conclusion.tone, "danger");
    assert.match(conclusion.sentence, /失败 2 条/);
    assert.match(conclusion.sentence, /异常 1 条/);
    assert.doesNotMatch(conclusion.sentence, /0 条/);
  });

  it("只有失败规则时结论不出现异常 0 条", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ stats: makeStats({ pass: 1, fail: 2 }) }),
    );

    assert.equal(conclusion.label, "需要关注");
    assert.match(conclusion.sentence, /失败 2 条/);
    assert.doesNotMatch(conclusion.sentence, /异常/);
    assert.doesNotMatch(conclusion.sentence, /0 条/);
  });

  it("只有异常规则时结论只表达异常", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ stats: makeStats({ pass: 1, error: 3 }) }),
    );

    assert.equal(conclusion.label, "需要关注");
    assert.match(conclusion.sentence, /异常 3 条/);
    assert.doesNotMatch(conclusion.sentence, /失败/);
    assert.doesNotMatch(conclusion.sentence, /0 条/);
  });

  it("仅有告警时使用警告语气而不是失败红", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ stats: makeStats({ pass: 3, warn: 2 }) }),
    );

    assert.equal(conclusion.tone, "warning");
    assert.equal(conclusion.label, "需要关注");
    assert.match(conclusion.sentence, /告警 2/);
    assert.equal(conclusion.nextAction, "rules");
  });

  it("全部通过或仅有跳过时给出成功结论并指向报告", () => {
    const passed = deriveTaskConclusion(makeTask({ stats: makeStats({ pass: 4 }) }));
    assert.equal(passed.tone, "success");
    assert.equal(passed.label, "全部通过");
    assert.equal(passed.nextAction, "report");

    const skipped = deriveTaskConclusion(
      makeTask({ stats: makeStats({ pass: 0, skip: 3 }) }),
    );
    assert.equal(skipped.tone, "success");
    assert.equal(skipped.label, "全部通过");
    assert.equal(skipped.nextAction, "report");
  });

  it("统计为空时不产生需要关注的结论", () => {
    const conclusion = deriveTaskConclusion(
      makeTask({ stats: makeStats({ total: 0, pass: 0 }) }),
    );

    assert.equal(conclusion.tone, "success");
    assert.equal(conclusion.label, "全部通过");
    assert.notEqual(conclusion.sentence.length, 0);
  });
});
