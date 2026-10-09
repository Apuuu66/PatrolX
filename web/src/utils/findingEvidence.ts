/**
 * 发现证据结构化（FR-012、FR-013、FR-014、R8、data-model §3）。
 *
 * 契约中的 evidence 仍是字符串：这里只做展示层拆分，解析失败时降级为原文，保证不丢信息。
 */

export interface EvidencePart {
  /** `键：值` / `键 值` 结构中的键；自由文本没有键。 */
  label?: string;
  value: string;
  /** 需要高亮的数字、次数、时长等关键数值。 */
  highlights: string[];
}

export interface FindingEvidenceView {
  parts: EvidencePart[];
  /** 渲染行数超过阈值（4 行）时默认折叠（FR-014）。 */
  collapsed: boolean;
  /** 原始证据文本，折叠与降级时都以此为准。 */
  raw: string;
}

/** 折叠阈值：超过 4 行默认折叠（FR-014）。 */
export const EVIDENCE_COLLAPSE_LINES = 4;

/** 单行可容纳字符数，用于估算渲染行数（中文按全角估算）。 */
const CHARS_PER_LINE = 42;

const KEY_VALUE_PATTERN = /^([^：:]{1,16})[：:]\s*(.+)$/;
const KEY_SPACE_VALUE_PATTERN = /^([^\s：:]{1,16})\s+(.+)$/;
const HIGHLIGHT_PATTERN =
  /\d+(?:\.\d+)?\s*(?:次|条|个|处|项|组|秒|分钟|小时|天|ms|毫秒|%|％)?/g;

export function splitEvidenceSegments(evidence: string): string[] {
  return evidence
    .split(/[；;]/)
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
}

function extractHighlights(value: string): string[] {
  const matches = value.match(HIGHLIGHT_PATTERN) ?? [];
  return matches.map((match) => match.trim()).filter((match) => /\d/.test(match));
}

function buildPart(segment: string): EvidencePart {
  const keyValue = segment.match(KEY_VALUE_PATTERN);
  if (keyValue) {
    const label = keyValue[1]!.trim();
    const value = keyValue[2]!.trim();
    return { label, value, highlights: extractHighlights(value) };
  }

  const keySpaceValue = segment.match(KEY_SPACE_VALUE_PATTERN);
  if (keySpaceValue && /\d/.test(keySpaceValue[2]!)) {
    const label = keySpaceValue[1]!.trim();
    const value = keySpaceValue[2]!.trim();
    return { label, value, highlights: extractHighlights(value) };
  }

  return { value: segment, highlights: extractHighlights(segment) };
}

/** 单个分段占用的估算行数：键名单独一行，值按字符数折算。 */
function partLines(part: EvidencePart): number {
  return Math.max(1, Math.ceil(part.value.length / CHARS_PER_LINE)) + (part.label ? 1 : 0);
}

/** 估算证据渲染行数。 */
export function estimateEvidenceLines(parts: readonly EvidencePart[]): number {
  return parts.reduce((total, part) => total + partLines(part), 0);
}

/**
 * 折叠时保留的证据分段：按估算行数截取前 `maxLines` 行，至少保留一段（FR-014）。
 */
export function sliceEvidenceParts(
  parts: readonly EvidencePart[],
  maxLines: number = EVIDENCE_COLLAPSE_LINES,
): EvidencePart[] {
  if (parts.length === 0) return [];
  if (maxLines <= 0) return parts.slice(0, 1);

  const visible: EvidencePart[] = [];
  let lines = 0;
  for (const part of parts) {
    const cost = partLines(part);
    if (visible.length > 0 && lines + cost > maxLines) break;
    visible.push(part);
    lines += cost;
  }
  return visible;
}

/**
 * 解析证据文本；空值返回 null（由调用方决定空态文案）。
 * 解析结果始终保留原始文本，任何异常结构都按自由文本降级。
 */
export function parseFindingEvidence(
  evidence?: string | null,
): FindingEvidenceView | null {
  if (evidence === null || evidence === undefined) return null;
  const raw = evidence.trim();
  if (!raw) return null;

  const segments = splitEvidenceSegments(raw);
  const source = segments.length > 0 ? segments : [raw];
  const parts = source.map(buildPart).filter((part) => part.value.length > 0);

  return {
    parts: parts.length > 0 ? parts : [{ value: raw, highlights: [] }],
    collapsed: estimateEvidenceLines(parts) > EVIDENCE_COLLAPSE_LINES,
    raw,
  };
}
