import { useEffect, useState } from "react";
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Space } from "antd";
import {
  api,
  type KpiMetricRuleV4,
  type KpiRegisteredDomainV4,
  type KpiThresholdDirectionV4,
  type KpiThresholdV4,
} from "../api/http";
import { buildThresholdFormValuesForMetric, buildThresholdPayload, KPI_THRESHOLD_PERIODS as PERIODS } from "./kpiConfigModel";
import { KpiMetricName, useKpiMetricCatalog } from "./KpiMetricSelect";

const DOMAINS: { value: KpiRegisteredDomainV4; label: string }[] = [
  { value: "call", label: "呼叫" },
  { value: "api", label: "接口" },
  { value: "media", label: "媒体" },
];

const DIRECTIONS: { value: KpiThresholdDirectionV4; label: string }[] = [
  { value: "min", label: "下限（低于告警）" },
  { value: "max", label: "上限（超过告警）" },
];

interface KpiThresholdModalProps {
  open: boolean;
  metricRule: KpiMetricRuleV4 | null;
  threshold: KpiThresholdV4 | null;
  operator: string;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

interface ThresholdFormValues {
  domain: KpiRegisteredDomainV4;
  metric_key: string;
  label: string;
  direction: KpiThresholdDirectionV4;
  unit: string;
  default: number | undefined;
  periods: Record<string, number | null>;
  threshold_id?: number;
}

export function KpiThresholdModal({
  open,
  metricRule,
  threshold,
  operator,
  onClose,
  onSaved,
}: KpiThresholdModalProps) {
  const { message, modal } = App.useApp();
  const { metricIndex } = useKpiMetricCatalog();
  const [form] = Form.useForm<ThresholdFormValues>();
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!open || !metricRule) return;
    form.resetFields();
    form.setFieldsValue(
      buildThresholdFormValuesForMetric(
        metricRule,
        threshold,
        metricIndex.get(metricRule.metric_key)?.name_zh || metricIndex.get(metricRule.metric_key)?.name_en,
      ),
    );
  }, [form, metricIndex, metricRule, open, threshold]);

  const submit = async () => {
    if (!metricRule) return;
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = buildThresholdPayload(values, operator);
      if (values.threshold_id) {
        await api.updateKpiThresholdV4(values.threshold_id, payload);
      } else {
        await api.createKpiThresholdV4(payload);
      }
      message.success("阈值已保存，受影响的 KPI 规则需手动重跑");
      await onSaved();
      onClose();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!threshold) return;
    setDeleting(true);
    try {
      await api.deleteKpiThresholdV4(threshold.id);
      message.success("阈值已删除");
      await onSaved();
      onClose();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const confirmRemove = () => {
    if (!threshold) return;
    modal.confirm({
      title: "删除阈值",
      content: "删除后该指标不再参与阈值判断。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => remove(),
    });
  };

  return (
    <Modal
      title={threshold ? "编辑阈值" : "配置阈值"}
      open={open}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      onOk={() => void submit()}
      onCancel={onClose}
      width={680}
      footer={
        <Space>
          {threshold ? (
            <Button danger loading={deleting} onClick={confirmRemove}>
              删除阈值
            </Button>
          ) : null}
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={() => void submit()}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item label="指标">{metricRule ? <KpiMetricName metricKey={metricRule.metric_key} /> : null}</Form.Item>
        <Space wrap style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", width: "100%" }}>
          <Form.Item name="domain" label="业务域" rules={[{ required: true }]}>
            <Select options={DOMAINS} disabled />
          </Form.Item>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
            <Select options={DIRECTIONS} />
          </Form.Item>
          <Form.Item name="label" label="阈值名称" rules={[{ required: true, message: "请输入阈值名称" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="unit" label="单位" rules={[{ required: true, message: "请输入单位" }]}>
            <Input aria-label="单位" />
          </Form.Item>
          <Form.Item name="default" label="默认阈值" rules={[{ required: true, message: "请输入默认阈值" }]}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
        </Space>
        <Form.Item name="metric_key" hidden>
          <Input />
        </Form.Item>
        <Form.Item name="threshold_id" hidden>
          <InputNumber />
        </Form.Item>
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
  );
}
