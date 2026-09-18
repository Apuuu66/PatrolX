import assert from "node:assert/strict";
import test from "node:test";

import { formatKpiNumber } from "./kpiFormat.ts";

test("limits fractional KPI values to 3 decimal places", () => {
  assert.equal(formatKpiNumber(99.44444444444444), "99.444");
  assert.equal(formatKpiNumber("99.44444444444444"), "99.444");
  assert.equal(formatKpiNumber(99.9999999), "100");
  assert.equal(formatKpiNumber(2700), "2,700");
  assert.equal(formatKpiNumber(0), "0");
  assert.equal(formatKpiNumber(null), "-");
  assert.equal(formatKpiNumber(undefined), "-");
});
