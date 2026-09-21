import { Card, Descriptions, Empty, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";
import type { MeasurementMetadataMetric, MeasurementMetadataUnit } from "../api/http";

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

function MetricStatusTag({ metric }: { metric: MeasurementMetadataMetric }) {
  if (metric.read_status === "missing") return <Tag color="red">列缺失</Tag>;
  if (metric.read_status === "parse_error") return <Tag color="red">不可读</Tag>;
  if (metric.value_pattern === "all_zero") return <Tag color="blue">全 0</Tag>;
  return <Tag color="green">可读</Tag>;
}

export function MeasurementInspectionPanel({ metadata }: { metadata?: Record<string, unknown> }) {
  const units = useMemo(() => {
    const raw = metadata?.measurement_units;
    return Array.isArray(raw) ? (raw as MeasurementMetadataUnit[]) : [];
  }, [metadata]);

  if (!units.length) {
    return <Empty description="没有可展示的测量单元结果" />;
  }

  return (
    <div data-testid="measurement-inspection-panel">
      {units.map((unit) => {
        const objectRows = Object.values(unit.objects ?? {});
        const objectColumns: ColumnsType<NonNullable<MeasurementMetadataUnit["objects"]>[string]> = [
          { title: "行对象", dataIndex: "object_key", key: "object_key" },
          { title: "行数", dataIndex: "row_count", key: "row_count", width: 90 },
          { title: "有效值", dataIndex: "valid_count", key: "valid_count", width: 100 },
          { title: "空值", dataIndex: "null_count", key: "null_count", width: 90 },
          { title: "解析错误", dataIndex: "parse_error_count", key: "parse_error_count", width: 110 },
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
                { title: "指标 ID", dataIndex: "metric_resource_id", key: "metric_resource_id" },
                { title: "CSV 列名", dataIndex: "raw_source_name", key: "raw_source_name" },
                { title: "单位", dataIndex: "display_unit", key: "display_unit", render: (value) => value || "-" },
                {
                  title: "状态",
                  key: "status",
                  width: 120,
                  render: (_: unknown, metric: MeasurementMetadataMetric) => <MetricStatusTag metric={metric} />,
                },
              ]}
              dataSource={unit.metrics}
              pagination={false}
              expandable={{
                expandedRowRender: (metric) => {
                  if (!metric.observations?.length) {
                    return <Typography.Text type="secondary">{metric.errors?.length ? JSON.stringify(metric.errors) : "没有行数据"}</Typography.Text>;
                  }
                  return (
                    <Table rowKey="object_key" size="small" columns={objectColumns} dataSource={metric.observations} pagination={false} />
                  );
                },
              }}
            />

            {(unit.derived_metrics ?? []).length > 0 && (
              <Card type="inner" title="派生指标（成功率）" size="small" style={{ marginTop: 12 }}>
                <Table
                  rowKey="metric_resource_id"
                  size="small"
                  columns={[
                    { title: "派生指标", dataIndex: "metric_resource_id", key: "metric_resource_id" },
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
