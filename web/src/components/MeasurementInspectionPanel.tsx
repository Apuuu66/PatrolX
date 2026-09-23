import { Card, Descriptions, Empty, Progress, Space, Statistic, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";
import { ResourceNameCell } from "./ResourceNameCell";
import type {
  MeasurementKpiOverview,
  MeasurementMetadataMetric,
  MeasurementMetadataUnit,
  MeasurementTrend,
  MeasurementTrendPoint,
} from "../api/http";

const STATUS_COLORS: Record<string, string> = {
  pass: "green",
  warn: "gold",
  fail: "red",
  error: "default",
  skip: "blue",
};

const STATUS_LABELS: Record<string, string> = {
  pass: "通过",
  warn: "告警",
  fail: "失败",
  error: "异常",
  skip: "跳过",
};

const BUSINESS_STATUS_LABELS: Record<string, string> = {
  normal: "正常",
  warn: "阈值预警",
  fail: "阈值失败",
  unconfigured: "未配置阈值",
  not_applicable: "不适用",
  not_judgeable: "无法判定",
};

const TREND_LABELS: Record<string, string> = {
  stable: "稳定",
  rising: "上升",
  falling: "下降",
  spike: "突增",
  plunge: "突降",
  fluctuating: "波动",
  all_zero: "全 0",
  recovering: "恢复中",
  cannot_determine: "无法判断",
};

const IMPORTANCE_LABELS: Record<string, string> = {
  P0: "P0",
  P1: "P1",
  P2: "P2",
  normal: "普通",
};

const DIRECTION_LABELS: Record<string, string> = {
  higher_better: "越高越好",
  lower_better: "越低越好",
  neutral: "不判定",
};

const TREND_SIGNAL_COLORS: Record<string, string> = {
  improved: "green",
  worsened: "red",
  none: "blue",
};

const TREND_SIGNAL_LABELS: Record<string, string> = {
  improved: "改善",
  worsened: "恶化",
  none: "无方向信号",
};

function MetricReadTag({ metric }: { metric: MeasurementMetadataMetric }) {
  if (metric.read_status === "missing") return <Tag color="red">列缺失</Tag>;
  if (metric.read_status === "parse_error") return <Tag color="red">不可读</Tag>;
  if (metric.value_pattern === "all_zero") return <Tag color="blue">全 0</Tag>;
  return <Tag color="green">可读</Tag>;
}

function MetricBusinessTag({ metric }: { metric: MeasurementMetadataMetric }) {
  const status = metric.business_status;
  if (!status) return <Tag>旧数据</Tag>;
  const color = status === "fail" ? "red" : status === "warn" ? "gold" : status === "normal" ? "green" : "blue";
  return <Tag color={color}>{BUSINESS_STATUS_LABELS[status] ?? status}</Tag>;
}

function MiniTrend({ points }: { points: MeasurementTrendPoint[] }) {
  if (points.length < 2) {
    return <Typography.Text type="secondary">趋势点不足</Typography.Text>;
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 96;
      const y = 28 - ((point.value - min) / range) * 24;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg width="104" height="32" role="img" aria-label="任务内迷你趋势">
      <path d={path} fill="none" stroke="#1677ff" strokeWidth="2" />
    </svg>
  );
}

function TrendTable({ trends }: { trends: MeasurementTrend[] }) {
  return (
    <Table
      rowKey={(trend) => `${trend.object_key ?? "__all__"}-${trend.period_minutes ?? "unknown"}`}
      size="small"
      columns={[
        { title: "行对象", dataIndex: "object_key", key: "object_key", render: (value) => value || "__all__" },
        { title: "周期(分钟)", dataIndex: "period_minutes", key: "period_minutes", render: (value) => value ?? "-" },
        {
          title: "趋势标签",
          dataIndex: "label",
          key: "label",
          render: (value: string) => TREND_LABELS[value] ?? value,
        },
        {
          title: "方向信号",
          dataIndex: "signal",
          key: "signal",
          render: (value: string) => <Tag color={TREND_SIGNAL_COLORS[value]}>{TREND_SIGNAL_LABELS[value]}</Tag>,
        },
        { title: "说明", dataIndex: "reason", key: "reason", render: (value) => value || "-" },
        {
          title: "趋势点数",
          dataIndex: "point_count",
          key: "point_count",
          width: 110,
          render: (value: number | undefined) => value ?? 0,
        },
      ]}
      dataSource={trends}
      pagination={false}
    />
  );
}

function KpiOverviewCard({ overview }: { overview: MeasurementKpiOverview }) {
  const statusCounts = overview.status_counts ?? {};
  return (
    <Card size="small" title="KPI 总览" style={{ marginBottom: 12 }}>
      <Space wrap size={24} align="center">
        <div style={{ width: 120 }}>
          <Progress type="dashboard" percent={overview.health_score} size={100} />
          <Typography.Text type="secondary">最低健康分</Typography.Text>
        </div>
        <Statistic title="测量单元" value={overview.unit_count} />
        <Statistic title="指标数" value={overview.metric_count} />
        <Statistic title="阈值失败" value={overview.business_fail_count} valueStyle={{ color: "#cf1322" }} />
        <Statistic title="阈值预警" value={overview.business_warn_count} valueStyle={{ color: "#d46b08" }} />
        <Statistic title="数据异常" value={overview.data_error_count} />
        <Statistic title="趋势恶化" value={overview.trend_worsened_count} />
        <Statistic title="未配置阈值" value={overview.unconfigured_count} />
        <Statistic title="自动入库" value={overview.auto_registered_count ?? 0} />
        <Statistic title="跨单元冲突" value={overview.conflict_count ?? 0} />
        <Statistic title="未匹配文件" value={overview.unmatched_file_count ?? 0} />
        <Space direction="vertical" size={2}>
          {Object.entries(statusCounts).map(([status, count]) => (
            <Typography.Text key={status}>
              <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status] ?? status}</Tag> {count}
            </Typography.Text>
          ))}
        </Space>
      </Space>
    </Card>
  );
}

export function MeasurementInspectionPanel({ metadata }: { metadata?: Record<string, unknown> }) {
  const overview = useMemo(() => {
    return metadata?.kpi_overview ? (metadata.kpi_overview as MeasurementKpiOverview) : null;
  }, [metadata]);

  const units = useMemo(() => {
    const raw = metadata?.measurement_units;
    if (!Array.isArray(raw)) return [];
    return (raw as MeasurementMetadataUnit[])
      .map((unit) => ({ ...unit, metrics: [...unit.metrics] }))
      .sort((left, right) => (left.risk_summary?.health_score ?? 100) - (right.risk_summary?.health_score ?? 100));
  }, [metadata]);

  if (!units.length) {
    return <Empty description="没有可展示的测量单元结果" />;
  }

  return (
    <div data-testid="measurement-inspection-panel">
      {overview ? <KpiOverviewCard overview={overview} /> : null}
      {units.map((unit) => {
        const objectRows = Object.values(unit.objects ?? {});
        const risk = unit.risk_summary;
        const objectColumns: ColumnsType<NonNullable<MeasurementMetadataUnit["objects"]>[string]> = [
          { title: "行对象", dataIndex: "object_key", key: "object_key" },
          { title: "行数", dataIndex: "row_count", key: "row_count", width: 90 },
          { title: "有效值", dataIndex: "valid_count", key: "valid_count", width: 100 },
          { title: "空值", dataIndex: "null_count", key: "null_count", width: 90 },
          { title: "解析错误", dataIndex: "parse_error_count", key: "parse_error_count", width: 110 },
          {
            title: "业务状态",
            dataIndex: "business_status",
            key: "business_status",
            width: 120,
            render: (value: string) => (value ? BUSINESS_STATUS_LABELS[value] ?? value : "-"),
          },
          {
            title: "均值",
            dataIndex: "avg_value",
            key: "avg_value",
            width: 120,
            render: (value: number | null) => (value === null || value === undefined ? "-" : value.toFixed(4)),
          },
          {
            title: "数值特征",
            dataIndex: "value_pattern",
            key: "value_pattern",
            width: 120,
            render: (value: string) =>
              value === "all_zero" ? <Tag color="blue">全 0</Tag> : value === "unknown" ? <Tag>无数据</Tag> : <Tag color="green">正常</Tag>,
          },
        ];

        const importanceOrder: Record<string, number> = { P0: 0, P1: 1, P2: 2, normal: 3 };
        const metrics = [...unit.metrics].sort((left, right) => {
          const leftOrder = importanceOrder[left.importance ?? "normal"] ?? 3;
          const rightOrder = importanceOrder[right.importance ?? "normal"] ?? 3;
          if (leftOrder !== rightOrder) return leftOrder - rightOrder;
          return `${left.metric_resource_name_zh ?? ""}${left.metric_resource_id}`.localeCompare(
            `${right.metric_resource_name_zh ?? ""}${right.metric_resource_id}`,
            "zh-Hans-CN",
          );
        });

        return (
          <Card
            key={unit.measurement_unit_id}
            size="small"
            title={
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span>{unit.name_zh}</span>
                <Typography.Text type="secondary">{unit.measurement_unit_id}</Typography.Text>
                <Tag color={STATUS_COLORS[unit.status]}>{STATUS_LABELS[unit.status]}</Tag>
                {unit.reason && <Typography.Text type="secondary">{unit.reason}</Typography.Text>}
              </div>
            }
            extra={risk ? <Typography.Text strong>健康分 {risk.health_score}</Typography.Text> : null}
            style={{ marginBottom: 12 }}
          >
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="英文名">{unit.name_en}</Descriptions.Item>
              <Descriptions.Item label="文件数">{unit.file_count}</Descriptions.Item>
              <Descriptions.Item label="指标覆盖">{unit.metric_coverage ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="来源文件">{(unit.source_files ?? []).join("，") || "-"}</Descriptions.Item>
              <Descriptions.Item label="指标数">{unit.metrics.length}</Descriptions.Item>
              <Descriptions.Item label="行对象数">{objectRows.length}</Descriptions.Item>
            </Descriptions>

            <Table
              rowKey={(metric) => `${metric.metric_resource_id}-${metric.raw_source_name}`}
              size="small"
              columns={[
                {
                  title: "指标",
                  dataIndex: "metric_resource_id",
                  key: "metric_resource_id",
                  render: (_: unknown, metric: MeasurementMetadataMetric) => (
                    <ResourceNameCell name={metric.metric_resource_name_zh || metric.base_source_name} id={metric.metric_resource_id} />
                  ),
                },
                {
                  title: "重点",
                  dataIndex: "importance",
                  key: "importance",
                  width: 90,
                  render: (value: string) => IMPORTANCE_LABELS[value] ?? "普通",
                },
                { title: "CSV 列名", dataIndex: "raw_source_name", key: "raw_source_name" },
                { title: "单位", dataIndex: "display_unit", key: "display_unit", render: (value) => value || "-" },
                {
                  title: "可读性",
                  key: "read_status",
                  width: 110,
                  render: (_: unknown, metric: MeasurementMetadataMetric) => <MetricReadTag metric={metric} />,
                },
                {
                  title: "业务状态",
                  key: "business_status",
                  width: 130,
                  render: (_: unknown, metric: MeasurementMetadataMetric) => <MetricBusinessTag metric={metric} />,
                },
                {
                  title: "阈值",
                  key: "thresholds",
                  width: 170,
                  render: (_: unknown, metric: MeasurementMetadataMetric) =>
                    metric.warning_threshold === null && metric.critical_threshold === null
                      ? "-"
                      : `${metric.warning_threshold ?? "-"} / ${metric.critical_threshold ?? "-"}`,
                },
                {
                  title: "趋势",
                  key: "trend",
                  width: 190,
                  render: (_: unknown, metric: MeasurementMetadataMetric) => (
                    <Space direction="vertical" size={0}>
                      <Space size={4}>
                        <Tag color="blue">{TREND_LABELS[metric.trend_label ?? "cannot_determine"] ?? metric.trend_label}</Tag>
                        <Tag color={TREND_SIGNAL_COLORS[metric.trend_signal ?? "none"]}>
                          {TREND_SIGNAL_LABELS[metric.trend_signal ?? "none"]}
                        </Tag>
                      </Space>
                      <MiniTrend points={metric.trend_points ?? []} />
                    </Space>
                  ),
                },
              ]}
              dataSource={metrics}
              pagination={{ pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }}
              expandable={{
                expandedRowRender: (metric) => (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Descriptions size="small" column={4}>
                      <Descriptions.Item label="指标分组">{metric.metric_group || "未分组"}</Descriptions.Item>
                      <Descriptions.Item label="方向">{DIRECTION_LABELS[metric.direction ?? "neutral"]}</Descriptions.Item>
                      <Descriptions.Item label="预警阈值">{metric.warning_threshold ?? "-"}</Descriptions.Item>
                      <Descriptions.Item label="失败阈值">{metric.critical_threshold ?? "-"}</Descriptions.Item>
                    </Descriptions>
                    {metric.errors?.length ? (
                      <Typography.Text type="danger">{JSON.stringify(metric.errors)}</Typography.Text>
                    ) : null}
                    {metric.trends?.length ? <TrendTable trends={metric.trends} /> : null}
                    {metric.observations?.length ? (
                      <Table rowKey="object_key" size="small" columns={objectColumns} dataSource={metric.observations} pagination={false} />
                    ) : (
                      <Typography.Text type="secondary">没有行数据</Typography.Text>
                    )}
                  </Space>
                ),
              }}
            />

            {(unit.derived_metrics ?? []).length > 0 && (
              <Card type="inner" title="派生指标" size="small" style={{ marginTop: 12 }}>
                <Table
                  rowKey="metric_resource_id"
                  size="small"
                  columns={[
                    {
                      title: "派生指标",
                      dataIndex: "metric_resource_id",
                      key: "metric_resource_id",
                      render: (_: unknown, metric: NonNullable<MeasurementMetadataUnit["derived_metrics"]>[number]) => (
                        <ResourceNameCell name={metric.metric_resource_name_zh} id={metric.metric_resource_id} />
                      ),
                    },
                    {
                      title: "状态",
                      dataIndex: "status",
                      key: "status",
                      width: 100,
                      render: (value: string) => (
                        <Tag color={value === "pass" ? "green" : value === "warn" ? "gold" : "red"}>{value.toUpperCase()}</Tag>
                      ),
                    },
                    { title: "说明", dataIndex: "message", key: "message", render: (value) => value || "-" },
                    {
                      title: "覆盖率",
                      key: "value",
                      width: 120,
                      render: (_: unknown, record) =>
                        record.observations.length
                          ? `${record.observations.filter((item) => item.value !== null).length}/${record.observations.length}`
                          : "-",
                    },
                  ]}
                  dataSource={unit.derived_metrics ?? []}
                  pagination={false}
                  expandable={{
                    expandedRowRender: (record) => (
                      <Table
                        rowKey="object_key"
                        size="small"
                        columns={[
                          { title: "行对象", dataIndex: "object_key", key: "object_key" },
                          { title: "状态", dataIndex: "status", key: "status", width: 100, render: (value: string) => <Tag color={value === "pass" ? "green" : value === "warn" ? "gold" : "red"}>{value.toUpperCase()}</Tag> },
                          { title: "值", dataIndex: "value", key: "value", render: (value: number | null) => (value === null || value === undefined ? "-" : `${value.toFixed(2)}%`) },
                          { title: "说明", dataIndex: "message", key: "message", render: (value) => value || "-" },
                        ]}
                        dataSource={record.observations}
                        pagination={false}
                      />
                    ),
                  }}
                />
              </Card>
            )}
          </Card>
        );
      })}
    </div>
  );
}
