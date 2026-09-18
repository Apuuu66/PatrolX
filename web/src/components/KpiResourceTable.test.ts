import assert from "node:assert/strict";
import { test } from "node:test";
import { buildResourceQuery, resourceDomainLabel, resourceRowSelection, resourceTypeLabel } from "./kpiResourceModel.ts";

test("builds resource query with search, filter and bounded pagination", () => {
  assert.deepEqual(buildResourceQuery({ search: " 请求 ", domain: "api", page: 2, pageSize: 500 }), {
    search: "请求",
    domain: "api",
    page: 2,
    page_size: 200,
  });
  assert.deepEqual(buildResourceQuery(), { search: undefined, domain: undefined, page: 1, page_size: 20 });
});

test("maps resource labels", () => {
  assert.equal(resourceDomainLabel("unclassified"), "未分类");
  assert.equal(resourceDomainLabel("media"), "媒体");
  assert.equal(resourceTypeLabel("rate"), "比率");
  assert.equal(resourceTypeLabel("unknown"), "unknown");
});

test("maps selected row keys", () => {
  const selection = resourceRowSelection<{ key: string }>(["me_1"], (keys) => keys);
  assert.equal(selection.selectedRowKeys[0], "me_1");
  assert.deepEqual(selection.onChange([1, "me_2"]), ["1", "me_2"]);
});
