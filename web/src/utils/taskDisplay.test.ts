import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { TaskStats } from "../api/http";
import {
  getAttentionSummary,
  getCustomerFields,
  getDeviceIdDisplay,
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
      { key: "product", label: "网元类型", value: "router" },
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

describe("getDeviceIdDisplay", () => {
  it("优先展示手工填写的设备 ID", () => {
    const display = getDeviceIdDisplay({
      device_id: "manual-001",
      inventory: { devices: [{ normalized_name: "CSP-SZ-01" }] },
    });

    assert.deepEqual(display, { value: "manual-001", source: "manual" });
  });

  it("未填写时回退到上传元数据中的设备 ID", () => {
    const display = getDeviceIdDisplay({}, { device_id: " home-device-001 " });

    assert.deepEqual(display, { value: "home-device-001", source: "manual" });
  });

  it("没有手工设备 ID 时展示台账解析出的网元名称", () => {
    const display = getDeviceIdDisplay({
      inventory: {
        devices: [{ normalized_name: "CSP-SZ-01" }, { normalized_name: "UMF-SZ-01" }],
      },
    });

    assert.deepEqual(display, { value: "CSP-SZ-01、UMF-SZ-01", source: "ledger" });
  });

  it("台账名称去重并忽略空值", () => {
    const display = getDeviceIdDisplay({
      inventory: { devices: [{ normalized_name: " " }, { normalized_name: "CSP-SZ-01" }, { normalized_name: "CSP-SZ-01" }] },
    });

    assert.deepEqual(display, { value: "CSP-SZ-01", source: "ledger" });
  });

  it("没有任何来源时展示占位符", () => {
    assert.deepEqual(getDeviceIdDisplay({ inventory: { devices: [] } }), { value: "-", source: null });
    assert.deepEqual(getDeviceIdDisplay({}), { value: "-", source: null });
  });
});

describe("getHealthBarSegments", () => {
  it("按 fail → warn → error → skip → pass 排序并过滤 0 值", () => {
    const segments = getHealthBarSegments(
      makeStats({ total: 8, pass: 3, warn: 1, fail: 2, error: 1, skip: 1 }),
    );

    assert.deepEqual(
      segments.map((segment) => ({
        key: segment.key,
        value: segment.value,
        percent: segment.percent,
      })),
      [
        { key: "fail", value: 2, percent: 25 },
        { key: "warn", value: 1, percent: 12.5 },
        { key: "error", value: 1, percent: 12.5 },
        { key: "skip", value: 1, percent: 12.5 },
        { key: "pass", value: 3, percent: 37.5 },
      ],
    );
  });

  it("概览场景弱化通过与会话，并保留关注状态的强调级别", () => {
    const segments = getHealthBarSegments(makeStats({ total: 4, pass: 3, warn: 1 }), {
      emphasis: "overview",
    });

    const pass = segments.find((segment) => segment.key === "pass");
    const warn = segments.find((segment) => segment.key === "warn");

    assert.equal(pass?.color, "#b7eb8f");
    assert.equal(pass?.emphasis, "quiet");
    assert.equal(warn?.color, "#faad14");
    assert.equal(warn?.emphasis, "attention");
  });

  it("任务行与详情保持标准状态色", () => {
    const segments = getHealthBarSegments(makeStats({ total: 2, pass: 1, skip: 1 }));

    assert.equal(segments.find((segment) => segment.key === "pass")?.color, "#52c41a");
    assert.equal(segments.find((segment) => segment.key === "skip")?.color, "#1677ff");
    assert.equal(segments.find((segment) => segment.key === "pass")?.emphasis, "normal");
  });

  it("全部状态为零时返回空分段", () => {
    assert.deepEqual(getHealthBarSegments(makeStats({ total: 0, pass: 0, warn: 0, fail: 0 })), []);
  });
});
