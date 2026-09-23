import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { versionCandidateLabel, versionSummaryMessage } from "./measurementVersionCompare.ts";

describe("measurement version compare utils", () => {
  it("renders unknown versions explicitly", () => {
    assert.equal(versionCandidateLabel({ version: null, version_known: false }), "版本未知");
    assert.equal(versionCandidateLabel({ version: "V1", version_known: true }), "V1");
  });

  it("explains mean change direction", () => {
    assert.match(
      versionSummaryMessage({
        current_value: 130,
        baseline_value: 105,
        absolute_change: 25,
        change_ratio: 25 / 105,
        direction: "up",
        message: "当前版本均值较基线版本均值上涨 25（23.81%）。",
      }),
      /上涨/,
    );
    assert.match(
      versionSummaryMessage({
        current_value: 90,
        baseline_value: 105,
        absolute_change: -15,
        change_ratio: -15 / 105,
        direction: "down",
        message: "当前版本均值较基线版本均值下降 15（14.29%）。",
      }),
      /下降/,
    );
    assert.match(
      versionSummaryMessage({
        current_value: null,
        baseline_value: 105,
        absolute_change: null,
        change_ratio: null,
        direction: "unknown",
        message: "缺少数据",
      }),
      /无法/,
    );
  });
});
