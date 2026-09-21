import { useCallback, useEffect, useState } from "react";
import {
  Alert, App, Button, Card, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography, Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { api, type MeasurementBinding, type MeasurementUnit } from "../api/http";
import { useAuth } from "../auth/AuthContext";

const STATUS_COLORS: Record<string, string> = {
  candidate: "gold", confirmed: "green", conflict: "red", ignored: "default",
};

const STATUS_LABELS: Record<string, string> = {
  candidate: "候选", confirmed: "已确认", conflict: "冲突", ignored: "忽略",
};

function MeasurementUnitTab() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<MeasurementUnit[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);

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
      message.success(`导入完成：新增 ${added}，更新 ${updated}，错误 ${(result.errors ?? []).length}`);
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
    </Card>
  );
}

function MeasurementBindingTab() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<MeasurementBinding[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [unitSearch, setUnitSearch] = useState("");
  const [status, setStatus] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (nextPage = page, nextPageSize = pageSize) => {
      setLoading(true);
      try {
        const data = await api.listMeasurementBindings({ page: nextPage, page_size: nextPageSize, measurement_unit_id: unitSearch || undefined, status });
        setItems(data.items);
        setTotal(data.total);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "绑定关系加载失败");
      } finally {
        setLoading(false);
      }
    },
    [message, page, pageSize, status, unitSearch],
  );

  useEffect(() => { void load(); }, [load]);

  const updateBinding = async (binding: MeasurementBinding, nextStatus: "confirmed" | "ignored") => {
    try {
      await api.setMeasurementBindingStatus(binding.id, nextStatus, nextStatus === "confirmed" ? true : binding.enabled);
      message.success(nextStatus === "confirmed" ? "已确认绑定" : "已忽略绑定");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新失败");
    }
  };

  const columns: ColumnsType<MeasurementBinding> = [
    { title: "指标 ID", dataIndex: "metric_resource_id", key: "metric_resource_id", render: (value) => value || "-" },
    { title: "CSV 列名", dataIndex: "raw_source_name", key: "raw_source_name" },
    { title: "基础列名", dataIndex: "base_source_name", key: "base_source_name" },
    { title: "测量单元", dataIndex: "measurement_unit_id", key: "measurement_unit_id" },
    { title: "任务", dataIndex: "task_id", key: "task_id" },
    { title: "来源文件", dataIndex: "source_file", key: "source_file" },
    { title: "状态", dataIndex: "status", key: "status", width: 110, render: (value: string) => <Tag color={STATUS_COLORS[value]}>{STATUS_LABELS[value]}</Tag> },
    {
      title: "操作", key: "actions", width: 170,
      render: (_, record) => isAdmin && record.status !== "conflict" ? (
        <Space>
          <Button size="small" disabled={record.status === "confirmed"} onClick={() => void updateBinding(record, "confirmed")}>确认</Button>
          <Button size="small" disabled={record.status === "ignored"} onClick={() => void updateBinding(record, "ignored")}>忽略</Button>
        </Space>
      ) : null,
    },
  ];

  return (
    <Card title="指标绑定关系">
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search allowClear placeholder="按测量单元 ID 精确过滤" style={{ width: 280 }} onSearch={(value) => { setUnitSearch(value); setPage(1); void load(1, pageSize); }} />
        <Select allowClear placeholder="绑定状态" style={{ width: 160 }} value={status} onChange={(value) => { setStatus(value); setPage(1); void load(1, pageSize); }} options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))} />
        <Typography.Text type="secondary">共 {total} 条</Typography.Text>
      </Space>
      <Table rowKey="id" loading={loading} columns={columns} dataSource={items}
        pagination={{ current: page, pageSize, total, showSizeChanger: true, onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize); void load(nextPage, nextPageSize); } }} />
    </Card>
  );
}

interface DerivedFormValues {
  measurement_unit_id: string;
  metric_resource_id: string;
  numerator_metric_id: string;
  denominator_metric_id: string;
}

function MeasurementDerivedTab() {
  const { message } = App.useApp();
  const [form] = Form.useForm<DerivedFormValues>();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const create = async (values: DerivedFormValues) => {
    setSubmitting(true);
    try {
      await api.createMeasurementDerived(values);
      message.success("派生成功率指标已创建");
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
      <Alert type="info" showIcon message="当前支持成功率模板" description="分母均值为 0 时展示为疑似业务未触发，默认不按业务阈值判定。" style={{ marginBottom: 16 }} />
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建派生成功率</Button>
      <Modal open={open} title="派生成功率指标" confirmLoading={submitting} okText="创建" onCancel={() => setOpen(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={(values) => void create(values)}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <Form.Item name="measurement_unit_id" label="测量单元 ID" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="metric_resource_id" label="派生指标 ID" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="numerator_metric_id" label="分子指标 ID" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="denominator_metric_id" label="分母指标 ID" rules={[{ required: true }]}><Input /></Form.Item>
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
