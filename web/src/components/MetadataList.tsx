export interface MetadataListItem {
  key: string;
  label: string;
  value: string;
}

export interface MetadataListProps {
  items: readonly MetadataListItem[];
  emptyText?: string;
  className?: string;
}

/**
 * 轻量键值元数据：label 次要色 + value 主色，4px 间距，不产生彩色 Tag 噪音。
 * 数据来源统一复用 getTaskMetadataTags 输出或页面按 FR-014 组装的同类结构（DESIGN.md Metadata Tag）。
 */
export function MetadataList({ items, emptyText = "-", className }: MetadataListProps) {
  if (items.length === 0) {
    return <span className="metadata-list-empty">{emptyText}</span>;
  }

  return (
    <span className={`metadata-list${className ? ` ${className}` : ""}`}>
      {items.map((item) => (
        <span key={item.key} className="metadata-list-item" data-metadata-key={item.key}>
          <span className="metadata-list-label">{item.label}</span>
          <span className="metadata-list-value" title={item.value}>
            {item.value}
          </span>
        </span>
      ))}
    </span>
  );
}
