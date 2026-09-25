import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { TaskStats } from "../api/http";
import {
  getAttentionSummary,
  getCustomerFields,
  getHealthBarSegments,
  getStatusStatEmphasis,
} from "./taskDisplay.ts";

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 5, pass: 2, warn: 1, fail: 2, error: 0, skip: 0, systems: 1, ...overrides };
}

describe("getStatusStatEmphasis", () => {
  it("弱化零值状态", () => {
    assert.equal(getStatusStatEmphasis("pass", 0), "quiet");
    assert.equal(getStatusStatEmphasis("fail", 0), "quiet");
  });

  it("突出需要关注的非零状态", () => {
    assert.equal(getStatusStatEmphasis("warn", 1), "attention");
    assert.equal(getStatusStatEmphasis("fail", 3), "attention");
    assert.equal(getStatusStatEmphasis("error", 1), "attention");
  });

  it("保持正常状态轻量但不弱化", () => {
    assert.equal(getStatusStatEmphasis("pass", 8), "normal");
    assert.equal(getStatusStatEmphasis("skip", 1), "normal");
  });
});

describe("getAttentionSummary", () => {
  it("按失败、告警、异常顺序汇总状态", () => {
    assert.equal(getAttentionSummary(makeStats()), "失败 2 · 告警 1 · 异常 0");
  });

  it("没有需要关注的状态时给出完成提示", () => {
    assert.equal(
      getAttentionSummary(makeStats({ warn: 0, fail: 0, error: 0 })),
      "未发现失败、告警或异常规则",
    );
  });
});

describe("getCustomerFields", () => {
  it("把客户字段转换为可读键值并排除设备 ID", () => {
    const fields = getCustomerFields({
      province: "js",
      operator: "cmcc",
      product: "router",
      device_id: "home-device-001",
    });

    assert.deepEqual(fields, [
      { key: "province", label: "省份", value: "js" },
      { key: "operator", label: "运营商", value: "cmcc" },
      { key: "product", label: "产品形态", value: "router" },
    ]);
  });

  it("跳过空值并支持未知字段", () => {
    const fields = getCustomerFields({ province: "", region: "华东" });
    assert.deepEqual(fields, [{ key: "region", label: "region", value: "华东" }]);
  });

  it("无有效字段时返回空列表", () => {
    assert.deepEqual(getCustomerFields(undefined), []);
    assert.deepEqual(getCustomerFields({ device_id: "dev-001" }), []);
  });
});

describe("getHealthBarSegments", () => {
  it("按非零状态生成健康度分段", () => {
    const segments = getHealthBarSegments(makeStats({ total: 4, pass: 2, warn: 1, fail: 1 }));

    assert.deepEqual(
      segments.map((segment) => ({ key: segment.key, value: segment.value, percent: segment.percent })),
      [
        { key: "pass", value: 2, percent: 50 },
        { key: "warn", value: 1, percent: 25 },
        { key: "fail", value: 1, percent: 25 },
      ],
    );
  });

  it("全部状态为零时返回空分段", () => {
    assert.deepEqual(getHealthBarSegments(makeStats({ total: 0, pass: 0, warn: 0, fail: 0 })), []);
  });
});
