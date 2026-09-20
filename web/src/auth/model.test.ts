import test from "node:test";
import assert from "node:assert/strict";

import { canWrite } from "./model.ts";

test("只有 admin 可以执行写操作", () => {
  assert.equal(canWrite("admin"), true);
  assert.equal(canWrite("viewer"), false);
  assert.equal(canWrite("unknown"), false);
});
