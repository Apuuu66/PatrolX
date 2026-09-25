import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Breadcrumb,
  Button,
  Card,
  Descriptions,
  Dropdown,
  Empty,
  Modal,
  Input,
  List,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import {
  ClearOutlined,
  FileTextOutlined,
  MoreOutlined,
  RedoOutlined,
  RollbackOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  api,
  type LogEntry,
  reportUrl,
  type RuleResult,
  type RuleStatus,
  type SystemInspection,
  type TaskSummary,
} from "../api/http";
import { RuleStatusTag, SeverityTag, TaskStatusTag } from "../components/StatusBadge";
import { SummaryCards } from "../components/SummaryCards";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { useAuth } from "../auth/AuthContext";
import { usePolling } from "../hooks/usePolling";
import { latestTaskFailure } from "../utils/taskFailure";
import {
  getAttentionSummary,
  getCustomerFields,
  getHealthBarSegments,
} from "../utils/taskDisplay";
import {
  filterRuleResults,
  getRuleCategoryOptions,
  sortRuleResultsByFocus,
  type RuleSortMode,
} from "../utils/ruleResults";
import { countByStatus, filterByStatus, toggleStatusFilter } from "../utils/taskFilter";
import {
  applyTaskDetailFilters,
  parseTaskDetailFilters,
  type TaskDetailTab,
} from "../utils/taskDetailFilters.ts";

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
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [task, setTask] = useState<TaskSummary | null>(null);
  const [system, setSystem] = useState<SystemInspection | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const filters = useMemo(() => parseTaskDetailFilters(searchParams), [searchParams]);
  const updateFilters = useCallback(
    (changes: Parameters<typeof applyTaskDetailFilters>[1]) => {
      setSearchParams(applyTaskDetailFilters(searchParams, changes), { replace: true });
    },
    [searchParams, setSearchParams],
  );
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [rebuildRuleCodes, setRebuildRuleCodes] = useState<string[]>([]);
  const [rebuilding, setRebuilding] = useState(false);
  const [deviceOpen, setDeviceOpen] = useState(false);
  const [deviceValue, setDeviceValue] = useState("");
  const [deviceSaving, setDeviceSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [t, s, inspectors, logs] = await Promise.all([
        api.getTask(taskId),
        api.getSystem(taskId, true).catch(() => null),
        api.listInspectors(undefined, true),
        api.getTaskLogs(taskId).catch(() => null),
      ]);
      setTask(t);
      setSystem(s);
      setHidden(new Set(inspectors.filter((i) => i.hidden).map((i) => i.code)));
      setFailure(latestTaskFailure(logs?.entries ?? []));
      setLogEntries(logs?.entries ?? []);
    } catch (err) {
      const text = err instanceof Error ? err.message : "加载失败";
      setLoadError(text);
      message.error(text);
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

  const saveDeviceId = async () => {
    setDeviceSaving(true);
    try {
      await api.updateTaskDeviceId(taskId, deviceValue.trim());
      message.success("设备 ID 已更新");
      setDeviceOpen(false);
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "设备 ID 更新失败");
    } finally {
      setDeviceSaving(false);
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

  const statusFilter = filters.status;

  const handleStatusClick = useCallback(
    (status: RuleStatus) => {
      updateFilters({ status: toggleStatusFilter(filters.status, status) });
    },
    [filters.status, updateFilters],
  );

  const handleTabChange = useCallback(
    (tab: string) => {
      updateFilters({ tab: tab as TaskDetailTab });
    },
    [updateFilters],
  );

  const rules = useMemo(() => (system?.rules ?? []).filter((r) => !hidden.has(r.code)), [system, hidden]);

  const statusCounts = useMemo(() => countByStatus(rules), [rules]);

  const filteredRules = useMemo(
    () => filterRuleResults(filterByStatus(rules, filters.status), { search: filters.search }),
    [rules, filters.status, filters.search],
  );

  const categoryCounts = useMemo(
    () => getRuleCategoryOptions(rules, filteredRules),
    [rules, filteredRules],
  );
  const sortedRules = useMemo(
    () => sortRuleResultsByFocus(filteredRules, filters.category, filters.sort),
    [filteredRules, filters.category, filters.sort],
  );

  const healthSegments = useMemo(() => (task ? getHealthBarSegments(task.stats) : []), [task]);

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
    {
      title: "分类",
      dataIndex: "category",
      width: 110,
      render: (value: string) => CATEGORY_LABELS[value] ?? value,
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

  if (loading && !task) {
    return <PageSkeleton rows={5} />;
  }

  if (!task) {
    if (loadError) {
      return <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />;
    }
    return <EmptyState description="任务不存在" />;
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
            <Button type="primary" icon={<FileTextOutlined />} onClick={() => navigate(`/tasks/${taskId}/report`)}>
              查看报告
            </Button>
            <Dropdown
              menu={{
                items: [
                  { key: "logs", label: "执行日志", icon: <UnorderedListOutlined /> },
                  { key: "rerun", label: "重跑全部", icon: <RedoOutlined /> },
                  { key: "rebuild", label: "增量重建", disabled: busy || !canRebuild || rebuilding, icon: <ClearOutlined /> },
                  { type: "divider" },
                  { key: "back", label: "返回列表", icon: <RollbackOutlined /> },
                ],
                onClick: ({ key }) => {
                  if (key === "logs") navigate(`/tasks/${taskId}/logs`);
                  if (key === "rerun") void rerunAll();
                  if (key === "rebuild") setRebuildOpen(true);
                  if (key === "back") navigate("/tasks");
                },
              }}
              trigger={["click"]}
            >
              <Button aria-label="更多操作" icon={<MoreOutlined />} />
            </Dropdown>
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
        <div aria-label="规则健康度分布" style={{ marginTop: 16 }}>
          <div
            style={{
              display: "flex",
              height: 8,
              overflow: "hidden",
              borderRadius: 999,
              background: "#f0f0f0",
              gap: 2,
            }}
          >
            {healthSegments.map((segment) => (
              <button
                key={segment.key}
                type="button"
                className="health-bar-segment"
                aria-label={`筛选${segment.label}`}
                aria-pressed={statusFilter === segment.key}
                title={`${segment.label} ${segment.value}`}
                onClick={() => handleStatusClick(segment.key)}
                style={{
                  width: `${segment.percent}%`,
                  backgroundColor: segment.color,
                  minWidth: segment.percent > 0 ? 4 : 0,
                  border: 0,
                  padding: 0,
                  cursor: "pointer",
                  outline: statusFilter === segment.key ? "2px solid rgba(0, 0, 0, 0.65)" : "none",
                  outlineOffset: 1,
                }}
              />
            ))}
          </div>
        </div>
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
              ? `${getAttentionSummary(task.stats)} · 以下规则建议优先查看结论和证据。`
              : undefined
          }
        />
        <Typography.Title level={5} style={{ margin: "18px 0 10px" }}>
          基础信息
        </Typography.Title>
        <Descriptions
          size="small"
          column={4}
          items={[
            { key: "package", label: "数据包", children: system?.package_file ?? "-" },
            { key: "version", label: "版本", children: system?.version ?? "-" },
            { key: "mode", label: "模式", children: task.mode === "online" ? "在线" : "本地" },
            { key: "trigger", label: "触发方式", children: task.trigger },
          ]}
        />

        <Typography.Title level={5} style={{ margin: "18px 0 10px" }}>
          客户与环境
        </Typography.Title>
        <Descriptions
          size="small"
          column={3}
          items={[
            {
              key: "device_id",
              label: "设备 ID",
              children: (
                <Space size={4}>
                  <Typography.Text>{task.device_id ?? system?.customer?.device_id ?? "-"}</Typography.Text>
                  {isAdmin && !busy && (
                    <Button
                      size="small"
                      type="text"
                      onClick={() => {
                        setDeviceValue(task.device_id ?? system?.customer?.device_id ?? "");
                        setDeviceOpen(true);
                      }}
                    >
                      编辑
                    </Button>
                  )}
                </Space>
              ),
            },
            {
              key: "customer",
              label: "客户信息",
              children: (() => {
                const fields = getCustomerFields(system?.customer);
                if (fields.length === 0) return "-";
                return fields.map((field) => `${field.label} ${field.value}`).join(" · ");
              })(),
            },
            { key: "empty", label: "", children: "" },
          ]}
        />

        <Typography.Title level={5} style={{ margin: "18px 0 10px" }}>
          执行时间
        </Typography.Title>
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: "created_at", label: "创建时间", children: dayjs(task.created_at).format("YYYY-MM-DD HH:mm:ss") },
            {
              key: "completed_at",
              label: "完成时间",
              children: task.completed_at ? dayjs(task.completed_at).format("YYYY-MM-DD HH:mm:ss") : "-",
            },
          ]}
        />
      </Card>
        {task.status === "failed" && failure && (
          <Alert type="error" showIcon message={`任务失败：${failure}`} style={{ marginBottom: 16 }} />
        )}

      <Tabs
        activeKey={filters.tab}
        onChange={handleTabChange}
        items={[
          {
            key: "rules",
            label: "规则结果",
            children: (
              <>
      {attentionRules.length > 0 && (
        <Card
          title={`重点关注（${attentionRules.length}）`}
          style={{ marginBottom: 16 }}
          styles={{ header: { borderColor: "#ffccc7" } }}
        >
          <Table rowKey="code" size="small" columns={columns} dataSource={attentionRules} pagination={false} />
        </Card>
      )}

      <Card
        title="全部规则"
        styles={{ body: { paddingTop: 8 } }}
        extra={
          <Space size={8} wrap>
            <Input
              aria-label="规则搜索"
              allowClear
              placeholder="搜索名称 / 编码"
              style={{ width: 200 }}
              value={filters.search}
              onChange={(event) => updateFilters({ search: event.target.value })}
            />
            <Select
              aria-label="规则排序"
              style={{ width: 136 }}
              value={filters.sort}
              options={[
                { value: "default", label: "默认排序" },
                { value: "severity", label: "严重度优先" },
              ]}
              onChange={(value) => updateFilters({ sort: value as RuleSortMode })}
            />
          </Space>
        }
      >
        <Space size={6} wrap style={{ marginBottom: 12 }}>
          <Tag.CheckableTag
            checked={filters.category === null}
            onClick={() => updateFilters({ category: null })}
            style={{ padding: "4px 10px", border: "1px solid #d9d9d9" }}
          >
            全部
          </Tag.CheckableTag>
          {categoryCounts.map((category) => (
            <Tag.CheckableTag
              key={category.value}
              checked={filters.category === category.value}
              onClick={() => updateFilters({ category: category.value })}
              style={{ padding: "4px 10px", border: "1px solid #d9d9d9" }}
            >
              {CATEGORY_LABELS[category.value] ?? category.value} {category.count}
            </Tag.CheckableTag>
          ))}
        </Space>
        {sortedRules.length === 0 ? (
          <Empty
            description={
              statusFilter || filters.search.trim()
                ? "暂无匹配的规则结果"
                : "暂无规则结果"
            }
          />
        ) : (
          <Table
            rowKey="code"
            size="small"
            columns={columns}
            dataSource={sortedRules}
            pagination={false}
            rowClassName={(record) => (record.category === filters.category ? "rule-row-focus" : "")}
          />
        )}
      </Card>
              </>
            ),
          },
          {
            key: "logs",
            label: "执行日志",
            children: (
              <Card title="执行日志">
                {logEntries.length === 0 ? (
                  <EmptyState description="暂无日志" />
                ) : (
                  <List
                    size="small"
                    dataSource={logEntries}
                    renderItem={(entry) => (
                      <List.Item>
                        <div style={{ width: "100%" }}>
                          <Space>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {dayjs(entry.ts).format("HH:mm:ss.SSS")}
                            </Typography.Text>
                            <Tag color={entry.level === "error" ? "red" : entry.level === "warn" ? "gold" : "blue"}>
                              {entry.level}
                            </Tag>
                            {entry.rule_code && <Tag>{entry.rule_code}</Tag>}
                          </Space>
                          <div style={{ marginTop: 2 }}>{entry.message}</div>
                        </div>
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            ),
          },
          {
            key: "report",
            label: "报告预览",
            children: (
              <Card title="巡检报告" styles={{ body: { padding: 0 } }}>
                <iframe
                  src={reportUrl(taskId)}
                  title="巡检报告"
                  style={{ width: "100%", height: "calc(100vh - 280px)", border: 0 }}
                />
              </Card>
            ),
          },
        ]}
      />

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
          description="所选规则及其私有准备会重算，未选择规则结果保持不变。"
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
      <Modal
        title="修改设备 ID"
        open={deviceOpen}
        confirmLoading={deviceSaving}
        okText="保存"
        cancelText="取消"
        onOk={() => void saveDeviceId()}
        onCancel={() => setDeviceOpen(false)}
      >
        <Input
          value={deviceValue}
          maxLength={128}
          allowClear
          placeholder="输入设备 ID"
          onChange={(event) => setDeviceValue(event.target.value)}
        />
      </Modal>
    </div>
  );
}
