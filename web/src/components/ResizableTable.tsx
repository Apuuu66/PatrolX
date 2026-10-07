import { Table as AntTable, type TableProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type ReactNode,
  type ThHTMLAttributes,
} from "react";

type ResizableHeaderCellProps = ThHTMLAttributes<HTMLTableCellElement> & {
  children?: ReactNode;
  onResize?: (width: number) => void;
  "data-column-key"?: string;
  "data-column-width"?: string;
};

type HeaderCellProps = Record<string, unknown> & { onResize?: (width: number) => void };

const MIN_COLUMN_WIDTH = 64;
const HANDLE_WIDTH = 8;

function ResizableHeaderCell({
  children,
  onResize,
  style,
  "data-column-key": columnKey,
  "data-column-width": columnWidth,
  ...cellProps
}: ResizableHeaderCellProps) {
  const cellRef = useRef<HTMLTableCellElement>(null);
  const columnWidthRef = useRef(columnWidth);
  const onResizeRef = useRef(onResize);
  columnWidthRef.current = columnWidth;
  onResizeRef.current = onResize;

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLSpanElement>) => {
      const cell = cellRef.current;
      if (!cell || (event.button !== undefined && event.button > 0)) return;
      event.preventDefault();
      event.stopPropagation();

      const startX = Number.isFinite(event.clientX) ? event.clientX : 0;
      const startWidth = Number(columnWidthRef.current) || cell.getBoundingClientRect().width;
      const cellStyle = cell.style;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        if (!Number.isFinite(moveEvent.clientX)) return;
        const nextWidth = Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + moveEvent.clientX - startX));
        onResizeRef.current?.(nextWidth);
      };
      const stopResize = () => {
        cellStyle.userSelect = "";
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", stopResize);
        window.removeEventListener("pointercancel", stopResize);
      };

      cellStyle.userSelect = "none";
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", stopResize);
      window.addEventListener("pointercancel", stopResize);
    },
    [],
  );

  const mergedStyle: CSSProperties = {
    ...(style ?? {}),
    position: style?.position === "sticky" ? "sticky" : "relative",
  };

  return (
    <th {...cellProps} ref={cellRef} style={mergedStyle}>
      {children}
      <span
        aria-hidden="true"
        data-column-width={columnWidth}
        data-testid={`column-resize-handle-${columnKey ?? ""}`}
        className="column-resize-handle"
        onPointerDown={handlePointerDown}
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          width: HANDLE_WIDTH,
          cursor: "col-resize",
          touchAction: "none",
          zIndex: 1,
        }}
      />
    </th>
  );
}

function columnKey(column: unknown, index: number): string {
  const typedColumn = column as { key?: unknown; dataIndex?: unknown };
  if (typedColumn.key !== undefined) return String(typedColumn.key);
  if (typedColumn.dataIndex !== undefined) {
    return Array.isArray(typedColumn.dataIndex)
      ? typedColumn.dataIndex.join(".")
      : String(typedColumn.dataIndex);
  }
  return String(index);
}

function useResizableColumns<T extends object>(columns: ColumnsType<T> | undefined): ColumnsType<T> | undefined {
  const [widths, setWidths] = useState<Record<string, number>>({});

  return useMemo(
    () =>
      columns?.map((column, index) => {
        const key = columnKey(column, index);
        const resizedWidth = widths[key];
        const width = "width" in column ? column.width : undefined;
        const nextColumn = {
          ...column,
          width: resizedWidth ?? width,
          onHeaderCell: (data) => {
            const originalProps = column.onHeaderCell?.(data) as HeaderCellProps | undefined;
            return {
              ...(originalProps ?? {}),
              "data-column-key": key,
              "data-column-width": typeof resizedWidth === "number" || typeof width === "number"
                ? String(resizedWidth ?? width)
                : undefined,
              onResize: (nextWidth: number) => setWidths((current) => ({ ...current, [key]: nextWidth })),
            } as HTMLAttributes<HTMLElement>;
          },
        } as ColumnsType<T>[number];
        return nextColumn;
      }),
    [columns, widths],
  );
}

export function ResizableTable<T extends object>(
  props: TableProps<T>,
) {
  const columns = useResizableColumns(props.columns);
  const hasResizableWidths = useMemo(
    () => columns?.some((column) => "width" in column && column.width !== undefined) ?? false,
    [columns],
  );

  return (
    <AntTable<T>
      {...props}
      columns={columns}
      tableLayout={props.tableLayout ?? (hasResizableWidths ? "fixed" : "auto")}
      components={{
        ...props.components,
        header: {
          ...props.components?.header,
          cell: ResizableHeaderCell,
        },
      }}
    />
  );
}

export const Table = ResizableTable;
