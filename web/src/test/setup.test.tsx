/** 测试环境垫片回归：jsdom 未实现带伪元素参数的 window.getComputedStyle。 */

import { render } from "@testing-library/react";
import { Table } from "antd";
import { describe, expect, it, vi } from "vitest";

describe("jsdom 环境垫片", () => {
  it("antd Table 测量滚动条时不触发 jsdom 未实现错误", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(
        <Table
          columns={[{ title: "名称", dataIndex: "name" }]}
          dataSource={[{ key: "1", name: "样例" }]}
          pagination={false}
          scroll={{ y: 120 }}
        />,
      );
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      errorSpy.mockRestore();
    }
  });
});
