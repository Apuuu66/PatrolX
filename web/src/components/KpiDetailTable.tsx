import { Table, Tag, Typography } from "antd";
import type { RuleResult } from "../api/http";

type KpiError = {
  code?: string;
  column?: string;
  message?: string;
  value?: number | string;
};

type KpiRecord = {
  line_number?: number;
  period_minutes?: number;
  start_at?: string;
  end_at?: string;
  values?: Record<string, number>;
  derived?: Record<string, number>;
  errors?: KpiError[];
};

type KpiFile = {
  path?: string;
  domain?: string;
  period_minutes?: number;
  measurement_set?: string;
  status?: string;
  errors?: KpiError[];
  objects?: string[];
  records?: KpiRecord[];
};

type KpiDetailRow = {
  key: string;
  file: string;
  period: number | string;
  startAt: string;
  endAt: string;
  metric: string;
  value: string;
  errors: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readKpiFiles(metadata: RuleResult["metadata"]): KpiFile[] {
  if (!isRecord(metadata) || !Array.isArray(metadata.kpi_files)) {
    return [];
  }
  return metadata.kpi_files.filter(isRecord) as KpiFile[];
}

function errorText(errors: KpiError[]): string[] {
  return errors
    .filter((error) => error.code || error.message)
    .map((error) => [error.code, error.message].filter(Boolean).join(": "));
}

function formatValue(value: number | undefined): string {
  return value === undefined || Number.isNaN(value) ? "-" : String(value);
}

export function KpiDetailTable({ metadata }: { metadata: RuleResult["metadata"] }) {
  const files = readKpiFiles(metadata);

  if (!files.length) {
    return <Typography.Text type="secondary">无 KPI 明细数据</Typography.Text>;
  }

  const rows: KpiDetailRow[] = [];
  files.forEach((file, fileIndex) => {
    (file.records ?? []).forEach((record, recordIndex) => {
      const metrics: Array<[string, number | undefined]> = [
        ...Object.entries(record.values ?? {}).map(([name, value]): [string, number | undefined] => [name, value]),
        ...Object.entries(record.derived ?? {}).map(([name, value]): [string, number | undefined] => [
          `derived.${name}`,
          value,
        ]),
      ];
      const rowErrors = errorText(record.errors ?? []);
      const base = {
        file: file.path ?? "-",
        period: record.period_minutes ?? file.period_minutes ?? "-",
        startAt: record.start_at ?? "-",
        endAt: record.end_at ?? "-",
        errors: rowErrors,
      };

      if (!metrics.length) {
        rows.push({
          key: `${fileIndex}-${recordIndex}-empty`,
          ...base,
          metric: "-",
          value: "-",
        });
        return;
      }

      metrics.forEach(([metric, value], metricIndex) => {
        rows.push({
          key: `${fileIndex}-${recordIndex}-${metricIndex}-${metric}`,
          ...base,
          metric,
          value: formatValue(value),
        });
      });
    });
  });

  return (
    <Table
      size="small"
      dataSource={rows}
      pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
      scroll={{ x: true }}
      columns={[
        { title: "来源文件", dataIndex: "file", width: 260, ellipsis: true },
        { title: "周期（分钟）", dataIndex: "period", width: 110 },
        { title: "开始时间（UTC）", dataIndex: "startAt", width: 180 },
        { title: "结束时间（UTC）", dataIndex: "endAt", width: 180 },
        { title: "指标", dataIndex: "metric", width: 180 },
        { title: "值", dataIndex: "value", width: 110 },
        {
          title: "错误",
          dataIndex: "errors",
          render: (errors: string[]) =>
            errors.length ? errors.map((error) => <Tag key={error} color="red">{error}</Tag>) : "-",
        },
      ]}
    />
  );
}
