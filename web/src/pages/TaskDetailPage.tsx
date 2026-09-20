import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Breadcrumb,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import { ClearOutlined, DownloadOutlined, FileTextOutlined, RedoOutlined, RollbackOutlined, UnorderedListOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  type KpiTaskCatalogSnapshot,
  type RuleResult,
  type RuleStatus,
  type SystemInspection,
  type TaskSummary,
} from "../api/http";
import { RuleStatusTag, SeverityTag, TaskStatusTag } from "../components/StatusBadge";
import { SummaryCards } from "../components/SummaryCards";
import { usePolling } from "../hooks/usePolling";
import { latestTaskFailure } from "../utils/taskFailure";
import { countByStatus, filterByStatus, toggleStatusFilter, type StatusFilter } from "../utils/taskFilter";
import { KpiClassificationClues } from "../components/KpiClassificationClues";

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
  const [catalogSnapshot, setCatalogSnapshot] = useState<KpiTaskCatalogSnapshot | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [rebuildRuleCodes, setRebuildRuleCodes] = useState<string[]>([]);
  const [rebuilding, setRebuilding] = useState(false);

  const load = useCallback(async () => {
    try {
      const [t, s, inspectors, logs] = await Promise.all([
        api.getTask(taskId),
        api.getSystem(taskId, true).catch(() => null),
        api.listInspectors(undefined, true),
        api.getTaskLogs(taskId).catch(() => null),
      ]);
      const snapshot = (s?.rules ?? []).some((rule) => rule.category === "kpi")
        ? await api.getKpiCatalogSnapshot(taskId).catch(() => null)
        : null;
      setTask(t);
      setSystem(s);
      setCatalogSnapshot(snapshot);
      setHidden(new Set(inspectors.filter((i) => i.hidden).map((i) => i.code)));
      setFailure(latestTaskFailure(logs?.entries ?? []));
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
  const canRebuild = task?.status === "completed" || task?.status === "failed";
  usePolling(load, 2000, !!busy);

  const downloadCatalogSnapshot = () => {
    if (!catalogSnapshot) return;
    const blob = new Blob([JSON.stringify(catalogSnapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `kpi_catalog_snapshot_${taskId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

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

  const rebuildIncremental = async () => {
    if (rebuildRuleCodes.length === 0) return;
    setRebuilding(true);
    try {
      await api.rebuildTask(taskId, {
        mode: "incremental",
        confirmed: true,
        rule_codes: rebuildRuleCodes,
        trigger_source: "ui",
      });
      message.success("已受理增量重建");
      setRebuildOpen(false);
      setRebuildRuleCodes([]);
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "增量重建失败");
    } finally {
      setRebuilding(false);
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

  const attentionRules = useMemo(
    () =>
      rules
        .filter((rule) => rule.status === "fail" || rule.status === "warn" || rule.status === "error")
        .sort((left, right) => {
          const weight = { fail: 0, warn: 1, error: 2, pass: 9, skip: 9 } as const;
          return weight[left.status] - weight[right.status];
        }),
    [rules],
  );

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
            <Button
              icon={<ClearOutlined />}
              disabled={busy || !canRebuild}
              loading={rebuilding}
              onClick={() => setRebuildOpen(true)}
            >
              增量重建
            </Button>
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
        <Alert
          style={{ marginTop: 16 }}
          type={attentionRules.length ? "warning" : "success"}
          showIcon
          message={
            attentionRules.length
              ? `重点关注 ${attentionRules.length} 条规则`
              : "巡检完成，未发现需要重点处理的规则"
          }
          description={
            attentionRules.length
              ? "以下规则存在失败、告警或执行异常，建议优先查看结论和证据。"
              : undefined
          }
        />
        <Descriptions
          size="small"
          column={4}
          style={{ marginTop: 16 }}
          items={[
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
        {catalogSnapshot && (
          <Descriptions
            size="small"
            column={3}
            title="KPI 快照"
            style={{ marginTop: 16 }}
            items={[
              {
                key: "captured_at",
                label: "生成时间",
                children: dayjs(catalogSnapshot.captured_at).format("YYYY-MM-DD HH:mm:ss"),
              },
              { key: "metrics", label: "指标数量", children: catalogSnapshot.metrics.length },
              {
                key: "download",
                label: "完整快照",
                children: (
                  <Button size="small" icon={<DownloadOutlined />} onClick={downloadCatalogSnapshot}>
                    下载
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Card>

      {catalogSnapshot && (
        <div style={{ marginBottom: 16 }}>
          <KpiClassificationClues taskId={taskId} />
        </div>
      )}

      {task.status === "failed" && failure && (
        <Alert type="error" showIcon message="任务失败" description={failure} style={{ marginBottom: 16 }} />
      )}

      {attentionRules.length > 0 && (
        <Card
          title={`重点关注（${attentionRules.length}）`}
          style={{ marginBottom: 16 }}
          styles={{ header: { borderColor: "#ffccc7" } }}
        >
          <Table rowKey="code" size="small" columns={columns} dataSource={attentionRules} pagination={false} />
        </Card>
      )}

      <Card title="全部规则" styles={{ body: { paddingTop: 8 } }}>
        {grouped.length === 0 ? (
          <Empty description={statusFilter ? `当前状态"${statusFilter}"没有规则结果` : "暂无规则结果"} />
        ) : (
          <Collapse
            items={grouped.map(([category, list]) => ({
              key: category,
              label: (
                <Space>
                  <span>{CATEGORY_LABELS[category] ?? category}</span>
                  <Tag>{list.length}</Tag>
                </Space>
              ),
              children: (
                <Table rowKey="code" size="small" columns={columns} dataSource={list} pagination={false} />
              ),
            }))}
          />
        )}
      </Card>

      <Modal
        title="增量重建"
        open={rebuildOpen}
        confirmLoading={rebuilding}
        okText="增量重建"
        okButtonProps={{ disabled: rebuildRuleCodes.length === 0 }}
        cancelText="取消"
        onCancel={() => {
          setRebuildOpen(false);
          setRebuildRuleCodes([]);
        }}
        onOk={() => void rebuildIncremental()}
      >
        <Alert
          type="warning"
          showIcon
          message="将强制重建解压现场"
          description="所选规则及其私有准备会重算，未选择规则结果和当前 KPI 快照保持不变。"
          style={{ marginBottom: 16 }}
        />
        <Select
          mode="multiple"
          showSearch
          allowClear
          placeholder="选择要重建重跑的普通规则"
          style={{ width: "100%" }}
          value={rebuildRuleCodes}
          onChange={setRebuildRuleCodes}
          options={rules.map((rule) => ({ value: rule.code, label: `${rule.name} (${rule.code})` }))}
        />
      </Modal>
    </div>
  );
}
