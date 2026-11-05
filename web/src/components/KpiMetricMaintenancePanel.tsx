import { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  InputNumber,
  Modal,
  Radio,
  Select,
  Spin,
  Switch,
  Tag,
} from "antd";

import {
  api,
  type KpiMeasurementDerived,
  type KpiMeasurementDerivedUpdateRequest,
  type KpiMetricMaintenanceAudit,
  type KpiMetricMaintenanceConfig,
  type KpiMetricMaintenanceConfigUpdateRequest,
} from "../api/http";
import { useAuth } from "../auth/AuthContext";

const AGGREGATION_LABELS: Record<string, string> = {
  latest: "最新值",
  mean: "平均值",
  sum: "总和",
  max: "最大值",
  min: "最小值",
};

const DIRECTION_LABELS: Record<string, string> = {
  higher_better: "越高越好",
  lower_better: "越低越好",
  neutral: "不判定",
};

const ZERO_LABELS: Record<string, string> = {
  unknown: "全零待确认",
  expected_zero: "全零正常",
  business_not_triggered: "业务未触发",
};

const CONFIG_SOURCE_LABELS: Record<string, string> = {
  custom: "维护配置",
  default: "默认规则",
  legacy_resource: "旧资源字段",
  missing: "缺失",
};

interface MaintenanceValues {
  role: "base" | "derived";
  direction: "higher_better" | "lower_better" | "neutral" | null;
  warning_threshold: number | null;
  critical_threshold: number | null;
  daily_aggregation: "latest" | "mean" | "sum" | "max" | "min";
  daily_change_threshold: number | null;
  daily_change_threshold_unit: "pp" | "relative" | "auto";
  is_percentage: boolean;
  zero_semantics: "unknown" | "expected_zero" | "business_not_triggered";
  consistency_tolerance: number;
  object_match_mode: "exact";
  enabled: boolean;
}

interface DerivedValues {
  numerator_metric_id: string;
  denominator_metric_id: string;
  template: "success_rate" | "reverse_success_rate";
  enabled: boolean;
}

function derivedFormula(item: KpiMeasurementDerived): string {
  if (item.template === "reverse_success_rate") {
    return `100 - ${item.numerator_metric_name_zh} / ${item.denominator_metric_name_zh} × 100`;
  }
  return `${item.numerator_metric_name_zh} / ${item.denominator_metric_name_zh} × 100`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function ConfigStatusTag({ config }: { config: KpiMetricMaintenanceConfig }) {
  if (!config.enabled) return <Tag>已停用</Tag>;
  if (config.role === "derived") return <Tag color="blue">聚合指标</Tag>;
  return <Tag color="green">基础指标</Tag>;
}

export function KpiMetricMaintenancePanel() {
  const { message } = App.useApp();
  const { canWrite } = useAuth();
  const [configs, setConfigs] = useState<KpiMetricMaintenanceConfig[]>([]);
  const [derivedItems, setDerivedItems] = useState<KpiMeasurementDerived[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [maintenanceEditing, setMaintenanceEditing] = useState<KpiMetricMaintenanceConfig | null>(null);
  const [derivedEditing, setDerivedEditing] = useState<KpiMeasurementDerived | null>(null);
  const [auditTarget, setAuditTarget] = useState<KpiMetricMaintenanceConfig | null>(null);
  const [audits, setAudits] = useState<KpiMetricMaintenanceAudit[]>([]);
  const [auditsLoading, setAuditsLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [maintenanceForm] = Form.useForm<MaintenanceValues>();
  const [derivedForm] = Form.useForm<DerivedValues>();
  const watchedDerivedTemplate = Form.useWatch("template", derivedForm);
  const watchedNumerator = Form.useWatch("numerator_metric_id", derivedForm);
  const watchedDenominator = Form.useWatch("denominator_metric_id", derivedForm);

  const derivedCandidates = configs
    .filter((item) =>
      item.measurement_unit_id === derivedEditing?.measurement_unit_id
      && item.metric_resource_id !== derivedEditing?.metric_resource_id
      && item.enabled,
    )
    .map((item) => ({
      value: item.metric_resource_id,
      label: `${item.name_zh} · ${item.metric_resource_id}`,
    }));

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [configList, derivedList] = await Promise.all([
        api.listKpiMetricMaintenanceConfigs({ page: 1, page_size: 200 }),
        api.listKpiMeasurementDerived({ page: 1, page_size: 200 }),
      ]);
      setConfigs(configList.items);
      setDerivedItems(derivedList.items);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "维护配置加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAudits = useCallback(async (config: KpiMetricMaintenanceConfig) => {
    setAuditsLoading(true);
    try {
      const result = await api.listKpiMetricMaintenanceAudits(
        config.measurement_unit_id,
        config.metric_resource_id,
        { page: 1, page_size: 50 },
      );
      setAudits(result.items);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "审计记录加载失败");
    } finally {
      setAuditsLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  const openMaintenanceEditor = (config: KpiMetricMaintenanceConfig) => {
    setMaintenanceEditing(config);
    maintenanceForm.setFieldsValue({
      role: config.role,
      direction: config.direction ?? null,
      warning_threshold: config.warning_threshold ?? null,
      critical_threshold: config.critical_threshold ?? null,
      daily_aggregation: config.daily_aggregation,
      daily_change_threshold: config.daily_change_threshold ?? null,
      daily_change_threshold_unit: config.daily_change_threshold_unit,
      is_percentage: config.is_percentage,
      zero_semantics: config.zero_semantics,
      consistency_tolerance: config.consistency_tolerance,
      object_match_mode: config.object_match_mode,
      enabled: config.enabled,
    });
  };

  const saveMaintenance = async () => {
    if (!maintenanceEditing) return;
    try {
      const values = await maintenanceForm.validateFields();
      setSubmitting(true);
      const payload: KpiMetricMaintenanceConfigUpdateRequest = { ...values };
      const updated = await api.updateKpiMetricMaintenanceConfig(
        maintenanceEditing.measurement_unit_id,
        maintenanceEditing.metric_resource_id,
        payload,
      );
      setConfigs((current) => current.map((item) =>
        item.measurement_unit_id === updated.measurement_unit_id
          && item.metric_resource_id === updated.metric_resource_id
          ? updated
          : item,
      ));
      setMaintenanceEditing(null);
      message.success("维护配置已更新");
      void loadAudits(updated);
    } catch (error) {
      if (error instanceof Error) message.error(error.message);
    } finally {
      setSubmitting(false);
    }
  };

  const openDerivedEditor = (item: KpiMeasurementDerived) => {
    setDerivedEditing(item);
    derivedForm.setFieldsValue({
      numerator_metric_id: item.numerator_metric_id,
      denominator_metric_id: item.denominator_metric_id,
      template: item.template,
      enabled: item.enabled,
    });
  };

  const saveDerived = async () => {
    if (!derivedEditing) return;
    try {
      const values = await derivedForm.validateFields();
      setSubmitting(true);
      const payload: KpiMeasurementDerivedUpdateRequest = { ...values };
      const updated = await api.updateKpiMeasurementDerived(derivedEditing.id, payload);
      setDerivedItems((current) => current.map((item) => item.id === updated.id ? updated : item));
      setDerivedEditing(null);
      message.success("聚合公式已更新");
    } catch (error) {
      if (error instanceof Error) message.error(error.message);
    } finally {
      setSubmitting(false);
    }
  };

  const openAudits = (config: KpiMetricMaintenanceConfig) => {
    setAuditTarget(config);
    setAudits([]);
    void loadAudits(config);
  };

  if (loading) {
    return (
      <div className="kpi-maintenance-loading" role="status">
        <Spin />
        <span>正在加载指标维护配置…</span>
      </div>
    );
  }

  return (
    <div className="kpi-maintenance-panel">
      {loadError ? (
        <div className="kpi-maintenance-error" role="alert">
          <strong>维护配置加载失败</strong>
          <span>{loadError}</span>
          <Button onClick={() => void load()}>重试</Button>
        </div>
      ) : null}

      <section className="kpi-maintenance-intro">
        <div>
          <h3>指标维护配置</h3>
          <p>当前判定只使用启用测量单元、已确认且启用的绑定以及启用指标；配置变更后会记录审计。</p>
        </div>
        <div className="kpi-maintenance-legend">
          <Tag>未知全零会进入待配置</Tag>
          <Tag>成功率按同一对象/周期的分子总和 ÷ 分母总和计算</Tag>
        </div>
      </section>

      <Card
        title="基础与聚合指标配置"
        extra={<span className="kpi-health-secondary">共 {configs.length} 个指标</span>}
        className="kpi-maintenance-card"
      >
        {configs.length === 0 ? <Empty description="暂无维护配置" /> : (
          <div className="kpi-maintenance-table-scroll">
            <table className="kpi-maintenance-table" aria-label="指标维护配置">
              <thead>
                <tr>
                  <th scope="col">测量单元 / 指标</th>
                  <th scope="col">判定配置</th>
                  <th scope="col">日聚合</th>
                  <th scope="col">变化阈值</th>
                  <th scope="col">配置来源</th>
                  <th scope="col">更新时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((config) => (
                  <tr key={`${config.measurement_unit_id}:${config.metric_resource_id}`}>
                    <td>
                      <strong>{config.name_zh}</strong>
                      <span className="kpi-health-secondary">{config.metric_resource_id}</span>
                      <span className="kpi-health-secondary">{config.measurement_unit_id}</span>
                    </td>
                    <td>
                      <ConfigStatusTag config={config} />
                      <span>{DIRECTION_LABELS[config.direction ?? "neutral"] ?? "未配置方向"}</span>
                      <span className="kpi-health-secondary">
                        预警 {config.warning_threshold ?? "—"} / 失败 {config.critical_threshold ?? "—"}
                      </span>
                    </td>
                    <td>
                      <span>{AGGREGATION_LABELS[config.daily_aggregation] ?? config.daily_aggregation}</span>
                      <span className="kpi-health-secondary">{ZERO_LABELS[config.zero_semantics] ?? config.zero_semantics}</span>
                    </td>
                    <td>
                      <span>{config.daily_change_threshold === null ? "默认" : config.daily_change_threshold}</span>
                      <span className="kpi-health-secondary">{config.daily_change_threshold_unit}</span>
                    </td>
                    <td>{CONFIG_SOURCE_LABELS[config.config_source] ?? config.config_source}</td>
                    <td>{formatTimestamp(config.updated_at)}</td>
                    <td>
                      <div className="kpi-maintenance-actions">
                        <Button size="small" onClick={() => openAudits(config)}>审计记录</Button>
                        {canWrite ? (
                          <Button size="small" type="primary" onClick={() => openMaintenanceEditor(config)}>
                            编辑维护配置
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="聚合指标公式"
        extra={<span className="kpi-health-secondary">共 {derivedItems.length} 个聚合配置</span>}
        className="kpi-maintenance-card"
      >
        {derivedItems.length === 0 ? <Empty description="暂无聚合指标" /> : (
          <div className="kpi-maintenance-table-scroll">
            <table className="kpi-maintenance-table" aria-label="聚合指标配置">
              <thead>
                <tr>
                  <th scope="col">聚合指标</th>
                  <th scope="col">分子</th>
                  <th scope="col">分母</th>
                  <th scope="col">公式</th>
                  <th scope="col">状态</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {derivedItems.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.metric_resource_name_zh}</strong>
                      <span className="kpi-health-secondary">{item.metric_resource_id}</span>
                    </td>
                    <td>{item.numerator_metric_name_zh}</td>
                    <td>{item.denominator_metric_name_zh}</td>
                    <td><code>{derivedFormula(item)}</code></td>
                    <td><Tag color={item.enabled ? "green" : "default"}>{item.enabled ? "启用" : "停用"}</Tag></td>
                    <td>
                      {canWrite ? (
                        <Button size="small" type="primary" onClick={() => openDerivedEditor(item)}>
                          编辑聚合配置
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={maintenanceEditing !== null}
        title={maintenanceEditing ? `编辑维护配置 · ${maintenanceEditing.name_zh}` : "编辑维护配置"}
        confirmLoading={submitting}
        onCancel={() => setMaintenanceEditing(null)}
        onOk={() => void saveMaintenance()}
        okText="保存"
        cancelText="取消"
        width={760}
        destroyOnHidden
      >
        <Form form={maintenanceForm} layout="vertical" className="kpi-maintenance-form">
          <div className="kpi-maintenance-form-grid">
            <Form.Item label="指标角色" name="role">
              <Select options={[{ value: "base", label: "基础指标" }, { value: "derived", label: "聚合指标" }]} />
            </Form.Item>
            <Form.Item label="判定方向" name="direction">
              <Select
                allowClear
                options={[
                  { value: "higher_better", label: "越高越好" },
                  { value: "lower_better", label: "越低越好" },
                  { value: "neutral", label: "不判定" },
                ]}
              />
            </Form.Item>
            <Form.Item label="预警阈值" name="warning_threshold">
              <InputNumber style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="失败阈值" name="critical_threshold">
              <InputNumber style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="日聚合方式" name="daily_aggregation">
              <Select
                options={Object.entries(AGGREGATION_LABELS).map(([value, label]) => ({ value, label }))}
              />
            </Form.Item>
            <Form.Item label="日变化阈值" name="daily_change_threshold">
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="变化阈值单位" name="daily_change_threshold_unit">
              <Select
                options={[
                  { value: "auto", label: "自动" },
                  { value: "pp", label: "百分点（pp）" },
                  { value: "relative", label: "相对变化（%）" },
                ]}
              />
            </Form.Item>
            <Form.Item label="全零语义" name="zero_semantics">
              <Select
                options={[
                  { value: "unknown", label: "全零待确认" },
                  { value: "expected_zero", label: "全零正常" },
                  { value: "business_not_triggered", label: "业务未触发" },
                ]}
              />
            </Form.Item>
            <Form.Item label="一致性容差（pp）" name="consistency_tolerance">
              <InputNumber min={0} precision={2} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="对象匹配方式" name="object_match_mode">
              <Select options={[{ value: "exact", label: "对象与周期完全匹配" }]} />
            </Form.Item>
            <Form.Item label="百分比指标" name="is_percentage" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="启用配置" name="enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal
        open={derivedEditing !== null}
        title={derivedEditing ? `编辑聚合公式 · ${derivedEditing.metric_resource_name_zh}` : "编辑聚合公式"}
        confirmLoading={submitting}
        onCancel={() => setDerivedEditing(null)}
        onOk={() => void saveDerived()}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={derivedForm} layout="vertical">
          <Form.Item
            label="分子指标"
            name="numerator_metric_id"
            rules={[{ required: true, message: "请选择分子指标" }]}
          >
            <Select showSearch optionFilterProp="label" options={derivedCandidates} />
          </Form.Item>
          <Form.Item
            label="分母指标"
            name="denominator_metric_id"
            rules={[{ required: true, message: "请选择分母指标" }]}
          >
            <Select showSearch optionFilterProp="label" options={derivedCandidates} />
          </Form.Item>
          <Form.Item label="计算公式" name="template">
            <Radio.Group>
              <Radio value="success_rate">正向成功率</Radio>
              <Radio value="reverse_success_rate">反向成功率</Radio>
            </Radio.Group>
          </Form.Item>
          {derivedEditing ? (
            <div className="kpi-maintenance-formula-preview">
              <span>公式预览</span>
              <code>{derivedFormula({
                ...derivedEditing,
                numerator_metric_name_zh: derivedCandidates.find((item) => item.value === watchedNumerator)?.label.split(" · ")[0]
                  ?? derivedEditing.numerator_metric_name_zh,
                denominator_metric_name_zh: derivedCandidates.find((item) => item.value === watchedDenominator)?.label.split(" · ")[0]
                  ?? derivedEditing.denominator_metric_name_zh,
                template: watchedDerivedTemplate ?? derivedEditing.template,
              })}</code>
            </div>
          ) : null}
          <Form.Item label="启用配置" name="enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={auditTarget !== null}
        title={auditTarget ? `维护审计 · ${auditTarget.name_zh}` : "维护审计"}
        footer={<Button onClick={() => setAuditTarget(null)}>关闭</Button>}
        onCancel={() => setAuditTarget(null)}
        width={820}
        destroyOnHidden
      >
        {auditsLoading ? (
          <div className="kpi-maintenance-loading" role="status"><Spin /><span>正在加载审计记录…</span></div>
        ) : audits.length === 0 ? (
          <Empty description="暂无维护审计记录" />
        ) : (
          <div className="kpi-maintenance-audit-list">
            {audits.map((audit) => (
              <article key={audit.id}>
                <header>
                  <strong>{audit.actor}</strong>
                  <span>{formatTimestamp(audit.created_at)}</span>
                </header>
                <p>变更字段：{audit.changed_fields.join("、") || "—"}</p>
                <details>
                  <summary>查看变更前后值</summary>
                  <pre>{JSON.stringify({ before: audit.before_values, after: audit.after_values }, null, 2)}</pre>
                </details>
              </article>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}
