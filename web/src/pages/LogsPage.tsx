import { useEffect, useState } from "react";
import { App, Breadcrumb, Card, Empty, List, Space, Spin, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { Link, useParams } from "react-router-dom";
import { api, type LogEntry } from "../api/http";

const LEVEL_COLOR: Record<string, string> = {
  info: "blue",
  warn: "gold",
  error: "red",
  debug: "default",
};

export function LogsPage() {
  const { taskId = "" } = useParams();
  const { message } = App.useApp();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const data = await api.getTaskLogs(taskId);
        setEntries(data.entries);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [taskId, message]);

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link to="/tasks">巡检任务</Link> },
          { title: <Link to={`/tasks/${taskId}`}>任务详情</Link> },
          { title: "执行日志" },
        ]}
      />
      <Card title="执行日志">
        {loading ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : entries.length === 0 ? (
          <Empty description="暂无日志" />
        ) : (
          <List
            size="small"
            dataSource={entries}
            renderItem={(e) => (
              <List.Item>
                <div style={{ width: "100%" }}>
                  <Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {dayjs(e.ts).format("HH:mm:ss.SSS")}
                    </Typography.Text>
                    <Tag color={LEVEL_COLOR[e.level] ?? "default"}>{e.level}</Tag>
                    {e.rule_code && <Tag>{e.rule_code}</Tag>}
                  </Space>
                  <div style={{ marginTop: 2 }}>{e.message}</div>
                  {Object.keys(e.detail ?? {}).length > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {JSON.stringify(e.detail)}
                    </Typography.Text>
                  )}
                </div>
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  );
}
