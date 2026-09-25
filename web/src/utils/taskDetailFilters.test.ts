import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { applyTaskDetailFilters, parseTaskDetailFilters } from "./taskDetailFilters.ts";

describe("parseTaskDetailFilters", () => {
  it("解析默认的任务详情筛选状态", () => {
    assert.deepEqual(parseTaskDetailFilters(new URLSearchParams()), {
      tab: "rules",
      status: null,
      category: null,
      search: "",
      sort: "default",
    });
  });

  it("解析合法的 URL 筛选参数", () => {
    const params = new URLSearchParams("view=logs&status=fail&category=log&search=dns&sort=severity");
    assert.deepEqual(parseTaskDetailFilters(params), {
      tab: "logs",
      status: "fail",
      category: "log",
      search: "dns",
      sort: "severity",
    });
  });

  it("忽略非法的 URL 筛选参数", () => {
    const params = new URLSearchParams("view=unknown&status=bad&sort=bad");
    assert.deepEqual(parseTaskDetailFilters(params), {
      tab: "rules",
      status: null,
      category: null,
      search: "",
      sort: "default",
    });
  });
});

describe("applyTaskDetailFilters", () => {
  it("更新筛选参数并清理空值", () => {
    const current = new URLSearchParams("keep=1&status=fail&category=log");
    const next = applyTaskDetailFilters(current, { status: null, category: "config", search: " dns " });

    assert.equal(next.get("keep"), "1");
    assert.equal(next.get("category"), "config");
    assert.equal(next.get("search"), "dns");
    assert.equal(next.has("status"), false);
  });
});
