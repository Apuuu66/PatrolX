import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime.js";
import "dayjs/locale/zh-cn.js";

dayjs.extend(relativeTime);

/** 数字等宽类名：时间、耗时、计数共用（FR-007、R4）。 */
export const TABULAR_NUMERIC_CLASS = "tabular-nums";

export const TIME_PLACEHOLDER = "-";

const FULL_TIME_FORMAT = "YYYY-MM-DD HH:mm:ss";

function parseTime(value?: string | null) {
  if (value === null || value === undefined) return null;
  const raw = value.trim();
  if (!raw) return null;
  const parsed = dayjs(raw);
  return parsed.isValid() ? parsed : null;
}

/** 中文相对时间（如"3 小时前"）；空值或非法时间返回占位符，不抛错（FR-006、FR-017）。 */
export function formatRelativeTime(value?: string | null): string {
  const parsed = parseTime(value);
  if (!parsed) return TIME_PLACEHOLDER;
  return parsed.locale("zh-cn").fromNow();
}

/** 完整时间，用于 Tooltip（FR-007）。 */
export function formatFullTime(value?: string | null): string {
  const parsed = parseTime(value);
  return parsed ? parsed.format(FULL_TIME_FORMAT) : TIME_PLACEHOLDER;
}

export interface RelativeTimeDisplay {
  /** 列表可见文本：相对时间或占位符。 */
  text: string;
  /** Tooltip 文案：完整时间；无有效时间时为空字符串（不渲染 Tooltip）。 */
  title: string;
}

/** 相对时间 + 完整时间 Tooltip 的一体化展示值（FR-006、FR-007）。 */
export function getRelativeTimeDisplay(value?: string | null): RelativeTimeDisplay {
  const text = formatRelativeTime(value);
  const title = formatFullTime(value);
  return { text, title: title === TIME_PLACEHOLDER ? "" : title };
}
