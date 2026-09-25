import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { loadTaskDetailData } from "./taskDetailData.ts";

const task = { task_id: "task-1" } as any;
const system = { package_file: "package.zip" } as any;
const logs = { entries: [{ ts: 1, level: "info", message: "ok" }] } as any;
const inspectors = [
  { code: "pkg.extract.a", hidden: true },
  { code: "log.a", hidden: false },
] as any;

const dependencies = {
  getTask: async () => task,
  getSystem: async () => system,
  listInspectors: async () => inspectors,
  getLogs: async () => logs,
};

describe("loadTaskDetailData", () => {
  it("加载任务、系统结果、日志和隐藏规则", async () => {
    const result = await loadTaskDetailData("task-1", dependencies);

    assert.equal(result.task.status, "ready");
    assert.equal(result.task.data, task);
    assert.equal(result.system.status, "ready");
    assert.equal(result.system.data, system);
    assert.equal(result.logs.status, "ready");
    assert.deepEqual(result.logs.data, logs.entries);
    assert.deepEqual([...result.hiddenRuleCodes], ["pkg.extract.a"]);
  });

  it("区分系统结果失败和日志失败，不影响任务数据", async () => {
    const result = await loadTaskDetailData("task-1", {
      ...dependencies,
      getSystem: async () => {
        throw new Error("系统结果不可用");
      },
      getLogs: async () => {
        throw new Error("日志不可用");
      },
    });

    assert.equal(result.task.status, "ready");
    assert.equal(result.system.status, "error");
    assert.equal(result.system.message, "系统结果不可用");
    assert.equal(result.logs.status, "error");
    assert.equal(result.logs.message, "日志不可用");
  });

  it("任务失败时返回可区分的错误并保留其他请求结果", async () => {
    const result = await loadTaskDetailData("task-1", {
      ...dependencies,
      getTask: async () => {
        throw new Error("任务不存在");
      },
    });

    assert.equal(result.task.status, "error");
    assert.equal(result.task.message, "任务不存在");
    assert.equal(result.system.status, "ready");
    assert.equal(result.logs.status, "ready");
  });
});
