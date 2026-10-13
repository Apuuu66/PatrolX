import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isSceneCleaned, toResourceError } from "./sceneError.ts";

describe("toResourceError", () => {
  it("保留 API 错误的错误码与状态码", () => {
    const error = Object.assign(new Error("执行日志不入库，已随磁盘现场清理，不可查看"), {
      code: "scene_cleaned",
      status: 410,
    });

    const state = toResourceError(error);

    assert.equal(state.message, "执行日志不入库，已随磁盘现场清理，不可查看");
    assert.equal(state.code, "scene_cleaned");
    assert.equal(state.statusCode, 410);
  });

  it("普通错误只保留消息", () => {
    const state = toResourceError(new Error("日志加载失败"));

    assert.deepEqual(state, { message: "日志加载失败", code: undefined, statusCode: undefined });
    assert.equal(isSceneCleaned(state), false);
  });

  it("非错误值回退到默认文案", () => {
    assert.equal(toResourceError(null, "加载失败").message, "加载失败");
  });
});

describe("isSceneCleaned", () => {
  it("按错误码或 410 状态码识别现场清理", () => {
    assert.equal(isSceneCleaned({ message: "已清理", code: "scene_cleaned" }), true);
    assert.equal(isSceneCleaned({ message: "已清理", statusCode: 410 }), true);
    assert.equal(isSceneCleaned({ message: "报告未生成", code: "not_found", status: 404 }), false);
    assert.equal(isSceneCleaned(null), false);
  });
});
