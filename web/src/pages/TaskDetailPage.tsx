import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Breadcrumb,
  Button,
  Card,
  Descriptions,
  Empty,
  Popconfirm,
  Space,
  Spin,
  Table,
  Typography,
} from "antd";
import { FileTextOutlined, RedoOutlined, RollbackOutlined, UnorderedListOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type RuleResult, type RuleStatus, type SystemInspection, type TaskSummary } from "../api/http";
import { RuleStatusTag, SeverityTag, TaskStatusTag } from "../components/StatusBadge";
import { SummaryCards } from "../components/SummaryCards";
import { usePolling } from "../hooks/usePolling";
import { countByStatus, filterByStatus, toggleStatusFilter, type StatusFilter } from "../utils/taskFilter";

const CATEGORY_LABELS: Record<string, string> = {
  log: "日志",
  kpi: "KPI",
  traffic: "话统",
  alarm: "告警",
  config: "配置",
  resource: "资源",
  other: "其他",
};

export function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [task, setTask] = useState<TaskSummary | null>(null);
  const [system, setSystem] = useState<SystemInspection | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(null);

  const load = useCallback(async () => {
    try {
      const [t, s, inspectors] = await Promise.all([
        api.getTask(taskId),
        api.getSystem(taskId).catch(() => null),
        api.listInspectors(undefined, true),
      ]);
      setTask(t);
      setSystem(s);
      setHidden(new Set(inspectors.filter((i) => i.hidden).map((i) => i.code)));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [taskId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  const busy = task?.status === "pending" || task?.status === "running";
  usePolling(load, 2000, !!busy);

  const rerunAll = async () => {
    try {
      await api.rerunTask(taskId);
      message.success("已受理全量重跑");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重跑失败");
    }
  };

  const rerunOne = async (code: string) => {
    try {
      await api.rerunTask(taskId, [code]);
      message.success(`已受理重跑 ${code}`);
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重跑失败");
    }
  };

  const handleStatusClick = useCallback(
    (status: RuleStatus) => {
      setStatusFilter((prev) => toggleStatusFilter(prev, status));
    },
    [],
  );

  const rules = useMemo(() => (system?.rules ?? []).filter((r) => !hidden.has(r.code)), [system, hidden]);

  const statusCounts = useMemo(() => countByStatus(rules), [rules]);

  const filteredRules = useMemo(() => filterByStatus(rules, statusFilter), [rules, statusFilter]);

  const grouped = useMemo(() => {
    const map = new Map<string, RuleResult[]>();
    for (const rule of filteredRules) map.set(rule.category, [...(map.get(rule.category) ?? []), rule]);
    return Array.from(map.entries());
  }, [filteredRules]);

  const columns: ColumnsType<RuleResult> = [
    {
      title: "规则",
      dataIndex: "code",
      render: (_, record) => (
        <div>
          <Typography.Link onClick={() => navigate(`/tasks/${taskId}/rules/${record.code}`)}>{record.name}</Typography.Link>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: "block" }}>
            {record.code}
          </Typography.Text>
        </div>
      ),
    },
    { title: "状态", dataIndex: "status", width: 90, render: (v, r) => <RuleStatusTag status={v} skipReason={r.skip_reason} /> },
    { title: "严重度", dataIndex: "severity", width: 90, render: (v: string) => <SeverityTag severity={v} /> },
    { title: "结果摘要", dataIndex: "summary" },
    { title: "耗时", dataIndex: "duration_ms", width: 90, render: (v: number | null) => (v == null ? "-" : `${v}ms`) },
    {
      title: "操作",
      width: 150,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => navigate(`/tasks/${taskId}/rules/${record.code}`)}>
            详情
          </Button>
          <Popconfirm title={`重跑规则 ${record.code}？`} onConfirm={() => rerunOne(record.code)}>
            <Button size="small" type="link" icon={<RedoOutlined />}>
              重跑
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin />
      </div>
    );
  }

  if (!task) {
    return <Empty description="任务不存在" />;
  }

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[{ title: <Link to="/tasks">巡检任务</Link> }, { title: task.name }]}
      />
      <Card
        title={
          <Space>
            <Typography.Text strong>{task.name}</Typography.Text>
            <TaskStatusTag status={task.status} />
          </Space>
        }
        extra={
          <Space>
            <Button icon={<RollbackOutlined />} onClick={() => navigate("/tasks")}>
              返回列表
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => navigate(`/tasks/${taskId}/report`)}>
              查看报告
            </Button>
            <Button icon={<UnorderedListOutlined />} onClick={() => navigate(`/tasks/${taskId}/logs`)}>
              执行日志
            </Button>
            <Popconfirm title="重跑全部规则？" onConfirm={() => void rerunAll()}>
              <Button type="primary" icon={<RedoOutlined />}>
                重跑全部
              </Button>
            </Popconfirm>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <SummaryCards
          stats={task.stats}
          statusCounts={statusCounts}
          activeStatus={statusFilter}
          onStatusClick={handleStatusClick}
        />
        <Descriptions
          size="small"
          column={4}
          style={{ marginTop: 16 }}
          items={[
            { key: "system_id", label: "系统标识", children: system?.system_id ?? "-" },
            { key: "package", label: "数据包", children: system?.package_file ?? "-" },
            { key: "version", label: "版本", children: system?.version ?? "-" },
            {
              key: "customer",
              label: "客户信息",
              children: system?.customer && Object.keys(system.customer).length ? JSON.stringify(system.customer) : "-",
            },
            { key: "mode", label: "模式", children: task.mode === "online" ? "在线" : "本地" },
            { key: "trigger", label: "触发方式", children: task.trigger },
            { key: "created_at", label: "创建时间", children: dayjs(task.created_at).format("YYYY-MM-DD HH:mm:ss") },
            {
              key: "completed_at",
              label: "完成时间",
              children: task.completed_at ? dayjs(task.completed_at).format("YYYY-MM-DD HH:mm:ss") : "-",
            },
          ]}
        />
      </Card>

      {grouped.length === 0 && statusFilter !== null && (
        <Card style={{ marginBottom: 16 }}>
          <Empty description={`当前状态"${statusFilter}"没有规则结果`} />
        </Card>
      )}
      {grouped.map(([category, list]) => (
        <Card
          key={category}
          title={`${CATEGORY_LABELS[category] ?? category}（${list.length}）`}
          style={{ marginBottom: 16 }}
        >
          <Table rowKey="code" size="small" columns={columns} dataSource={list} pagination={false} />
        </Card>
      ))}
    </div>
  );
}
