import { TABLE_DENSITY_LABELS, type TableDensity } from "../hooks/useTableDensity";

const OPTIONS: readonly TableDensity[] = ["compact", "comfortable"];

export interface DensitySegmentedProps {
  value: TableDensity;
  onChange: (value: TableDensity) => void;
  className?: string;
}

/**
 * 密度切换控件（FR-016、contracts §6）。
 *
 * 用原生 button + aria-pressed 表达选中态：键盘可操作、读屏可读，且只回调密度值，
 * 不触碰筛选、分页与滚动位置。
 */
export function DensitySegmented({ value, onChange, className }: DensitySegmentedProps) {
  return (
    <div
      role="group"
      aria-label="表格密度"
      data-testid="density-control"
      className={`density-segmented${className ? ` ${className}` : ""}`}
    >
      {OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          className={`density-segmented-option${value === option ? " is-active" : ""}`}
          aria-pressed={value === option}
          onClick={() => {
            // 已是当前密度时不重复回调，避免无意义的偏好写入。
            if (value !== option) onChange(option);
          }}
        >
          {TABLE_DENSITY_LABELS[option]}
        </button>
      ))}
    </div>
  );
}
