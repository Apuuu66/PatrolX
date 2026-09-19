import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  api,
  type KpiRegisteredDomainV4,
  type KpiThresholdDirectionV4,
  type KpiThresholdPageV4,
  type KpiThresholdV4,
} from "../api/http";
import { buildThresholdPayload, KPI_THRESHOLD_PERIODS as PERIODS } from "./kpiConfigModel";

const DOMAINS: { value: KpiRegisteredDomainV4; label: string }[] = [
  { value: "call", label: "呼叫" },
  { value: "api", label: "接口" },
  { value: "media", label: "媒体" },
];

const DIRECTIONS: { value: KpiThresholdDirectionV4; label: string }[] = [
  { value: "min", label: "下限（低于告警）" },
  { value: "max", label: "上限（超过告警）" },
];

interface ThresholdFormValues {
  domain: KpiRegisteredDomainV4;
  metric_key: string;
  label: string;
  direction: KpiThresholdDirectionV4;
  unit: string;
  default: number;
  periods: Record<string, number | null>;
  threshold_id?: number;
}

export function KpiThresholdEditor({ operator, onChanged }: { operator: string; onChanged?: () => void }) {
  const { message } = App.useApp();
  const [pageData, setPageData] = useState<KpiThresholdPageV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<ThresholdFormValues>();

  const load = useCallback(async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    try {
      setPageData(await api.listKpiThresholdsV4({ page: nextPage, page_size: nextPageSize }));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "阈值加载失败");
    } finally {
      setLoading(false);
    }
  }, [message, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    form.setFieldsValue({ domain: "call", direction: "min", unit: "%", default: 99, periods: {} });
    setOpen(true);
  };

  const openEdit = (record: KpiThresholdV4) => {
    form.setFieldsValue({
      threshold_id: record.id,
      domain: record.domain,
      metric_key: record.metric_key,
      label: record.label,
      direction: record.direction,
      unit: record.unit,
      default: Number(record.default),
      periods: Object.fromEntries(PERIODS.map((period) => [period, record.periods[period] ?? null])),
    });
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload = buildThresholdPayload(values, operator);
    setSaving(true);
    try {
      if (values.threshold_id) await api.updateKpiThresholdV4(values.threshold_id, payload);
      else await api.createKpiThresholdV4(payload);
      message.success("阈值已保存，受影响的 KPI 规则需手动重跑");
      setOpen(false);
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (record: KpiThresholdV4) => {
    try {
      await api.deleteKpiThresholdV4(record.id);
      message.success("阈值已删除");
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const columns: ColumnsType<KpiThresholdV4> = [
    { title: "业务域", dataIndex: "domain", width: 90 },
    { title: "指标 Key", dataIndex: "metric_key", ellipsis: true },
    { title: "名称", dataIndex: "label", width: 160, ellipsis: true },
    { title: "方向", dataIndex: "direction", width: 80 },
    { title: "默认值", dataIndex: "default", width: 100 },
    {
      title: "周期阈值",
      key: "periods",
      render: (_, record) =>
        PERIODS.map((period) => (record.periods[period] !== undefined ? `${period}m:${record.periods[period]}` : null))
          .filter(Boolean)
          .join("，") || "-",
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 160,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button size="small" type="link" danger onClick={() => void remove(record)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="阈值规则"
      extra={
        <Button type="primary" onClick={openCreate}>
          新增阈值
        </Button>
      }
      styles={{ body: { paddingTop: 8 } }}
    >
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={pageData?.items ?? []}
        pagination={{
          current: pageData?.page ?? page,
          pageSize: pageData?.page_size ?? pageSize,
          total: pageData?.total ?? 0,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
            void load(nextPage, nextPageSize);
          },
        }}
      />
      <Modal
        title={form.getFieldValue("threshold_id") ? "编辑阈值" : "新增阈值"}
        open={open}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        onOk={() => void submit()}
        onCancel={() => setOpen(false)}
        width={680}
      >
        <Form form={form} layout="vertical">
          <Space wrap style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", width: "100%" }}>
            <Form.Item name="domain" label="业务域" rules={[{ required: true }]}>
              <Select options={DOMAINS} />
            </Form.Item>
            <Form.Item name="metric_key" label="指标 Key" rules={[{ required: true, message: "请输入指标 Key" }]}>
              <Input aria-label="指标 Key" />
            </Form.Item>
            <Form.Item name="label" label="阈值名称" rules={[{ required: true, message: "请输入阈值名称" }]}>
              <Input />
            </Form.Item>
            <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
              <Select options={DIRECTIONS} />
            </Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true, message: "请输入单位" }]}>
              <Input aria-label="单位" />
            </Form.Item>
            <Form.Item name="default" label="默认阈值" rules={[{ required: true, message: "请输入默认阈值" }]}>
              <InputNumber style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <Card size="small" title="周期阈值（可选，需覆盖默认值时填写）">
            <Space wrap style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", width: "100%" }}>
              {PERIODS.map((period) => (
                <Form.Item key={period} name={["periods", period]} label={`${period} 分钟`}>
                  <InputNumber style={{ width: "100%" }} />
                </Form.Item>
              ))}
            </Space>
          </Card>
        </Form>
      </Modal>
    </Card>
  );
}
