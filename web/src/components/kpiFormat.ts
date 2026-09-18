/** 格式化 KPI 数值：整数保留千分位，小数最多保留 3 位。 */
export function formatKpiNumber(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return "-";

  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 3,
  }).format(number);
}
