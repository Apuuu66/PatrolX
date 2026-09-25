import { Alert, Button, Empty, Skeleton } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

export function PageSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="page-skeleton" aria-label="页面加载中">
      <Skeleton active paragraph={{ rows: 2 }} />
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton
          key={index}
          active
          avatar={false}
          title
          paragraph={{ rows: 2 }}
          style={{ marginTop: index === 0 ? 20 : 16 }}
        />
      ))}
    </div>
  );
}

export function LoadErrorState({
  title = "加载失败",
  description,
  onRetry,
  retrying = false,
}: {
  title?: string;
  description?: string;
  onRetry: () => void;
  retrying?: boolean;
}) {
  return (
    <Alert
      className="page-error-state"
      type="error"
      showIcon
      message={title}
      description={description}
      action={
        <Button size="small" icon={<ReloadOutlined />} loading={retrying} onClick={onRetry}>
          重试
        </Button>
      }
    />
  );
}

export function EmptyState({ description }: { description: string }) {
  return <Empty className="page-empty-state" description={description} />;
}
