import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  api,
  type KpiAggregationKindV4,
  type KpiMetricRuleV4,
  type KpiMetricRulePageV4,
  type KpiMetricTypeV4,
  type KpiSemanticGroupV4,
  type KpiDisplayRoleV4,
  type KpiSourceTypeV4,
} from "../api/http";

const AGGREGATIONS: { value: KpiAggregationKindV4; label: string }[] = [
  { value: "sum", label: "求和 (sum)" },
  { value: "min", label: "最小值 (min)" },
  { value: "max", label: "最大值 (max)" },
  { value: "mean", label: "均值 (mean)" },
  { value: "count", label: "计数 (count)" },
  { value: "median", label: "中位数 (median)" },
  { value: "stddev", label: "标准差 (stddev)" },
  { value: "success_rate", label: "成功率 (success_rate)" },
];

const METRIC_TYPES: { value: KpiMetricTypeV4; label: string }[] = [
  { value: "count", label: "次数" },
  { value: "rate", label: "比率" },
  { value: "capacity", label: "容量" },
  { value: "latency", label: "时延" },
  { value: "gauge", label: "仪表" },
];

const SEMANTIC_GROUPS: { value: KpiSemanticGroupV4; label: string }[] = [
  { value: "traffic", label: "业务量" },
  { value: "quality", label: "质量" },
  { value: "latency", label: "时延" },
  { value: "capacity", label: "容量" },
  { value: "other", label: "其他" },
];

const DISPLAY_ROLES: { value: KpiDisplayRoleV4; label: string }[] = [
  { value: "highlight", label: "重点展示" },
  { value: "context", label: "上下文" },
];

const SOURCE_TYPES: { value: KpiSourceTypeV4; label: string }[] = [
  { value: "raw", label: "原始聚合" },
  { value: "derived", label: "派生公式" },
];

interface FormulaFormValues {
  metric_key: string;
  metric_type: KpiMetricTypeV4;
  semantic_group: KpiSemanticGroupV4;
  display_role: KpiDisplayRoleV4;
  unit: string;
  source_type: KpiSourceTypeV4;
  aggregation_kind: KpiAggregationKindV4;
  description?: string;
  numerator?: string;
  denominator?: string;
  scale?: number;
  denominator_fallback_inputs?: string;
}

export function KpiFormulaEditor({ operator, onChanged }: { operator: string; onChanged?: () => void }) {
  const { message } = App.useApp();
  const [pageData, setPageData] = useState<KpiMetricRulePageV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormulaFormValues>();
  const sourceType = Form.useWatch("source_type", form);

  const load = useCallback(async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    try {
      setPageData(await api.listKpiMetricRulesV4({ page: nextPage, page_size: nextPageSize }));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "指标公式加载失败");
    } finally {
      setLoading(false);
    }
  }, [message, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    form.setFieldsValue({
      metric_type: "count",
      semantic_group: "other",
      display_role: "context",
      unit: "",
      source_type: "raw",
      aggregation_kind: "sum",
      scale: 100,
      denominator_fallback_inputs: "",
    });
    setOpen(true);
  };

  const openEdit = (record: KpiMetricRuleV4) => {
    form.setFieldsValue({
      metric_key: record.metric_key,
      metric_type: record.metric_type,
      semantic_group: record.semantic_group,
      display_role: record.display_role,
      unit: record.unit,
      source_type: record.source_type,
      aggregation_kind: record.aggregation_kind,
      description: record.description ?? undefined,
      numerator: record.formula?.numerator,
      denominator: record.formula?.denominator,
      scale: record.formula ? Number(record.formula.scale) : 100,
      denominator_fallback_inputs: record.formula?.denominator_fallback_inputs?.join(","),
    });
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const derived = values.source_type === "derived";
      await api.upsertKpiMetricRuleV4(values.metric_key.trim(), {
        metric_type: values.metric_type,
        semantic_group: values.semantic_group,
        display_role: values.display_role,
        unit: values.unit,
        source_type: values.source_type,
        aggregation_kind: values.aggregation_kind,
        description: values.description || null,
        operator,
        formula: derived
          ? {
              kind: "ratio",
              numerator: values.numerator?.trim() ?? "",
              denominator: values.denominator?.trim() ?? "",
              denominator_fallback_inputs: (values.denominator_fallback_inputs ?? "")
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
              scale: values.scale ?? 100,
            }
          : null,
      });
      message.success("指标公式已保存，受影响的 KPI 规则需手动重跑");
      setOpen(false);
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (record: KpiMetricRuleV4) => {
    try {
      await api.deleteKpiMetricRuleV4(record.metric_key);
      message.success("已删除自定义规则并回退默认规则");
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const columns: ColumnsType<KpiMetricRuleV4> = [
    {
      title: "指标 Key",
      dataIndex: "metric_key",
      width: 220,
      ellipsis: true,
      render: (value: string, record) => (
        <Space size={4}>
          <span>{value}</span>
          {record.source_type === "derived" && <Tag color="blue">派生</Tag>}
        </Space>
      ),
    },
    { title: "类型", dataIndex: "metric_type", width: 100 },
    { title: "业务域", dataIndex: "domain", width: 90, render: (value) => value ?? "-" },
    { title: "单位", dataIndex: "unit", width: 80 },
    { title: "聚合", dataIndex: "aggregation_kind", width: 120 },
    {
      title: "公式",
      key: "formula",
      render: (_, record) =>
        record.formula ? `${record.formula.numerator} / ${record.formula.denominator} × ${record.formula.scale}` : "-",
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
      title="指标聚合与公式"
      extra={
        <Button type="primary" onClick={openCreate}>
          新增指标口径
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
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
            void load(nextPage, nextPageSize);
          },
        }}
      />
      <Modal
        title="指标口径"
        open={open}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        onOk={() => void submit()}
        onCancel={() => setOpen(false)}
        width={680}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="metric_key" label="指标 Key" rules={[{ required: true, message: "请输入指标 Key" }]}>
            <Input placeholder="me_call_attempts" disabled={Boolean(form.getFieldValue("metric_key") && pageData?.items.some((item) => item.metric_key === form.getFieldValue("metric_key")))} />
          </Form.Item>
          <Space wrap style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", width: "100%" }}>
            <Form.Item name="source_type" label="来源类型" rules={[{ required: true }]}>
              <Select options={SOURCE_TYPES} />
            </Form.Item>
            <Form.Item
              name="aggregation_kind"
              label="聚合公式"
              rules={[{ required: true, message: "请选择聚合公式" }]}
            >
              <Select options={AGGREGATIONS} />
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
              <Input placeholder="次 / % / 个" />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          {sourceType === "derived" && (
            <Card size="small" title="受控成功率公式：分子 / 分母 × scale">
              <Form.Item name="numerator" label="分子指标 Key" rules={[{ required: true, message: "请输入分子指标" }]}>
                <Input placeholder="me_call_success_count" />
              </Form.Item>
              <Form.Item name="denominator" label="分母指标 Key" rules={[{ required: true, message: "请输入分母指标" }]}>
                <Input placeholder="me_call_attempts" />
              </Form.Item>
              <Form.Item name="denominator_fallback_inputs" label="分母回退输入（逗号分隔，可选）">
                <Input placeholder="me_call_success_count,me_call_failure_count" />
              </Form.Item>
              <Form.Item name="scale" label="缩放倍数" rules={[{ required: true }]}>
                <InputNumber min={0} max={1000000} style={{ width: "100%" }} />
              </Form.Item>
            </Card>
          )}
        </Form>
      </Modal>
    </Card>
  );
}
