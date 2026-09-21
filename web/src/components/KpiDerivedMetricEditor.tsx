import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { KpiMetricSelect, useKpiMetricCatalog } from "./KpiMetricSelect";
import { formatKpiMetricFormula } from "./kpiMetricCatalogModel";
import {
  buildKpiDerivedMetricPayload,
  validateKpiDerivedMetricDraft,
  type KpiDerivedMetricFormValues,
} from "./kpiDerivedMetricModel";
import {
  api,
  type KpiDerivedMetricPageV4,
  type KpiDerivedMetricV4,
  type KpiDisplayRoleV4,
  type KpiMetricTypeV4,
  type KpiRegisteredDomainV4,
  type KpiSemanticGroupV4,
} from "../api/http";

const DOMAINS: { value: KpiRegisteredDomainV4; label: string }[] = [
  { value: "call", label: "呼叫" },
  { value: "api", label: "接口" },
  { value: "media", label: "媒体" },
];

const METRIC_TYPES: { value: KpiMetricTypeV4; label: string }[] = [
  { value: "rate", label: "比率" },
  { value: "count", label: "计数" },
  { value: "gauge", label: "仪表" },
];

const SEMANTIC_GROUPS: { value: KpiSemanticGroupV4; label: string }[] = [
  { value: "quality", label: "质量" },
  { value: "traffic", label: "流量" },
  { value: "latency", label: "时延" },
  { value: "capacity", label: "容量" },
  { value: "other", label: "其他" },
];

const DISPLAY_ROLES: { value: KpiDisplayRoleV4; label: string }[] = [
  { value: "highlight", label: "重点展示" },
  { value: "context", label: "上下文" },
];

const FORMULA_KINDS = [
  { value: "ratio", label: "正向比率（分子 / 分母）" },
  { value: "inverse_ratio", label: "反向比率（1 - 分子 / 分母）" },
];


export function KpiDerivedMetricEditor({ onChanged }: { onChanged?: () => void }) {
  const { message, modal } = App.useApp();
  const { metrics, metricIndex } = useKpiMetricCatalog();
  const [pageData, setPageData] = useState<KpiDerivedMetricPageV4 | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<KpiDerivedMetricV4 | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<KpiDerivedMetricFormValues>();
  const domain = Form.useWatch("domain", form);
  const numerator = Form.useWatch("numerator", form);

  const load = useCallback(
    async (nextPage = page, nextPageSize = pageSize) => {
      setLoading(true);
      try {
        setPageData(await api.listKpiDerivedMetricsV4({ page: nextPage, page_size: nextPageSize }));
      } catch (err) {
        message.error(err instanceof Error ? err.message : "派生指标加载失败");
      } finally {
        setLoading(false);
      }
    },
    [message, page, pageSize],
  );

  useEffect(() => {
    void load();
    // 页面初始化只加载一次，分页由表格显式触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      domain: "call",
      metric_type: "rate",
      semantic_group: "quality",
      display_role: "highlight",
      enabled: true,
      formula_kind: "ratio",
      scale: 100,
    });
    setOpen(true);
  };

  const openEdit = (record: KpiDerivedMetricV4) => {
    setEditing(record);
    form.setFieldsValue({
      metric_key: record.metric_key,
      name_zh: record.name_zh,
      name_en: record.name_en,
      domain: record.domain,
      metric_type: record.metric_type,
      semantic_group: record.semantic_group,
      display_role: record.display_role,
      unit: record.unit,
      description: record.description ?? undefined,
      enabled: record.enabled,
      formula_kind: record.formula.kind,
      numerator: record.formula.numerator,
      denominator: record.formula.denominator,
      denominator_fallback_inputs: record.formula.denominator_fallback_inputs ?? [],
      scale: Number(record.formula.scale),
    });
    setOpen(true);
  };



  const submit = async () => {
    const values = await form.validateFields();
    const validationErrors = validateKpiDerivedMetricDraft(values, Boolean(editing));
    if (validationErrors.length > 0) {
      message.warning(validationErrors[0]);
      return;
    }
    setSaving(true);
    try {
      if (editing) await api.updateKpiDerivedMetricV4(editing.metric_key, buildKpiDerivedMetricPayload(values));
      else {
        const metricKey = values.metric_key?.trim() || undefined;
        await api.createKpiDerivedMetricV4({
          ...(metricKey ? { metric_key: metricKey } : {}),
          ...buildKpiDerivedMetricPayload(values),
        });
      }
      message.success("派生指标已保存，仅影响新任务");
      setOpen(false);
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = (record: KpiDerivedMetricV4) => {
    modal.confirm({
      title: "删除派生指标",
      content: `确认删除 ${record.name_zh}？历史任务不受影响。`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await api.deleteKpiDerivedMetricV4(record.metric_key);
          message.success("派生指标已删除");
          await load();
          onChanged?.();
        } catch (err) {
          message.error(err instanceof Error ? err.message : "删除失败");
        }
      },
    });
  };

  const columns: ColumnsType<KpiDerivedMetricV4> = [
    {
      title: "指标",
      dataIndex: "metric_key",
      width: 240,
      render: (_, record) => (
        <div style={{ minWidth: 0 }}>
          <div>{record.name_zh}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {record.metric_key}
          </Typography.Text>
        </div>
      ),
    },
    { title: "业务域", dataIndex: "domain", width: 90, render: (value: KpiRegisteredDomainV4) => DOMAINS.find((item) => item.value === value)?.label ?? value },
    { title: "单位", dataIndex: "unit", width: 80 },
    {
      title: "公式",
      key: "formula",
      render: (_, record) => formatKpiMetricFormula(record.formula, metrics, metricIndex),
    },
    {
      title: "状态",
      dataIndex: "enabled",
      width: 90,
      render: (value: boolean) => (value ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
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
          <Button size="small" type="link" danger onClick={() => remove(record)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const gridStyle = { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", width: "100%" };

  return (
    <Card
      title="派生指标"
      extra={
        <Button type="primary" onClick={openCreate}>
          新增派生指标
        </Button>
      }
      styles={{ body: { paddingTop: 8 } }}
    >
      <Table
        rowKey="metric_key"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={pageData?.items ?? []}
        pagination={{
          current: pageData?.page ?? page,
          pageSize: pageData?.page_size ?? pageSize,
          total: pageData?.total ?? 0,
          showSizeChanger: true,
          showTotal: (value) => `共 ${value} 条`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
            void load(nextPage, nextPageSize);
          },
        }}
      />
      <Modal
        title={editing ? "编辑派生指标" : "新增派生指标"}
        open={open}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        onOk={() => void submit()}
        onCancel={() => setOpen(false)}
        width={720}
      >
        <Form form={form} layout="vertical">
          <Space wrap style={gridStyle}>
            <Form.Item
              name="metric_key"
              label="指标 key"
              rules={editing ? [] : [{ pattern: /^[a-z][a-z0-9_]{2,127}$/, message: "派生指标 key 格式不正确" }]}
              extra="可不填，保存后自动生成；填写时为 3-128 位小写字母开头，可含数字和下划线"
            >
              <Input placeholder="不填则自动生成" disabled={Boolean(editing)} />
            </Form.Item>
            <Form.Item name="domain" label="业务域" rules={[{ required: true }]}>
              <Select options={DOMAINS} />
            </Form.Item>
            <Form.Item name="name_zh" label="中文名" rules={[{ required: true, message: "请输入中文名" }]}>
              <Input />
            </Form.Item>
            <Form.Item name="name_en" label="英文名" rules={[{ required: true, message: "请输入英文名" }]}>
              <Input />
            </Form.Item>
            <Form.Item name="metric_type" label="指标类型" rules={[{ required: true }]}>
              <Select options={METRIC_TYPES} />
            </Form.Item>
            <Form.Item name="semantic_group" label="语义分组" rules={[{ required: true }]}>
              <Select options={SEMANTIC_GROUPS} />
            </Form.Item>
            <Form.Item name="display_role" label="展示角色" rules={[{ required: true }]}>
              <Select options={DISPLAY_ROLES} />
            </Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true, message: "请输入单位" }]}>
              <Input placeholder="%" />
            </Form.Item>
          </Space>
          <Space wrap style={gridStyle}>
            <Form.Item name="formula_kind" label="公式类型" rules={[{ required: true }]}>
              <Select options={FORMULA_KINDS} />
            </Form.Item>
            <Form.Item name="scale" label="倍率 scale" rules={[{ required: true, message: "请输入倍率" }]}>
              <InputNumber<number> min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <Space wrap style={gridStyle}>
            <Form.Item name="numerator" label="分子指标" rules={[{ required: true, message: "请选择分子" }]}>
              <KpiMetricSelect domain={domain} />
            </Form.Item>
            <Form.Item name="denominator" label="分母指标" rules={[{ required: true, message: "请选择分母" }]}>
              <KpiMetricSelect domain={domain} excludedKeys={numerator ? new Set([numerator]) : undefined} />
            </Form.Item>
          </Space>
          <Form.Item name="denominator_fallback_inputs" label="分母 fallback（可选）">
            <KpiMetricSelect mode="multiple" domain={domain} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
