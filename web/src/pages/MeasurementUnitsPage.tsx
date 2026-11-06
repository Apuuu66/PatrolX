import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, App, Button, Card, Form, Input, Modal, Segmented, Select, Space, Switch, Tabs, Tag,
  Typography,
} from "antd";
import { Table } from "../components/ResizableTable";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import {
  api, type KpiLegacyRecoveryAuditV6, type KpiMeasurementBindingV6,
  type KpiMaintenanceOperationAcceptedV6, type KpiMaintenanceOperationV6,
  type KpiMeasurementUnitV6, type KpiPendingAttributionV6, type MeasurementBinding,
  type MeasurementResource, type MeasurementUnit, type TaskSummary,
} from "../api/http";
import { KpiMetricMaintenancePanel } from "../components/KpiMetricMaintenancePanel";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, LoadErrorState } from "../components/PageState";

const STATUS_COLORS: Record<string, string> = {
  candidate: "gold", confirmed: "green", conflict: "red", ignored: "default",
};

const STATUS_LABELS: Record<string, string> = {
  candidate: "候选", confirmed: "已确认", conflict: "冲突", ignored: "忽略",
};

const DISABLE_NOTICE = "只影响后续巡检，现有配置、团队关注和历史结果保留";

const CONFIGURATION_LABELS: Record<string, string> = {
  ready: "配置已完备",
  incomplete: "待配置",
};

const RECOVERY_LABELS: Record<string, { color: string; text: string }> = {
  pending: { color: "gold", text: "历史恢复待处理" },
  partial_failure: { color: "red", text: "历史恢复部分失败" },
  completed: { color: "green", text: "历史停用已恢复" },
};

const RECOVERY_RESULT_LABELS: Record<KpiLegacyRecoveryAuditV6["result"], { color: string; text: string }> = {
  pending: { color: "gold", text: "待恢复" },
  running: { color: "processing", text: "恢复中" },
  recovered: { color: "green", text: "恢复成功" },
  failed: { color: "red", text: "恢复失败" },
  skipped: { color: "default", text: "已跳过" },
};

const MAINTENANCE_OPERATION_LABELS: Record<KpiMaintenanceOperationV6["status"], { color: string; text: string }> = {
  queued: { color: "gold", text: "排队中" },
  running: { color: "processing", text: "处理中" },
  succeeded: { color: "green", text: "成功" },
  partial_success: { color: "orange", text: "部分成功" },
  failed: { color: "red", text: "失败" },
};

function createIdempotencyKey(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${suffix}`.slice(0, 128);
}

interface MeasurementUnitTabProps {
  networkElementType: string;
}

function MeasurementUnitTab({ networkElementType }: MeasurementUnitTabProps) {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<KpiMeasurementUnitV6[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [updatingUnitId, setUpdatingUnitId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.listKpiMeasurementUnitsV6({
        network_element_type: networkElementType,
        page: 1,
        page_size: 20,
        ...(search ? { search } : {}),
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      const text = err instanceof Error ? err.message : "测量单元加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      setLoading(false);
    }
  }, [message, networkElementType, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleInspection = async (unit: KpiMeasurementUnitV6) => {
    const nextEnabled = !unit.inspection_enabled;
    setUpdatingUnitId(unit.measurement_unit_id);
    try {
      const updated = await api.setKpiMeasurementInspectionEnabledV6(
        unit.network_element_type,
        unit.measurement_unit_id,
        { expected_revision: unit.revision, inspection_enabled: nextEnabled },
      );
      setItems((current) => current.map((item) => (
        item.measurement_unit_id === updated.measurement_unit_id ? updated : item
      )));
      message.success(nextEnabled ? "测量单元已启用，后续任务将纳入其指标" : "测量单元已停用");
    } catch (err) {
      const text = err instanceof Error ? err.message : "测量单元状态更新失败";
      message.error(text);
      await load();
    } finally {
      setUpdatingUnitId(null);
    }
  };

  const columns: ColumnsType<KpiMeasurementUnitV6> = [
    {
      title: "测量单元",
      key: "measurement_unit",
      width: 320,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.name_zh}</Typography.Text>
          <Typography.Text type="secondary">{record.name_en}</Typography.Text>
          <Typography.Text code>{record.measurement_unit_id}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "网元类型",
      dataIndex: "network_element_type",
      key: "network_element_type",
      width: 110,
      render: (value: string) => <Tag color={value === "CSP" ? "purple" : "blue"}>{value}</Tag>,
    },
    {
      title: "纳入指标",
      key: "metric_counts",
      width: 190,
      render: (_, record) => (
        <Space wrap size={4}>
          <Tag>{record.base_metric_count} 基础</Tag>
          <Tag>{record.derived_metric_count} 派生</Tag>
        </Space>
      ),
    },
    {
      title: "配置 / 恢复",
      key: "state",
      width: 210,
      render: (_, record) => {
        const recovery = RECOVERY_LABELS[record.recovery_state];
        return (
          <Space direction="vertical" size={4}>
            <Tag color={record.configuration_state === "ready" ? "green" : "gold"}>
              {CONFIGURATION_LABELS[record.configuration_state] ?? record.configuration_state}
            </Tag>
            {recovery ? <Tag color={recovery.color}>{recovery.text}</Tag> : null}
          </Space>
        );
      },
    },
    {
      title: "巡检范围",
      key: "inspection_scope",
      width: 250,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          {isAdmin ? (
            <Switch
              aria-label={`${record.inspection_enabled ? "停用" : "启用"} ${record.name_zh}`}
              checked={record.inspection_enabled}
              loading={updatingUnitId === record.measurement_unit_id}
              onChange={() => void toggleInspection(record)}
            />
          ) : null}
          <Typography.Text type={record.inspection_enabled ? "success" : "secondary"}>
            {record.inspection_enabled ? "已启用 · 后续任务" : "已停用 · 配置保留"}
          </Typography.Text>
          {!record.inspection_enabled ? (
            <Typography.Text type="secondary" className="measurement-scope-notice">
              {DISABLE_NOTICE}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
  ];

  const enabledCount = items.filter((item) => item.inspection_enabled).length;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="巡检启停只到测量单元，不再提供指标、绑定或派生级巡检开关；团队关注也不等于巡检范围。"
        description="测量单元归属一个网元类型；启用后纳入全部已确认基础指标和已定义派生指标。变更只影响后续任务。"
      />
      <Card>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Space wrap align="center" style={{ width: "100%", justifyContent: "space-between" }}>
            <Space wrap>
              <Typography.Title level={4} style={{ margin: 0 }}>测量单元列表</Typography.Title>
              <Tag color="blue">唯一启停粒度</Tag>
              <Typography.Text type="secondary">共 {total} 个 · {enabledCount} 个启用</Typography.Text>
            </Space>
          </Space>
          <Input.Search
            allowClear
            aria-label="搜索测量单元"
            placeholder="搜索测量单元名称或 ID"
            style={{ width: 320 }}
            onSearch={setSearch}
          />
          {loadError ? (
            <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />
          ) : (
            <Table
              rowKey={(record) => `${record.network_element_type}:${record.measurement_unit_id}`}
              loading={loading}
              columns={columns}
              dataSource={items}
              pagination={false}
              locale={{
                emptyText: (
                  <EmptyState
                    description={`${networkElementType} 下尚未纳入指标`}
                    action={<Button onClick={() => void load()}>刷新列表</Button>}
                  />
                ),
              }}
            />
          )}
        </Space>
      </Card>
    </Space>
  );
}

interface BindingCorrectionFormValues {
  status: "confirmed" | "ignored";
  reason: string;
}

function MeasurementBindingTab({ networkElementType }: { networkElementType: string }) {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<KpiMeasurementBindingV6[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<KpiMeasurementBindingV6["status"] | undefined>();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [correctionTarget, setCorrectionTarget] = useState<KpiMeasurementBindingV6 | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [correctionForm] = Form.useForm<BindingCorrectionFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.listKpiMeasurementBindingsV6({
        network_element_type: networkElementType,
        page,
        page_size: pageSize,
        ...(search ? { search } : {}),
        ...(status ? { status } : {}),
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      const text = err instanceof Error ? err.message : "绑定关系加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      setLoading(false);
    }
  }, [message, networkElementType, page, pageSize, search, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCorrection = (binding: KpiMeasurementBindingV6) => {
    setCorrectionTarget(binding);
    correctionForm.setFieldsValue({ status: "confirmed", reason: "" });
  };

  const submitCorrection = async (values: BindingCorrectionFormValues) => {
    if (!correctionTarget) return;
    setCorrecting(true);
    try {
      await api.correctKpiMeasurementBindingV6(
        correctionTarget.network_element_type,
        correctionTarget.id,
        {
          expected_revision: correctionTarget.revision,
          status: values.status,
          reason: values.reason.trim(),
        },
      );
      message.success(values.status === "confirmed" ? "绑定异常已确认为有效" : "绑定异常已忽略");
      setCorrectionTarget(null);
      correctionForm.resetFields();
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "绑定异常修正失败");
      await load();
    } finally {
      setCorrecting(false);
    }
  };

  const columns: ColumnsType<KpiMeasurementBindingV6> = [
    {
      title: "指标",
      key: "metric",
      width: 260,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong ellipsis={{ tooltip: record.metric_resource_name }}>
            {record.metric_resource_name || record.base_source_name}
          </Typography.Text>
          <Typography.Text code>{record.metric_resource_id || "未关联指标"}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "测量单元",
      key: "measurement_unit",
      width: 220,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text>{record.measurement_unit_name || record.measurement_unit_id}</Typography.Text>
          <Typography.Text type="secondary" code>{record.measurement_unit_id}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "源列映射",
      key: "source_mapping",
      width: 240,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text ellipsis={{ tooltip: record.raw_source_name }}>
            {record.raw_source_name}
          </Typography.Text>
          <Typography.Text type="secondary" ellipsis={{ tooltip: record.base_source_name }}>
            → {record.base_source_name}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "诊断",
      dataIndex: "diagnostic",
      key: "diagnostic",
      width: 220,
      render: (value: string | null) => value || "自动分类正常",
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (value: string) => <Tag color={STATUS_COLORS[value]}>{STATUS_LABELS[value]}</Tag>,
    },
    {
      title: "来源",
      key: "source",
      width: 240,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text ellipsis={{ tooltip: record.source_file }}>{record.source_file}</Typography.Text>
          <Typography.Text type="secondary" code>{record.origin_task_id}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 110,
      fixed: "right",
      render: (_, record) => isAdmin && ["candidate", "conflict"].includes(record.status) ? (
        <Button size="small" onClick={() => openCorrection(record)}>人工修正</Button>
      ) : <Typography.Text type="secondary">只读</Typography.Text>,
    },
  ];

  return (
    <Card title="绑定关系诊断">
      <Alert
        type="info"
        showIcon
        message="正常绑定由自动入库流程确认，本页只处理候选或冲突绑定。"
        description="每次人工修正必须填写原因并携带当前 revision；不提供批量确认，也不提供指标级巡检开关。"
        style={{ marginBottom: 16 }}
      />
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          allowClear
          aria-label="搜索绑定关系"
          placeholder="搜索指标、列名、测量单元或任务"
          style={{ width: 320 }}
          onSearch={(value) => {
            setSearch(value.trim());
            setPage(1);
          }}
        />
        <Select
          allowClear
          aria-label="筛选绑定状态"
          placeholder="全部状态"
          style={{ width: 160 }}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Typography.Text type="secondary">共 {total} 条</Typography.Text>
      </Space>
      {loadError ? (
        <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />
      ) : (
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          scroll={{ x: 1390 }}
          locale={{
            emptyText: (
              <EmptyState
                description={`${networkElementType} 下暂无绑定关系`}
                action={<Button onClick={() => void load()}>刷新列表</Button>}
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      )}

      <Modal
        open={correctionTarget !== null}
        title="单条修正绑定异常"
        okText="确认修正"
        confirmLoading={correcting}
        onCancel={() => setCorrectionTarget(null)}
        onOk={() => correctionForm.submit()}
      >
        <Form
          form={correctionForm}
          layout="vertical"
          onFinish={(values) => void submitCorrection(values)}
        >
          <Typography.Paragraph type="secondary">
            来源列：{correctionTarget?.raw_source_name}；当前 revision：{correctionTarget?.revision}。
            修正只影响当前绑定配置，不改变指标级巡检开关。
          </Typography.Paragraph>
          <Form.Item name="status" label="修正结果" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "confirmed", label: "确认绑定有效" },
                { value: "ignored", label: "忽略该异常绑定" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label="修正原因"
            rules={[{ required: true, whitespace: true, message: "请填写修正原因" }]}
          >
            <Input.TextArea rows={3} maxLength={512} showCount placeholder="例如：人工核对源列后确认归属" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

function RecoveryAttributionTab({ networkElementType }: { networkElementType: string }) {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [audits, setAudits] = useState<KpiLegacyRecoveryAuditV6[]>([]);
  const [pendingItems, setPendingItems] = useState<KpiPendingAttributionV6[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [pendingTarget, setPendingTarget] = useState<KpiPendingAttributionV6 | null>(null);
  const [operation, setOperation] = useState<KpiMaintenanceOperationV6 | null>(null);
  const pollSequence = useRef(0);
  const pollTimer = useRef<number | null>(null);
  const [pendingForm] = Form.useForm<{ network_element_type: string }>();

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [auditPage, pendingPage] = await Promise.all([
        api.listKpiLegacyRecoveryAuditsV6({
          network_element_type: networkElementType,
          page: 1,
          page_size: 20,
        }),
        api.listKpiPendingAttributionsV6({ page: 1, page_size: 20 }),
      ]);
      setAudits(auditPage.items);
      setPendingItems(pendingPage.items);
    } catch (err) {
      const text = err instanceof Error ? err.message : "恢复与归属记录加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      setLoading(false);
    }
  }, [message, networkElementType]);

  useEffect(() => {
    void load();
  }, [load]);

  const stopPolling = useCallback(() => {
    pollSequence.current += 1;
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const pollOperation = useCallback((accepted: KpiMaintenanceOperationAcceptedV6) => {
    stopPolling();
    const sequence = pollSequence.current;

    const poll = async () => {
      if (sequence !== pollSequence.current) return;
      try {
        const current = await api.getKpiMaintenanceOperationV6(accepted.operation_id);
        if (sequence !== pollSequence.current) return;
        setOperation(current);
        if (["succeeded", "partial_success", "failed"].includes(current.status)) {
          setRetrying(false);
          setResolving(false);
          await load();
          if (sequence !== pollSequence.current) return;
          if (current.status === "succeeded") {
            message.success(
              current.operation_type === "pending_attribution_resolve"
                ? "待归属配置已完成归属"
                : "历史恢复项已重试完成",
            );
          } else if (current.status === "partial_success") {
            message.warning("维护操作部分成功，请处理失败项");
          } else {
            message.error("维护操作执行失败");
          }
          return;
        }
        pollTimer.current = window.setTimeout(() => void poll(), 1000);
      } catch (err) {
        if (sequence !== pollSequence.current) return;
        setRetrying(false);
        setResolving(false);
        message.error(err instanceof Error ? err.message : "维护操作状态读取失败");
        await load();
      }
    };

    void poll();
  }, [load, message, stopPolling]);

  const retryableAudits = audits.filter((audit) => audit.result === "failed" || audit.result === "pending");

  const retryFailedAudits = async () => {
    if (retryableAudits.length === 0) return;
    setRetrying(true);
    setOperation(null);
    try {
      const accepted = await api.retryKpiLegacyRecoveryV6({
        audit_ids: retryableAudits.map((audit) => audit.audit_id),
        idempotency_key: createIdempotencyKey("legacy-recovery-retry"),
      });
      pollOperation(accepted);
    } catch (err) {
      setRetrying(false);
      message.error(err instanceof Error ? err.message : "历史恢复重试提交失败");
    }
  };

  const openPendingResolution = (pending: KpiPendingAttributionV6) => {
    setPendingTarget(pending);
    pendingForm.resetFields();
  };

  const submitPendingResolution = async (values: { network_element_type: string }) => {
    if (!pendingTarget) return;
    setResolving(true);
    setOperation(null);
    try {
      const accepted = await api.resolveKpiPendingAttributionV6(pendingTarget.pending_id, {
        network_element_type: values.network_element_type,
        idempotency_key: createIdempotencyKey("pending-attribution-resolve"),
      });
      setPendingTarget(null);
      pendingForm.resetFields();
      pollOperation(accepted);
    } catch (err) {
      setResolving(false);
      message.error(err instanceof Error ? err.message : "待归属配置提交失败");
    }
  };

  const auditColumns: ColumnsType<KpiLegacyRecoveryAuditV6> = [
    {
      title: "恢复对象",
      key: "object",
      width: 320,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.metric_resource_id || record.measurement_unit_id || record.source_record_id}</Typography.Text>
          <Typography.Text type="secondary">
            {record.network_element_type || "待归属"} · {record.object_kind} · {record.measurement_unit_id || "无测量单元"}
          </Typography.Text>
          <Typography.Text code>{record.source_table}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "恢复结果",
      dataIndex: "result",
      key: "result",
      width: 120,
      render: (value: KpiLegacyRecoveryAuditV6["result"]) => {
        const label = RECOVERY_RESULT_LABELS[value];
        return <Tag color={label.color}>{label.text}</Tag>;
      },
    },
    {
      title: "尝试",
      dataIndex: "attempt_count",
      key: "attempt_count",
      width: 80,
      render: (value: number) => `${value} 次`,
    },
    {
      title: "失败原因",
      key: "error",
      width: 260,
      render: (_, record) => record.error_message ? (
        <Space direction="vertical" size={2}>
          <Typography.Text type="danger">{record.error_message}</Typography.Text>
          {record.error_code ? <Typography.Text code>{record.error_code}</Typography.Text> : null}
        </Space>
      ) : <Typography.Text type="secondary">无</Typography.Text>,
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 190,
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
  ];

  const pendingColumns: ColumnsType<KpiPendingAttributionV6> = [
    {
      title: "待归属对象",
      key: "object",
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.source_key}</Typography.Text>
          <Typography.Text type="secondary">{record.source_table} / {record.source_record_id}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "候选网元类型",
      dataIndex: "candidate_network_element_types",
      key: "candidates",
      render: (values: string[]) => values.length > 0 ? values.join(" / ") : "需人工指定",
    },
    {
      title: "状态",
      dataIndex: "resolution_state",
      key: "resolution_state",
      render: (value: string) => <Tag color={value === "failed" ? "red" : value === "materialized" ? "green" : "gold"}>{value}</Tag>,
    },
    {
      title: "操作",
      key: "actions",
      width: 140,
      render: (_, record) => {
        if (!isAdmin || record.resolution_state === "materialized") {
          return <Typography.Text type="secondary">只读</Typography.Text>;
        }
        return (
          <Button size="small" onClick={() => openPendingResolution(record)}>
            指定网元类型
          </Button>
        );
      },
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="历史停用恢复按对象逐条审计，待归属项必须明确选择网元类型后才会进入巡检范围。"
        description="恢复操作只处理配置归属，不改写历史结果；成功项不会因同批失败回滚。"
      />
      {loadError ? (
        <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />
      ) : (
        <>
          {operation ? (
            <Card size="small" title="最近一次维护操作">
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color={MAINTENANCE_OPERATION_LABELS[operation.status].color}>
                    {MAINTENANCE_OPERATION_LABELS[operation.status].text}
                  </Tag>
                  <Typography.Text>成功 {operation.succeeded_count}</Typography.Text>
                  <Typography.Text type="danger">失败 {operation.failed_count}</Typography.Text>
                  <Typography.Text type="secondary">待处理 {operation.pending_count}</Typography.Text>
                </Space>
                {operation.items.some((item) => item.result === "failed") ? (
                  <Space direction="vertical" size={4}>
                    {operation.items.filter((item) => item.result === "failed").map((item) => (
                      <Typography.Text key={item.target_id} type="danger">
                        对象 {item.target_id}：{item.error_message || item.error_code || "处理失败"}
                      </Typography.Text>
                    ))}
                  </Space>
                ) : null}
              </Space>
            </Card>
          ) : null}
          <Card
            title={`历史恢复审计 · ${networkElementType}`}
            extra={isAdmin ? (
              <Button
                danger
                loading={retrying}
                disabled={loading || retryableAudits.length === 0}
                onClick={() => void retryFailedAudits()}
              >
                重试失败恢复项（{retryableAudits.length}）
              </Button>
            ) : (
              <Typography.Text type="secondary">只读</Typography.Text>
            )}
          >
            <Table
              rowKey="audit_id"
              loading={loading}
              columns={auditColumns}
              dataSource={audits}
              pagination={false}
              locale={{ emptyText: <EmptyState description="当前网元类型暂无历史恢复审计" /> }}
            />
          </Card>
          <Card title="待归属配置">
            <Table
              rowKey="pending_id"
              loading={loading}
              columns={pendingColumns}
              dataSource={pendingItems}
              pagination={false}
              locale={{ emptyText: <EmptyState description="暂无待归属配置" /> }}
            />
          </Card>
          <Modal
            open={pendingTarget !== null}
            title="指定待归属配置"
            okText="确认归属"
            confirmLoading={resolving}
            onCancel={() => {
              setPendingTarget(null);
              pendingForm.resetFields();
            }}
            onOk={() => pendingForm.submit()}
          >
            <Form
              form={pendingForm}
              layout="vertical"
              onFinish={(values) => void submitPendingResolution(values)}
            >
              <Typography.Paragraph type="secondary">
                待归属对象：{pendingTarget?.source_key}。必须人工明确选择 UMF 或 CSP，系统不会根据候选默认猜测。
              </Typography.Paragraph>
              <Form.Item
                name="network_element_type"
                label="网元类型"
                rules={[{ required: true, message: "请选择网元类型" }]}
              >
                <Select
                  aria-label="选择网元类型"
                  placeholder="请选择 UMF 或 CSP"
                  options={[
                    { value: "UMF", label: "UMF" },
                    { value: "CSP", label: "CSP" },
                  ]}
                />
              </Form.Item>
            </Form>
          </Modal>
        </>
      )}
    </Space>
  );
}

interface DerivedFormValues {
  measurement_unit_id: string;
  metric_resource_id: string;
  numerator_metric_id: string;
  denominator_metric_id: string;
  template: "success_rate" | "reverse_success_rate";
}

const DERIVED_TEMPLATE_OPTIONS = [
  { value: "success_rate", label: "成功率" },
  { value: "reverse_success_rate", label: "反向成功率" },
];

function MeasurementDerivedTab() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [form] = Form.useForm<DerivedFormValues>();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedUnitId, setSelectedUnitId] = useState<string>();
  const [unitOptions, setUnitOptions] = useState<MeasurementUnit[]>([]);
  const [metricOptions, setMetricOptions] = useState<MeasurementResource[]>([]);
  const [bindingOptions, setBindingOptions] = useState<MeasurementBinding[]>([]);
  const [unitLoading, setUnitLoading] = useState(false);
  const [metricLoading, setMetricLoading] = useState(false);
  const [bindingLoading, setBindingLoading] = useState(false);

  const loadUnitOptions = useCallback(async (search: string) => {
    setUnitLoading(true);
    try {
      const data = await api.listMeasurementUnits({ search: search || undefined });
      setUnitOptions(data.items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "测量单元加载失败");
    } finally {
      setUnitLoading(false);
    }
  }, [message]);

  const loadMetricOptions = useCallback(async (search: string) => {
    setMetricLoading(true);
    try {
      const data = await api.listMeasurementResources({ kind: "me", search: search || undefined, page_size: 100 });
      setMetricOptions(data.items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "指标加载失败");
    } finally {
      setMetricLoading(false);
    }
  }, [message]);

  const loadBindingOptions = useCallback(async (unitId: string, search: string) => {
    if (!unitId) {
      setBindingOptions([]);
      return;
    }
    setBindingLoading(true);
    try {
      const data = await api.listMeasurementBindings({
        measurement_unit_id: unitId,
        status: "confirmed",
        search: search || undefined,
      });
      setBindingOptions(data.items.filter((item) => item.metric_resource_id));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "确认绑定加载失败");
    } finally {
      setBindingLoading(false);
    }
  }, [message]);

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    setSelectedUnitId(undefined);
    void Promise.all([loadUnitOptions(""), loadMetricOptions(""), loadBindingOptions("", "")]);
  }, [open, form, loadUnitOptions, loadMetricOptions, loadBindingOptions]);

  const create = async (values: DerivedFormValues) => {
    setSubmitting(true);
    try {
      await api.createMeasurementDerived(values);
      message.success("派生指标已创建");
      setOpen(false);
      form.resetFields();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "创建派生指标失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card title="派生指标">
      <Alert
        type="info"
        showIcon
        message="支持成功率和反向成功率模板"
        description="反向成功率等于 100 减去正向成功率；分母均值为 0 时展示为疑似业务未触发，默认不按业务阈值判定。"
        style={{ marginBottom: 16 }}
      />
      {isAdmin ? (
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建派生指标</Button>
      ) : null}
      <Modal open={open} title="派生指标" confirmLoading={submitting} okText="创建" onCancel={() => setOpen(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" initialValues={{ template: "success_rate" }} onFinish={(values) => void create(values)}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <Form.Item name="template" label="模板" rules={[{ required: true }]}>
              <Select options={DERIVED_TEMPLATE_OPTIONS} />
            </Form.Item>
            <Form.Item name="measurement_unit_id" label="测量单元" rules={[{ required: true }]}>
              <Select
                allowClear
                showSearch
                filterOption={false}
                loading={unitLoading}
                placeholder="搜索并选择测量单元"
                onSearch={(value) => void loadUnitOptions(value)}
                onChange={(value) => {
                  const unitId = value || "";
                  setSelectedUnitId(unitId || undefined);
                  form.setFieldsValue({ numerator_metric_id: undefined, denominator_metric_id: undefined });
                  void loadBindingOptions(unitId, "");
                }}
                options={unitOptions.map((item) => ({
                  value: item.resource_id,
                  label: `${item.name_zh} / ${item.resource_id}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="metric_resource_id" label="派生指标" rules={[{ required: true }]}>
              <Select
                allowClear
                showSearch
                filterOption={false}
                loading={metricLoading}
                placeholder="搜索并选择 ME 指标"
                onSearch={(value) => void loadMetricOptions(value)}
                options={metricOptions.map((item) => ({
                  value: item.resource_id,
                  label: `${item.name_zh} / ${item.resource_id}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="numerator_metric_id" label="分子指标" rules={[{ required: true }]}>
              <Select
                allowClear
                showSearch
                disabled={!selectedUnitId}
                filterOption={false}
                loading={bindingLoading}
                placeholder={selectedUnitId ? "搜索已确认绑定指标" : "请先选择测量单元"}
                onSearch={(value) => void loadBindingOptions(selectedUnitId || "", value)}
                options={bindingOptions.map((item) => ({
                  value: item.metric_resource_id,
                  label: `${item.metric_resource_name_zh || item.base_source_name} / ${item.metric_resource_id}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="denominator_metric_id" label="分母指标" rules={[{ required: true }]}>
              <Select
                allowClear
                showSearch
                disabled={!selectedUnitId}
                filterOption={false}
                loading={bindingLoading}
                placeholder={selectedUnitId ? "搜索已确认绑定指标" : "请先选择测量单元"}
                onSearch={(value) => void loadBindingOptions(selectedUnitId || "", value)}
                options={bindingOptions.map((item) => ({
                  value: item.metric_resource_id,
                  label: `${item.metric_resource_name_zh || item.base_source_name} / ${item.metric_resource_id}`,
                }))}
              />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </Card>
  );
}

export function MeasurementUnitsPage() {
  const navigate = useNavigate();
  const [networkElementType, setNetworkElementType] = useState("UMF");
  const [completedTasks, setCompletedTasks] = useState<TaskSummary[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void api
      .listTasks({ status: "completed", page_size: 20 })
      .then((data) => {
        if (active) setCompletedTasks(data.items);
      })
      .catch(() => {
        if (active) setCompletedTasks([]);
      })
      .finally(() => {
        if (active) setTasksLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div>
      <PageHeader
        title="测量单元巡检范围"
        description="按测量单元控制巡检范围；团队关注与全部指标在 KPI 结果工作台查看"
        actions={
          <Space wrap>
            <Segmented
              aria-label="网元类型"
              value={networkElementType}
              options={["UMF", "CSP"]}
              onChange={(value) => setNetworkElementType(String(value))}
            />
            <Select
              aria-label="查看团队关注"
              loading={tasksLoading}
              disabled={tasksLoading || completedTasks.length === 0}
              placeholder={tasksLoading ? "加载已完成任务" : "暂无已完成任务"}
              style={{ width: 260 }}
              options={completedTasks.map((task) => ({
                value: task.task_id,
                label: `${task.name} · ${task.task_id}`,
              }))}
              onChange={(taskId: string) => navigate(`/tasks/${encodeURIComponent(taskId)}/kpi`)}
            />
          </Space>
        }
      />
      <Tabs defaultActiveKey="units" items={[
        {
          key: "units",
          label: "测量单元",
          children: <MeasurementUnitTab key={networkElementType} networkElementType={networkElementType} />,
        },
        {
          key: "bindings",
          label: "绑定关系",
          children: <MeasurementBindingTab networkElementType={networkElementType} />,
        },
        {
          key: "recovery",
          label: "恢复与归属",
          children: <RecoveryAttributionTab networkElementType={networkElementType} />,
        },
        { key: "derived", label: "派生指标", children: <MeasurementDerivedTab /> },
        { key: "maintenance", label: "维护配置", children: <KpiMetricMaintenancePanel /> },
      ]} />
    </div>
  );
}
