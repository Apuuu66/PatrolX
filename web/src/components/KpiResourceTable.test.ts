import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildResourceDomainFilterOptions,
  buildResourceQuery,
  resourceDomainLabel,
  resourceRowSelection,
} from "./kpiResourceModel.ts";

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
  assert.equal(resourceDomainLabel("reserved"), "预留");
});

test("maps selected row keys", () => {
  const selection = resourceRowSelection<{ key: string }>(["me_1"], (keys) => keys);
  assert.equal(selection.selectedRowKeys[0], "me_1");
  assert.deepEqual(selection.onChange([1, "me_2"]), ["1", "me_2"]);
});

test("builds compact domain filter options", () => {
  const summary = { unclassified: 10, call: 72, api: 34, media: 12, reserved: 0 };
  assert.deepEqual(buildResourceDomainFilterOptions(summary, 128), [
    { value: "all", label: "全部", count: 128 },
    { value: "unclassified", label: "未分类", count: 10 },
    { value: "call", label: "呼叫", count: 72 },
    { value: "api", label: "API", count: 34 },
    { value: "media", label: "媒体", count: 12 },
    { value: "reserved", label: "预留", count: 0 },
  ]);
});
