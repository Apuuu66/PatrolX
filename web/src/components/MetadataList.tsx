import { Button, Popover } from "antd";

import { CopyTextButton } from "./CopyTextButton";

export interface MetadataListItem {
  key: string;
  label: string;
  value: string;
}

export interface MetadataListProps {
  items: readonly MetadataListItem[];
  /** 平铺展示的最大项数，其余收纳进"更多元数据"（FR-010、contracts §4）。 */
  maxVisible?: number;
  className?: string;
}

/** 只有真正有值的字段才渲染；空值与空白值统一在组件内剔除（FR-010、contracts §4）。 */
function withValue(items: readonly MetadataListItem[]): MetadataListItem[] {
  return items.filter((item) => (item.value ?? "").trim().length > 0);
}

function MetadataValue({ item }: { item: MetadataListItem }) {
  return (
    <span className="metadata-list-value">
      <span className="metadata-list-value-text" title={item.value}>
        {item.value}
      </span>
      <CopyTextButton text={item.value} label={`${item.label}值`} className="metadata-list-copy" />
    </span>
  );
}

/**
 * 轻量键值元数据：label 次要色 + value 主色，4px 间距，不产生彩色 Tag 噪音。
 *
 * - 空值 / 空白值不渲染，全部为空时整块隐藏（FR-010、R6）；
 * - 最多平铺 maxVisible（默认 4）项，其余进入"更多元数据"Popover；
 * - 完整值可复制，超长值截断但保留悬浮完整值（contracts §4）。
 */
export function MetadataList({ items, maxVisible = 4, className }: MetadataListProps) {
  const visibleItems = withValue(items);
  if (visibleItems.length === 0) return null;

  const flatItems = visibleItems.slice(0, Math.max(1, maxVisible));
  const overflowItems = visibleItems.slice(flatItems.length);

  return (
    <span className={`metadata-list${className ? ` ${className}` : ""}`}>
      {flatItems.map((item) => (
        <span key={item.key} className="metadata-list-item" data-metadata-key={item.key}>
          <span className="metadata-list-label">{item.label}</span>
          <MetadataValue item={item} />
        </span>
      ))}
      {overflowItems.length > 0 && (
        <Popover
          trigger="click"
          placement="bottomLeft"
          content={
            <div className="metadata-list-more-panel" data-testid="metadata-more-panel">
              {overflowItems.map((item) => (
                <span key={item.key} className="metadata-list-more-item" data-metadata-key={item.key}>
                  <span className="metadata-list-label">{item.label}</span>
                  <MetadataValue item={item} />
                </span>
              ))}
            </div>
          }
        >
          <Button
            type="link"
            size="small"
            className="metadata-list-more-trigger"
            data-testid="metadata-more"
          >
            更多元数据（{overflowItems.length}）
          </Button>
        </Popover>
      )}
    </span>
  );
}
