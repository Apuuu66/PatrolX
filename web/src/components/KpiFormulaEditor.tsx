import { useCallback, useEffect, useMemo, useState } from "react";
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  api,
  type KpiMetricRuleV4,
  type KpiMetricRulePageV4,
  type KpiMetricTypeV4,
  type KpiSemanticGroupV4,
  type KpiDisplayRoleV4,
  type KpiSourceTypeV4,
  type KpiThresholdV4,
} from "../api/http";
import { KpiMetricName, KpiMetricSelect, useKpiMetricCatalog } from "./KpiMetricSelect";
import { formatKpiMetricFormula } from "./kpiMetricCatalogModel";
import { KpiThresholdModal } from "./KpiThresholdModal";
import {
  buildMetricRulePayload,
  formatKpiThresholdSummary,
  groupThresholdsByMetricKey,
  KPI_AGGREGATION_OPTIONS as AGGREGATIONS,
  type KpiMetricRuleFormValues,
} from "./kpiConfigModel";


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

interface FormulaFormValues extends Omit<KpiMetricRuleFormValues, "unit"> {
  metric_key: string;
  unit: string;
}

interface ThresholdTarget {
  metricRule: KpiMetricRuleV4;
  threshold: KpiThresholdV4 | null;
}

export function KpiFormulaEditor({ operator, onChanged }: { operator: string; onChanged?: () => void }) {
  const { message } = App.useApp();
  const { metrics, metricIndex } = useKpiMetricCatalog();
  const [pageData, setPageData] = useState<KpiMetricRulePageV4 | null>(null);
  const [thresholds, setThresholds] = useState<KpiThresholdV4[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormulaFormValues>();
  const [thresholdTarget, setThresholdTarget] = useState<ThresholdTarget | null>(null);
  const sourceType = Form.useWatch("source_type", form);
  const existingMetricKeys = useMemo(
    () => new Set((pageData?.items ?? []).map((item) => item.metric_key)),
    [pageData],
  );
  const derivedMetricKeys = useMemo(
    () => new Set((pageData?.items ?? []).filter((item) => item.source_type === "derived").map((item) => item.metric_key)),
    [pageData],
  );
  const thresholdIndex = useMemo(() => groupThresholdsByMetricKey(thresholds), [thresholds]);

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

  const loadThresholds = useCallback(async () => {
    try {
      const firstPage = await api.listKpiThresholdsV4({ page: 1, page_size: 200 });
      const items = [...firstPage.items];
      const totalPages = Math.ceil(firstPage.total / 200);
      for (let nextPage = 2; nextPage <= totalPages; nextPage += 1) {
        const pageData = await api.listKpiThresholdsV4({ page: nextPage, page_size: 200 });
        items.push(...pageData.items);
      }
      setThresholds(items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "阈值加载失败");
    }
  }, [message]);

  useEffect(() => {
    void load();
    void loadThresholds();
  }, [load, loadThresholds]);

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
      await api.upsertKpiMetricRuleV4(
        values.metric_key.trim(),
        buildMetricRulePayload(values.metric_key, values, operator),
      );
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

  const openThreshold = (record: KpiMetricRuleV4) => {
    setThresholdTarget({ metricRule: record, threshold: thresholdIndex.get(record.metric_key) ?? null });
  };

  const columns: ColumnsType<KpiMetricRuleV4> = [
    {
      title: "指标",
      dataIndex: "metric_key",
      width: 240,
      ellipsis: true,
      render: (_, record) => (
        <Space size={4}>
          <KpiMetricName metricKey={record.metric_key} />
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
        record.formula
          ? formatKpiMetricFormula(record.formula, metrics, metricIndex)
          : "-",
    },
    {
      title: "阈值",
      key: "threshold",
      width: 130,
      render: (_, record) => formatKpiThresholdSummary(thresholdIndex.get(record.metric_key)),
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
      width: 190,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button size="small" type="link" onClick={() => openThreshold(record)}>
            {thresholdIndex.has(record.metric_key) ? "编辑阈值" : "配置阈值"}
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
          <Form.Item name="metric_key" label="指标" rules={[{ required: true, message: "请选择指标" }]}>
            <KpiMetricSelect id="metric_key" excludedKeys={existingMetricKeys} />
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
              <Form.Item name="numerator" label="分子指标" rules={[{ required: true, message: "请选择分子指标" }]}>
                <KpiMetricSelect excludedKeys={derivedMetricKeys} />
              </Form.Item>
              <Form.Item name="denominator" label="分母指标" rules={[{ required: true, message: "请选择分母指标" }]}>
                <KpiMetricSelect excludedKeys={derivedMetricKeys} />
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
      <KpiThresholdModal
        open={thresholdTarget !== null}
        metricRule={thresholdTarget?.metricRule ?? null}
        threshold={thresholdTarget?.threshold ?? null}
        operator={operator}
        onClose={() => setThresholdTarget(null)}
        onSaved={async () => {
          await loadThresholds();
          onChanged?.();
        }}
      />
    </Card>
  );
}
