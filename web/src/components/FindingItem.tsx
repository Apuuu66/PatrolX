import { useState, type ReactNode } from "react";
import { Button, Space, Typography } from "antd";

import type { RuleFinding } from "../api/http";
import { CopyTextButton } from "./CopyTextButton";
import { SeverityTag } from "./StatusBadge";
import {
  parseFindingEvidence,
  sliceEvidenceParts,
  type EvidencePart,
} from "../utils/findingEvidence";

/** 把解析出的关键数值包成高亮 span，其余文本保持原样（FR-013）。 */
function renderHighlights(value: string, highlights: readonly string[]): ReactNode {
  if (highlights.length === 0) return value;

  const nodes: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const raw of highlights) {
    if (!raw) continue;
    const index = value.indexOf(raw, cursor);
    if (index < 0) continue;
    if (index > cursor) nodes.push(value.slice(cursor, index));
    nodes.push(
      <span key={`highlight-${key}`} className="rule-finding-highlight">
        {raw}
      </span>,
    );
    key += 1;
    cursor = index + raw.length;
  }
  if (cursor === 0) return value;
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}

function EvidenceParts({ parts }: { parts: readonly EvidencePart[] }) {
  return (
    <span className="rule-finding-evidence" data-testid="finding-evidence-parts">
      {parts.map((part, index) => (
        <span key={`${part.label ?? "text"}-${index}`} className="rule-finding-evidence-part" data-evidence-part="">
          {part.label ? (
            <span className="rule-finding-evidence-label">{part.label}</span>
          ) : null}
          <span className="rule-finding-evidence-value">
            {renderHighlights(part.value, part.highlights)}
          </span>
        </span>
      ))}
    </span>
  );
}

function FindingField({
  label,
  testId,
  children,
}: {
  label: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div className="rule-finding-field" data-testid={testId}>
      <span className="rule-finding-field-label">{label}</span>
      <div className="rule-finding-field-value">{children}</div>
    </div>
  );
}

export interface FindingItemProps {
  finding: RuleFinding;
}

/**
 * 单条发现：严重度 + 标题，来源 / 证据 / 详情 / 建议分行渲染（FR-012、FR-013、FR-014、R8）。
 *
 * - 证据按 `；` 拆成键值分段，关键数值高亮；
 * - 超过 4 行默认折叠，可展开 / 收起；
 * - 来源路径可一键复制；
 * - 解析失败（自由文本）时按原文降级，不丢信息。
 */
export function FindingItem({ finding }: FindingItemProps) {
  const [expanded, setExpanded] = useState(false);
  const evidence = parseFindingEvidence(finding.evidence);
  const parts = evidence
    ? evidence.collapsed && !expanded
      ? sliceEvidenceParts(evidence.parts)
      : evidence.parts
    : [];

  return (
    <div className="rule-finding" data-testid="finding-item" data-finding-id={finding.finding_id}>
      <Space size={8} wrap>
        <SeverityTag severity={finding.severity} variant="plain" />
        <Typography.Text strong>{finding.title}</Typography.Text>
      </Space>
      <div className="rule-finding-body">
        {finding.source_file ? (
          <FindingField label="来源" testId="finding-field-source">
            <span className="rule-finding-source">
              <code title={finding.source_file}>{finding.source_file}</code>
              <CopyTextButton text={finding.source_file} label="来源路径" />
            </span>
          </FindingField>
        ) : null}
        {evidence ? (
          <FindingField label="证据" testId="finding-field-evidence">
            <EvidenceParts parts={parts} />
            {evidence.collapsed ? (
              <Button
                type="link"
                size="small"
                className="rule-finding-toggle"
                aria-expanded={expanded}
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? "收起证据" : "展开其余证据"}
              </Button>
            ) : null}
          </FindingField>
        ) : null}
        {finding.details ? (
          <FindingField label="详情" testId="finding-field-details">
            {finding.details}
          </FindingField>
        ) : null}
        {finding.recommendation ? (
          <FindingField label="建议" testId="finding-field-recommendation">
            {finding.recommendation}
          </FindingField>
        ) : null}
      </div>
    </div>
  );
}
