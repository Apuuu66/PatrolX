import { useEffect, useMemo, useState } from "react";
import { App, Breadcrumb, Card, Empty, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Link, useParams } from "react-router-dom";
import { api, type LogEntry } from "../api/http";

const LEVEL_COLOR: Record<string, string> = {
  info: "blue",
  warn: "gold",
  error: "red",
  debug: "default",
};

const LEVEL_OPTIONS = [
  { value: "error", label: "error" },
  { value: "warn", label: "warn" },
  { value: "info", label: "info" },
  { value: "debug", label: "debug" },
];

export function LogsPage() {
  const { taskId = "" } = useParams();
  const { message } = App.useApp();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [level, setLevel] = useState<string | undefined>();
  const [ruleCode, setRuleCode] = useState<string | undefined>();

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

  const ruleOptions = useMemo(
    () =>
      Array.from(new Set(entries.map((entry) => entry.rule_code).filter(Boolean) as string[])).map((code) => ({
        value: code,
        label: code,
      })),
    [entries],
  );

  const filtered = useMemo(
    () =>
      entries.filter((entry) => {
        if (level && entry.level !== level) return false;
        if (ruleCode && entry.rule_code !== ruleCode) return false;
        return true;
      }),
    [entries, level, ruleCode],
  );

  const columns: ColumnsType<LogEntry> = [
    {
      title: "时间",
      dataIndex: "ts",
      width: 130,
      render: (value: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {dayjs(value).format("HH:mm:ss.SSS")}
        </Typography.Text>
      ),
    },
    {
      title: "级别",
      dataIndex: "level",
      width: 90,
      render: (value: string) => <Tag color={LEVEL_COLOR[value] ?? "default"}>{value}</Tag>,
    },
    { title: "规则", dataIndex: "rule_code", width: 190, render: (value?: string) => value ?? "-" },
    { title: "消息", dataIndex: "message" },
  ];

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
      <Card
        title={`执行日志（${filtered.length}）`}
        extra={
          <Space wrap>
            <Select
              allowClear
              placeholder="级别"
              style={{ width: 120 }}
              value={level}
              options={LEVEL_OPTIONS}
              onChange={setLevel}
            />
            <Select
              allowClear
              showSearch
              placeholder="规则"
              style={{ width: 200 }}
              value={ruleCode}
              options={ruleOptions}
              onChange={setRuleCode}
            />
          </Space>
        }
      >
        {loading ? (
          <Empty description="加载中" />
        ) : filtered.length === 0 ? (
          <Empty description="暂无匹配日志" />
        ) : (
          <Table
            rowKey={(record) => `${record.ts}-${record.rule_code ?? ""}-${record.message}`}
            size="small"
            dataSource={filtered}
            columns={columns}
            pagination={{ pageSize: 50, showSizeChanger: false }}
            expandable={{
              rowExpandable: (record) => Object.keys(record.detail ?? {}).length > 0,
              expandedRowRender: (record) => (
                <Typography.Paragraph
                  code
                  style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                >
                  {JSON.stringify(record.detail, null, 2)}
                </Typography.Paragraph>
              ),
            }}
          />
        )}
      </Card>
    </div>
  );
}
