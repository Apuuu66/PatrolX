import { Card, Empty, List, Space, Tag, Typography } from "antd";
import { LoadErrorState } from "../PageState";
import dayjs from "dayjs";
import type { LogEntry } from "../../api/http";

type TaskLogsPanelProps = {
  logs: LogEntry[];
  error: string | null;
  onRetry: () => void;
  retrying: boolean;
};

export function TaskLogsPanel({ logs, error, onRetry, retrying }: TaskLogsPanelProps) {
  return (
    <Card title="执行日志">
      {error ? (
        <LoadErrorState description={error} onRetry={onRetry} retrying={retrying} />
      ) : logs.length === 0 ? (
        <Empty description="暂无日志" />
      ) : (
        <List
          size="small"
          dataSource={logs}
          renderItem={(entry) => (
            <List.Item>
              <div className="task-log-item">
                <Space>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {dayjs(entry.ts).format("HH:mm:ss.SSS")}
                  </Typography.Text>
                  <Tag color={entry.level === "error" ? "red" : entry.level === "warn" ? "gold" : "blue"}>
                    {entry.level}
                  </Tag>
                  {entry.rule_code && <Tag>{entry.rule_code}</Tag>}
                </Space>
                <div className="task-log-message">{entry.message}</div>
              </div>
            </List.Item>
          )}
        />
      )}
    </Card>
  );
}
