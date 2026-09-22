import { useCallback, useEffect, useState, type Key } from "react";
import {
  Alert, App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Typography, Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { api, type MeasurementBinding, type MeasurementBindingBatchConfirmResponse, type MeasurementResource, type MeasurementUnit, type MeasurementUnitImportResult } from "../api/http";
import { ResourceNameCell } from "../components/ResourceNameCell";
import { useAuth } from "../auth/AuthContext";

const STATUS_COLORS: Record<string, string> = {
  candidate: "gold", confirmed: "green", conflict: "red", ignored: "default",
};

const STATUS_LABELS: Record<string, string> = {
  candidate: "候选", confirmed: "已确认", conflict: "冲突", ignored: "忽略",
};

const IMPORT_ERROR_LABELS: Record<string, string> = {
  invalid_resource: "资源行缺少必填字段",
  resource_id_conflict: "同一个资源 ID 对应不同中文名",
  metric_owner_conflict: "指标已归属其他测量单元",
  invalid_display_order: "显示顺序必须是整数",
  invalid_direction: "指标方向非法",
  invalid_importance: "重要级别非法",
  invalid_warning_threshold: "预警阈值必须是数字",
  invalid_critical_threshold: "失败阈值必须是数字",
  threshold_direction_conflict: "预警/失败阈值与指标方向矛盾",
};

const DIRECTION_OPTIONS = [
  { value: "higher_better", label: "越高越好" },
  { value: "lower_better", label: "越低越好" },
  { value: "neutral", label: "不判定" },
];

const IMPORTANCE_OPTIONS = [
  { value: "P0", label: "P0" },
  { value: "P1", label: "P1" },
  { value: "P2", label: "P2" },
  { value: "normal", label: "普通" },
];

const DIRECTION_LABELS: Record<string, string> = {
  higher_better: "越高越好",
  lower_better: "越低越好",
  neutral: "不判定",
};

const IMPORTANCE_COLORS: Record<string, string> = { P0: "red", P1: "orange", P2: "gold", normal: "blue" };

const BATCH_CONFIRM_ERROR_LABELS: Record<string, string> = {
  kpi_binding_not_found: "绑定不存在",
  kpi_binding_metric_missing: "缺少 ME 指标",
  kpi_binding_status_not_confirmable: "当前状态不允许批量确认",
  kpi_binding_conflict: "指标已绑定到其他测量单元",
};

const IMPORT_SKIP_LABELS: Record<string, string> = {
  unsupported_resource_prefix: "资源 ID 前缀不属于导入范围",
  unchanged: "资源已存在且无变化",
};

function MeasurementUnitTab() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<MeasurementUnit[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<MeasurementUnitImportResult | null>(null);

  const load = useCallback(
    async (nextPage = page, nextPageSize = pageSize, nextSearch = search) => {
      setLoading(true);
      try {
        const data = await api.listMeasurementUnits({ page: nextPage, page_size: nextPageSize, search: nextSearch || undefined });
        setItems(data.items);
        setTotal(data.total);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "测量单元加载失败");
      } finally {
        setLoading(false);
      }
    },
    [message, page, pageSize, search],
  );

  useEffect(() => { void load(); }, [load]);

  const importFile = async (file: File) => {
    setImporting(true);
    try {
      const result = await api.importMeasurementUnits(file);
      const added = Object.values(result.added ?? {}).reduce((sum, value) => sum + value, 0);
      const updated = Object.values(result.updated ?? {}).reduce((sum, value) => sum + value, 0);
      const errorCount = (result.errors ?? []).length;
      const skippedCount = (result.skipped ?? []).length;
      const summary = `导入完成：新增 ${added}，更新 ${updated}，错误 ${errorCount}，跳过 ${skippedCount}`;
      if (errorCount > 0 || skippedCount > 0) {
        setImportResult(result);
        message.warning(summary);
      } else {
        message.success(summary);
      }
      setPage(1);
      await load(1, pageSize, search);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const toggleEnabled = async (record: MeasurementUnit) => {
    try {
      await api.setMeasurementUnitEnabled(record.resource_id, !record.enabled);
      message.success(record.enabled ? "已停用" : "已启用");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新失败");
    }
  };

  const columns: ColumnsType<MeasurementUnit> = [
    {
      title: "测量单元", dataIndex: "name_zh", key: "name_zh",
      render: (_, record) => (<div><div>{record.name_zh}</div><Typography.Text type="secondary">{record.name_en}</Typography.Text></div>),
    },
    { title: "资源 ID", dataIndex: "resource_id", key: "resource_id", width: 180 },
    { title: "文件片段", dataIndex: "filename_fragment", key: "filename_fragment", width: 220 },
    {
      title: "绑定", key: "bindings", width: 170,
      render: (_, record) => (<Space><Tag color="green">确认 {record.confirmed_binding_count}</Tag><Tag color="gold">候选 {record.candidate_binding_count}</Tag></Space>),
    },
    { title: "目录资源", key: "resources", width: 150, render: (_, record) => `ME ${record.metric_count} / UNIT ${record.unit_count}` },
    { title: "派生指标", dataIndex: "derived_count", key: "derived_count", width: 100 },
    { title: "状态", dataIndex: "enabled", key: "enabled", width: 110, render: (enabled: boolean) => (enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
    {
      title: "操作", key: "actions", width: 110,
      render: (_, record) => isAdmin ? <Button size="small" onClick={() => void toggleEnabled(record)}>{record.enabled ? "停用" : "启用"}</Button> : null,
    },
  ];

  const importErrorColumns: ColumnsType<NonNullable<MeasurementUnitImportResult["errors"]>[number]> = [
    { title: "CSV 行号", dataIndex: "line_number", key: "line_number", width: 100 },
    {
      title: "资源 ID", dataIndex: "resource_id", key: "resource_id", width: 220,
      render: (value: unknown) => (typeof value === "string" && value ? value : "-"),
    },
    {
      title: "错误原因", dataIndex: "reason", key: "reason", width: 200,
      render: (value: unknown) => IMPORT_ERROR_LABELS[String(value)] ?? String(value ?? "-"),
    },
    {
      title: "说明", key: "description",
      render: (_, record) => {
        if (record.reason === "resource_id_conflict") {
          return `资源 ID 已对应「${String(record.existing_name_zh ?? "-")}」，当前行中文名是「${String(record.name_zh ?? "-")}」`;
        }
        return "该行未导入";
      },
    },
  ];

  const importSkippedColumns: ColumnsType<NonNullable<MeasurementUnitImportResult["skipped"]>[number]> = [
    { title: "CSV 行号", dataIndex: "line_number", key: "line_number", width: 100 },
    {
      title: "资源 ID", dataIndex: "resource_id", key: "resource_id", width: 220,
      render: (value: unknown) => (typeof value === "string" && value ? value : "-"),
    },
    {
      title: "处理方式", dataIndex: "reason", key: "reason", width: 220,
      render: (value: unknown) => IMPORT_SKIP_LABELS[String(value)] ?? String(value ?? "-"),
    },
    {
      title: "说明", key: "description",
      render: (_, record) => {
        if (record.reason === "unsupported_resource_prefix") {
          return "仅导入 MU_*、ME_*、UNIT_* 三类资源";
        }
        if (record.reason === "unchanged") {
          return "中英文名称均未变化";
        }
        return "-";
      },
    },
  ];

  return (
    <Card title="测量单元目录" extra={isAdmin ? (
      <Upload accept=".csv" showUploadList={false} customRequest={({ file }) => void importFile(file as File)}>
        <Button icon={<UploadOutlined />} loading={importing}>导入资源 CSV</Button>
      </Upload>
    ) : null}>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search allowClear placeholder="搜索中英文描述" style={{ width: 280 }} onSearch={(value) => { setSearch(value); setPage(1); void load(1, pageSize, value); }} />
        <Typography.Text type="secondary">共 {total} 个测量单元</Typography.Text>
      </Space>
      <Table rowKey="resource_id" loading={loading} columns={columns} dataSource={items}
        pagination={{ current: page, pageSize, total, showSizeChanger: true, onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize); void load(nextPage, nextPageSize); } }} />
      <Modal
        open={importResult !== null}
        title="资源导入结果明细"
        footer={<Button type="primary" onClick={() => setImportResult(null)}>关闭</Button>}
        onCancel={() => setImportResult(null)}
        width={860}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          {(importResult?.errors ?? []).length > 0 && (
            <>
              <Typography.Text strong>错误明细</Typography.Text>
              <Table
                rowKey={(record) => `${record.line_number ?? "unknown"}-${String(record.resource_id ?? "")}`}
                size="small"
                columns={importErrorColumns}
                dataSource={importResult?.errors ?? []}
                pagination={{ pageSize: 10, showSizeChanger: false }}
              />
            </>
          )}
          {(importResult?.skipped ?? []).length > 0 && (
            <>
              <Typography.Text strong>跳过明细</Typography.Text>
              <Table
                rowKey={(record) => `${record.line_number ?? "unknown"}-${String(record.resource_id ?? "")}`}
                size="small"
                columns={importSkippedColumns}
                dataSource={importResult?.skipped ?? []}
                pagination={{ pageSize: 10, showSizeChanger: false }}
              />
            </>
          )}
        </Space>
      </Modal>
    </Card>
  );
}

interface RegisterFormValues {
  name_zh?: string;
  name_en?: string;
  bind_existing_resource_id?: string;
}

interface MetricEditFormValues {
  name_zh: string;
  name_en?: string;
  enabled: boolean;
  display_order?: number;
  metric_group?: string;
  direction?: "higher_better" | "lower_better" | "neutral";
  importance?: "P0" | "P1" | "P2" | "normal";
  warning_threshold?: number | null;
  critical_threshold?: number | null;
}

function MeasurementBindingTab() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<MeasurementBinding[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [unitSearch, setUnitSearch] = useState("");
  const [status, setStatus] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [selectedBindingIds, setSelectedBindingIds] = useState<Key[]>([]);
  const [batchConfirming, setBatchConfirming] = useState(false);
  const [batchResult, setBatchResult] = useState<MeasurementBindingBatchConfirmResponse | null>(null);
  const [registerForm] = Form.useForm<RegisterFormValues>();
  const [registerTarget, setRegisterTarget] = useState<MeasurementBinding | null>(null);
  const [registerSubmitting, setRegisterSubmitting] = useState(false);
  const [resourceSearch, setResourceSearch] = useState("");
  const [resources, setResources] = useState<MeasurementResource[]>([]);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceMap, setResourceMap] = useState<Record<string, MeasurementResource>>({});
  const [editForm] = Form.useForm<MetricEditFormValues>();
  const [editingMetric, setEditingMetric] = useState<MeasurementResource | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);

  const loadResourceGovernance = useCallback(async (bindings: MeasurementBinding[]) => {
    const boundIds = [...new Set(bindings.flatMap((item) => item.metric_resource_id ? [item.metric_resource_id] : []))];
    if (boundIds.length === 0) {
      setResourceMap({});
      return;
    }

    const nextResourceMap: Record<string, MeasurementResource> = {};
    let currentPage = 1;
    let resourceTotal = 0;
    do {
      const data = await api.listMeasurementResources({ kind: "me", page: currentPage, page_size: 200 });
      resourceTotal = data.total;
      for (const resource of data.items) {
        if (boundIds.includes(resource.resource_id)) nextResourceMap[resource.resource_id] = resource;
      }
      currentPage += 1;
    } while (Object.keys(nextResourceMap).length < boundIds.length && (currentPage - 1) * 200 < resourceTotal);
    setResourceMap(nextResourceMap);
  }, []);

  const load = useCallback(
    async (nextPage = page, nextPageSize = pageSize) => {
      setLoading(true);
      try {
        const data = await api.listMeasurementBindings({
          page: nextPage,
          page_size: nextPageSize,
          search: unitSearch || undefined,
          status,
        });
        setItems(data.items);
        setTotal(data.total);
        await loadResourceGovernance(data.items);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "绑定关系加载失败");
      } finally {
        setLoading(false);
      }
    },
    [loadResourceGovernance, message, page, pageSize, status, unitSearch],
  );

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!registerTarget) return;
    const loadResources = async () => {
      setResourceLoading(true);
      try {
        const data = await api.listMeasurementResources({
          kind: "me",
          search: resourceSearch || undefined,
          page_size: 50,
        });
        setResources(data.items);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "已有指标加载失败");
      } finally {
        setResourceLoading(false);
      }
    };
    void loadResources();
  }, [message, registerTarget, resourceSearch]);

  const openRegister = (record: MeasurementBinding) => {
    setResourceSearch("");
    setResources([]);
    registerForm.setFieldsValue({
      name_zh: record.base_source_name,
      name_en: undefined,
      bind_existing_resource_id: undefined,
    });
    setRegisterTarget(record);
  };

  const submitRegister = async (values: RegisterFormValues) => {
    if (!registerTarget) return;
    setRegisterSubmitting(true);
    try {
      const payload = values.bind_existing_resource_id
        ? { bind_existing_resource_id: values.bind_existing_resource_id }
        : { name_zh: values.name_zh, name_en: values.name_en || null };
      await api.registerMeasurementMetric(registerTarget.id, payload);
      message.success("指标已注册");
      setRegisterTarget(null);
      registerForm.resetFields();
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "注册指标失败");
    } finally {
      setRegisterSubmitting(false);
    }
  };

  const openEdit = async (record: MeasurementBinding) => {
    if (!record.metric_resource_id) return;
    const cachedMetric = resourceMap[record.metric_resource_id];
    if (cachedMetric) {
      setEditingMetric(cachedMetric);
      editForm.setFieldsValue({
        name_zh: cachedMetric.name_zh,
        name_en: cachedMetric.name_en || undefined,
        enabled: cachedMetric.enabled,
        display_order: cachedMetric.display_order ?? undefined,
        metric_group: cachedMetric.metric_group || "未分组",
        direction: cachedMetric.direction || "neutral",
        importance: cachedMetric.importance || "normal",
        warning_threshold: cachedMetric.warning_threshold,
        critical_threshold: cachedMetric.critical_threshold,
      });
      return;
    }

    try {
      const listed = await api.listMeasurementResources({
        kind: "me",
        search: record.metric_resource_id,
        page_size: 50,
      });
      const metric = listed.items.find((item) => item.resource_id === record.metric_resource_id);
      if (!metric) {
        message.error("未找到待编辑指标");
        return;
      }
      setEditingMetric(metric);
      editForm.setFieldsValue({
        name_zh: metric.name_zh,
        name_en: metric.name_en || undefined,
        enabled: metric.enabled,
        display_order: metric.display_order ?? undefined,
        metric_group: metric.metric_group || "未分组",
        direction: metric.direction || "neutral",
        importance: metric.importance || "normal",
        warning_threshold: metric.warning_threshold,
        critical_threshold: metric.critical_threshold,
      });
    } catch (err) {
      message.error(err instanceof Error ? err.message : "待编辑指标加载失败");
    }
  };

  const submitEdit = async (values: MetricEditFormValues) => {
    if (!editingMetric) return;
    setEditSubmitting(true);
    try {
      const updated = await api.updateMeasurementResource(editingMetric.resource_id, values);
      message.success("指标已更新");
      setEditingMetric(null);
      editForm.resetFields();
      await load();
      setResourceMap((current) => ({ ...current, [updated.resource_id]: updated }));
      return updated;
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新指标失败");
    } finally {
      setEditSubmitting(false);
    }
  };

  const batchConfirm = async () => {
    if (selectedBindingIds.length === 0) return;
    setBatchConfirming(true);
    try {
      const result = await api.batchConfirmMeasurementBindings(selectedBindingIds.map(Number));
      setBatchResult(result);
      if (result.failed > 0) {
        message.warning(`批量确认完成：成功 ${result.succeeded} 条，失败 ${result.failed} 条`);
      } else {
        message.success(`批量确认完成：成功 ${result.succeeded} 条`);
      }
      setSelectedBindingIds([]);
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "批量确认失败");
    } finally {
      setBatchConfirming(false);
    }
  };

  const updateBinding = async (binding: MeasurementBinding, nextStatus: "confirmed" | "ignored") => {
    try {
      await api.setMeasurementBindingStatus(
        binding.id,
        nextStatus,
        nextStatus === "confirmed" ? true : binding.enabled,
      );
      message.success(nextStatus === "confirmed" ? "已确认绑定" : "已忽略绑定");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新失败");
    }
  };

  const columns: ColumnsType<MeasurementBinding> = [
    {
      title: "指标", dataIndex: "metric_resource_id", key: "metric_resource_id",
      render: (value: string | null, record) => value ? (
        <Space>
          <ResourceNameCell name={record.metric_resource_name_zh} id={value} />
          {record.metric_is_manual ? <Tag color="blue">人工注册</Tag> : null}
        </Space>
      ) : "-",
    },
    { title: "CSV 列名", dataIndex: "raw_source_name", key: "raw_source_name" },
    { title: "基础列名", dataIndex: "base_source_name", key: "base_source_name" },
    {
      title: "测量单元", dataIndex: "measurement_unit_id", key: "measurement_unit_id",
      render: (_, record) => <ResourceNameCell name={record.measurement_unit_name_zh} id={record.measurement_unit_id} />,
    },
    { title: "任务", dataIndex: "task_id", key: "task_id" },
    { title: "来源文件", dataIndex: "source_file", key: "source_file" },
    {
      title: "分组", key: "metric_group", width: 120,
      render: (_, record) => {
        if (!record.metric_resource_id) return "-";
        return resourceMap[record.metric_resource_id]?.metric_group || "未分组";
      },
    },
    {
      title: "方向", key: "direction", width: 110,
      render: (_, record) => {
        if (!record.metric_resource_id) return "-";
        const direction = resourceMap[record.metric_resource_id]?.direction;
        return direction ? DIRECTION_LABELS[direction] : "未配置";
      },
    },
    {
      title: "重点", key: "importance", width: 90,
      render: (_, record) => {
        if (!record.metric_resource_id) return "-";
        const importance = resourceMap[record.metric_resource_id]?.importance || "normal";
        return <Tag color={IMPORTANCE_COLORS[importance]}>{importance}</Tag>;
      },
    },
    {
      title: "状态", dataIndex: "status", key: "status", width: 110,
      render: (value: string) => <Tag color={STATUS_COLORS[value]}>{STATUS_LABELS[value]}</Tag>,
    },
    {
      title: "操作", key: "actions", width: 280,
      render: (_, record) => isAdmin && record.status !== "conflict" ? (
        <Space>
          {!record.metric_resource_id && record.status === "candidate" ? (
            <Button size="small" type="primary" onClick={() => openRegister(record)}>注册指标</Button>
          ) : null}
          {record.metric_resource_id ? (
            <Button size="small" onClick={() => void openEdit(record)}>调整指标</Button>
          ) : null}
          <Button size="small" disabled={record.status === "confirmed"} onClick={() => void updateBinding(record, "confirmed")}>确认</Button>
          <Button size="small" disabled={record.status === "ignored"} onClick={() => void updateBinding(record, "ignored")}>忽略</Button>
        </Space>
      ) : null,
    },
  ];

  const rowSelection = {
    selectedRowKeys: selectedBindingIds,
    onChange: setSelectedBindingIds,
    getCheckboxProps: (record: MeasurementBinding) => ({
      disabled: !isAdmin || record.status !== "candidate" || !record.metric_resource_id,
    }),
  };

  return (
    <Card title="指标绑定关系">
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search allowClear placeholder="搜索指标 ID / 列名 / 测量单元" style={{ width: 280 }} onSearch={(value) => { setUnitSearch(value); setPage(1); setSelectedBindingIds([]); void load(1, pageSize); }} />
        <Select allowClear placeholder="绑定状态" style={{ width: 160 }} value={status} onChange={(value) => { setStatus(value); setPage(1); setSelectedBindingIds([]); void load(1, pageSize); }} options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))} />
        <Typography.Text type="secondary">共 {total} 条</Typography.Text>
        {isAdmin ? (
          <Button type="primary" disabled={selectedBindingIds.length === 0} loading={batchConfirming} onClick={() => void batchConfirm()}>
            批量确认
          </Button>
        ) : null}
      </Space>
      {batchResult && batchResult.failed > 0 ? (
        <Alert
          type="warning"
          showIcon
          closable
          style={{ marginBottom: 16 }}
          message={`批量确认：成功 ${batchResult.succeeded} 条，失败 ${batchResult.failed} 条`}
          description={batchResult.items.filter((item) => item.outcome === "failed").map((item) => (
            <div key={item.binding_id}>
              {item.binding_id}: {BATCH_CONFIRM_ERROR_LABELS[item.error_code ?? ""] ?? item.message ?? "确认失败"}
            </div>
          ))}
          onClose={() => setBatchResult(null)}
        />
      ) : null}
      <Table rowKey="id" loading={loading} columns={columns} dataSource={items} rowSelection={isAdmin ? rowSelection : undefined}
        pagination={{ current: page, pageSize, total, showSizeChanger: true, onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize); setSelectedBindingIds([]); void load(nextPage, nextPageSize); } }} />

      <Modal
        open={registerTarget !== null}
        title="注册未注册指标"
        confirmLoading={registerSubmitting}
        okText="注册"
        onCancel={() => setRegisterTarget(null)}
        onOk={() => registerForm.submit()}
      >
        <Form form={registerForm} layout="vertical" onFinish={(values) => void submitRegister(values)}>
          <Typography.Paragraph type="secondary">
            展示单位：{registerTarget?.display_unit || "无"}；常规表头列会自动入库，这里仅用于异常修正。
          </Typography.Paragraph>
          <Form.Item name="bind_existing_resource_id" label="绑定已有指标（可选）">
            <Select
              allowClear
              showSearch
              placeholder="搜索并选择已有 ME 指标"
              filterOption={false}
              loading={resourceLoading}
              onSearch={setResourceSearch}
              options={resources.map((item) => ({
                value: item.resource_id,
                label: `${item.name_zh} / ${item.resource_id}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="name_zh"
            label="中文名"
            rules={[{ required: true, message: "未选择已有指标时中文名必填" }]}
          >
            <Input maxLength={256} />
          </Form.Item>
          <Form.Item name="name_en" label="英文名（可选）">
            <Input maxLength={256} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={editingMetric !== null}
        title={editingMetric ? `${editingMetric.name_zh} / ${editingMetric.resource_id}` : "编辑指标"}
        confirmLoading={editSubmitting}
        okText="保存"
        onCancel={() => setEditingMetric(null)}
        onOk={() => editForm.submit()}
      >
        <Form form={editForm} layout="vertical" onFinish={(values) => void submitEdit(values)}>
          <Form.Item name="name_zh" label="中文名" rules={[{ required: true, message: "中文名必填" }]}>
            <Input maxLength={256} />
          </Form.Item>
          <Form.Item name="name_en" label="英文名">
            <Input maxLength={256} />
          </Form.Item>
          <Form.Item name="enabled" label="启用状态">
            <Select options={[{ value: true, label: "启用" }, { value: false, label: "停用" }]} />
          </Form.Item>
          <Form.Item name="display_order" label="显示顺序">
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="metric_group" label="指标分组">
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="direction" label="方向">
            <Select options={DIRECTION_OPTIONS} />
          </Form.Item>
          <Form.Item name="importance" label="重要级别">
            <Select options={IMPORTANCE_OPTIONS} />
          </Form.Item>
          <Form.Item name="warning_threshold" label="预警阈值">
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="critical_threshold" label="失败阈值">
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
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
      setBindingOptions(data.items.filter((item) => item.enabled && item.metric_resource_id));
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
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建派生指标</Button>
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
  return (
    <div>
      <Typography.Title level={3}>基础指标</Typography.Title>
      <Typography.Paragraph type="secondary">基于测量单元维护资源目录、指标绑定和派生指标。</Typography.Paragraph>
      <Tabs defaultActiveKey="units" items={[
        { key: "units", label: "测量单元", children: <MeasurementUnitTab /> },
        { key: "bindings", label: "绑定关系", children: <MeasurementBindingTab /> },
        { key: "derived", label: "派生指标", children: <MeasurementDerivedTab /> },
      ]} />
    </div>
  );
}
