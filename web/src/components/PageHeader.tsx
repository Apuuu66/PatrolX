import type { ReactNode } from "react";

export interface PageHeaderProps {
  /** 页面唯一标题（16px / 600）。 */
  title: ReactNode;
  /** 一句话说明（12px 次要色）。 */
  description?: ReactNode;
  /** 面包屑等标题上方内容。 */
  breadcrumb?: ReactNode;
  /** 状态区 slot：状态标签、非零摘要等。 */
  status?: ReactNode;
  /** 操作区 slot；每个页面最多 1 个主操作。 */
  actions?: ReactNode;
  className?: string;
}

/**
 * 统一页头：标题 + 说明 + 状态区 + 操作区。
 * 操作主次分层由调用方保证，页头本身不决定按钮权重（FR-001、FR-004）。
 */
export function PageHeader({
  title,
  description,
  breadcrumb,
  status,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={`page-header${className ? ` ${className}` : ""}`}>
      {breadcrumb ? <div className="page-header-breadcrumb">{breadcrumb}</div> : null}
      <div className="page-header-main">
        <div className="page-header-titles">
          <h1 className="page-header-title">{title}</h1>
          {description ? <p className="page-header-description">{description}</p> : null}
        </div>
        {status || actions ? (
          <div className="page-header-aside">
            {status ? <div className="page-header-status">{status}</div> : null}
            {actions ? <div className="page-header-actions">{actions}</div> : null}
          </div>
        ) : null}
      </div>
    </header>
  );
}
