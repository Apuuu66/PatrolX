import type { RuleStatus } from "../api/http";

/**
 * 文本安全状态色（FR-019、SC-006、R13）。
 *
 * 填充色继续使用 `statusLabels.ts` 的标准状态色；只有在把状态色用于文字时改用这里的更深色阶，
 * 保证白底对比度 ≥ 4.5:1。research R13 给出的 warn/pass 原始色阶未达 AA，实现时下移到
 * gold-8 / green-8 并在 verification.md 记录偏差。
 */
export const STATUS_TEXT_COLORS: Record<RuleStatus, string> = {
  pass: "#237804",
  warn: "#874d00",
  fail: "#cf1322",
  error: "#595959",
  skip: "#0958d9",
};

/** 取状态文本色；未知状态回退兜底色，避免渲染出 undefined。 */
export function getStatusTextColor(status: string, fallback = "inherit"): string {
  return STATUS_TEXT_COLORS[status as RuleStatus] ?? fallback;
}

function toRgb(color: string): [number, number, number] | null {
  const value = color.trim().replace(/^#/, "");
  if (/^[0-9a-f]{3}$/i.test(value)) {
    return [0, 2, 4].map((index) => Number.parseInt(value[index]! + value[index]!, 16)) as [
      number,
      number,
      number,
    ];
  }
  if (/^[0-9a-f]{6}$/i.test(value)) {
    return [0, 2, 4].map((index) => Number.parseInt(value.slice(index, index + 2), 16)) as [
      number,
      number,
      number,
    ];
  }
  return null;
}

function relativeLuminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2.x 相对对比度；非法色值返回 1（最低对比度）。 */
export function contrastRatio(foreground: string, background: string): number {
  const fg = toRgb(foreground);
  const bg = toRgb(background);
  if (!fg || !bg) return 1;
  const fgLuminance = relativeLuminance(fg);
  const bgLuminance = relativeLuminance(bg);
  const lighter = Math.max(fgLuminance, bgLuminance);
  const darker = Math.min(fgLuminance, bgLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}
