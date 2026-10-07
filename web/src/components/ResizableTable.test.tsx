import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResizableTable } from "./ResizableTable";
import type { ColumnsType } from "antd/es/table";

type Row = { key: string; name: string; value: string };

function pointerEvent(type: string, clientX: number) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clientX", { value: clientX });
  Object.defineProperty(event, "pointerId", { value: 1 });
  return event;
}

describe("ResizableTable", () => {
  it("renders column resize handles and updates column width while dragging", () => {
    const columns: ColumnsType<Row> = [
      { title: "名称", dataIndex: "name", key: "name", width: 120 },
      { title: "值", dataIndex: "value", key: "value", width: 180 },
    ];
    const { container } = render(
      <ResizableTable<Row>
        rowKey="key"
        columns={columns}
        dataSource={[{ key: "row", name: "名称值", value: "值" }]}
        pagination={false}
      />,
    );
    const handle = container.querySelector<HTMLElement>('[data-testid="column-resize-handle-name"]');
    expect(handle).not.toBeNull();
    const firstCol = container.querySelector<HTMLElement>(".ant-table colgroup col");
        expect(firstCol?.style.width).toBe("120px");

    if (!handle) return;
    fireEvent(handle, pointerEvent("pointerdown", 120));
    fireEvent(window, pointerEvent("pointermove", 200));
    fireEvent(window, pointerEvent("pointerup", 200));
    const resizedCol = container.querySelector<HTMLElement>(".ant-table colgroup col");
    expect(resizedCol?.style.width).toBe("200px");

    const secondHandle = container.querySelector<HTMLElement>('[data-testid="column-resize-handle-name"]');
    if (!secondHandle) throw new Error("second resize handle not found");
    expect(secondHandle.dataset.columnWidth).toBe("200");
    fireEvent(secondHandle, pointerEvent("pointerdown", 200));
    fireEvent(window, pointerEvent("pointermove", 180));
    fireEvent(window, pointerEvent("pointerup", 180));
    const secondResizedCol = container.querySelector<HTMLElement>(".ant-table colgroup col");
    expect(secondResizedCol?.style.width).toBe("180px");
  });
});
