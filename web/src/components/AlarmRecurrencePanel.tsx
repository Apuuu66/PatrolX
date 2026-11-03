import { Alert, Descriptions, Empty, Space, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

import { Table } from "./ResizableTable";

interface CountMap {
  [key: string]: number;
}

export interface AlarmRecurrenceFlags {
  multi_lifecycle: boolean;
  repeat_reporting: boolean;
  short_alarm: boolean;
  rapid_recurrence: boolean;
  reset_cleared: boolean;
}

export interface AlarmRecurrenceObject {
  object: string;
  lifecycle_count: number;
  not_cleared_count: number;
  raw_repeat_times_total: number;
  max_single_repeat_times: number;
  estimated_report_total: number;
  repeat_totals_complete: boolean;
  first_raised_at: string | null;
  last_raised_at: string | null;
  max_duration_sec: number | null;
  min_adjacent_gap_sec: number | null;
  status_counts: CountMap;
  severity_counts: CountMap;
  flags: AlarmRecurrenceFlags;
}

export interface AlarmRecurrenceType extends AlarmRecurrenceObject {
  type_key: string;
  app_name: string;
  alarm_id: string;
  alarm_name: string;
  object_count?: number;
  objects?: AlarmRecurrenceObject[];
  objects_truncated?: boolean;
  source_refs: Array<{ source_file: string; line_no: number }>;
}

export interface AlarmRecurrenceMetadata {
  schema_version?: number;
  parameters?: {
    short_alarm_sec?: number;
    rapid_recurrence_window_sec?: number;
    rapid_recurrence_min_count?: number;
    parameter_source?: string;
  };
  coverage?: {
    start_at?: string | null;
    end_at?: string | null;
    span_sec?: number;
    end_basis?: string;
    timezone_policy?: string;
    observation_note?: string;
  };
  totals?: {
    source_files?: number;
    failed_files?: number;
    raw_rows?: number;
    valid_records?: number;
    excluded_records?: number;
    duplicate_records?: number;
    alarm_types?: number;
    multi_lifecycle_types?: number;
    repeat_reporting_types?: number;
    short_alarm_types?: number;
    rapid_recurrence_types?: number;
    reset_cleared_records?: number;
    repeat_positive_records?: number;
    repeat_totals_complete?: boolean;
    estimated_report_totals_complete?: boolean;
    types_truncated?: boolean;
    details_truncated?: boolean;
    findings_truncated?: boolean;
  };
  status_counts?: CountMap;
  severity_counts?: CountMap;
  types?: AlarmRecurrenceType[];
  notes?: string[];
}

export interface AlarmRecurrenceMetric {
  key: string;
  value: unknown;
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  "Not Cleared": { label: "未清除", color: "red" },
  "Normal Cleared": { label: "正常清除", color: "green" },
  "Reset Cleared": { label: "Reset Cleared", color: "orange" },
  Unknown: { label: "未知", color: "default" },
};

const SEVERITY_META: Record<string, { label: string; color: string }> = {
  CRITICAL: { label: "紧急", color: "red" },
  HIGH: { label: "严重", color: "volcano" },
  MEDIUM: { label: "重要", color: "gold" },
  LOW: { label: "次要", color: "blue" },
  UNKNOWN: { label: "未知", color: "default" },
};

const FLAG_META: Array<{ key: keyof AlarmRecurrenceFlags; label: string; color: string }> = [
  { key: "multi_lifecycle", label: "多次发生", color: "blue" },
  { key: "repeat_reporting", label: "重复上报", color: "red" },
  { key: "short_alarm", label: "短告警", color: "orange" },
  { key: "rapid_recurrence", label: "快速复发", color: "volcano" },
  { key: "reset_cleared", label: "Reset Cleared", color: "gold" },
];

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm:ss") : value;
}

function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 60) return `${value} 秒`;
  if (value < 3600) return `${value} 秒（${Math.round(value / 60)} 分钟）`;
  return `${value} 秒（${(value / 3600).toFixed(1)} 小时）`;
}

function metricNumber(metrics: AlarmRecurrenceMetric[] | undefined, key: string, fallback: number): number {
  const value = metrics?.find((metric) => metric.key === key)?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function StatusSummary({ counts }: { counts: CountMap | undefined }) {
  const current = counts ?? {};
  return (
    <Space size={[4, 4]} wrap>
      {Object.entries(STATUS_META).map(([state, meta]) => (
        <Tag key={state} color={meta.color}>
          {meta.label} {current[state] ?? 0}
        </Tag>
      ))}
    </Space>
  );
}

function SeveritySummary({ counts }: { counts: CountMap | undefined }) {
  const current = counts ?? {};
  return (
    <Space size={[4, 4]} wrap>
      {Object.entries(SEVERITY_META).map(([severity, meta]) => (
        <Tag key={severity} color={meta.color}>
          {meta.label} {current[severity] ?? 0}
        </Tag>
      ))}
    </Space>
  );
}

function FlagTags({ flags }: { flags: Partial<AlarmRecurrenceFlags> | undefined }) {
  const active = FLAG_META.filter((flag) => flags?.[flag.key]);
  if (!active.length) return <Typography.Text type="secondary">无风险标记</Typography.Text>;
  return (
    <Space size={[4, 4]} wrap>
      {active.map((flag) => (
        <Tag key={flag.key} color={flag.color}>
          {flag.label}
        </Tag>
      ))}
    </Space>
  );
}

function RepeatCell({ type }: { type: AlarmRecurrenceType }) {
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text>{type.raw_repeat_times_total} 次</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        单条最大 {type.max_single_repeat_times}
      </Typography.Text>
      {!type.repeat_totals_complete && (
        <Typography.Text type="warning" style={{ fontSize: 12 }}>
          汇总不完整
        </Typography.Text>
      )}
    </Space>
  );
}

function SourceRefCell({ type }: { type: AlarmRecurrenceType }) {
  const first = type.source_refs?.[0];
  if (!first) return "—";
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text code style={{ fontSize: 12 }}>
        {first.source_file}:{first.line_no}
      </Typography.Text>
      {(type.source_refs?.length ?? 0) > 1 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          等 {type.source_refs.length} 处
        </Typography.Text>
      )}
    </Space>
  );
}

const TYPE_COLUMNS: ColumnsType<AlarmRecurrenceType> = [
  {
    title: "告警类型",
    key: "type",
    width: 270,
    render: (_value, type) => (
      <Space direction="vertical" size={0}>
        <Typography.Text strong>{type.alarm_name || "未知告警"}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {type.app_name} / {type.alarm_id}
        </Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {type.object_count ?? type.objects?.length ?? 0} 个对象
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "生命周期",
    key: "lifecycle",
    width: 130,
    render: (_value, type) => (
      <Space direction="vertical" size={0}>
        <Typography.Text>{type.lifecycle_count} 条</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          未清除 {type.not_cleared_count}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "原始重复",
    key: "repeat",
    width: 145,
    render: (_value, type) => <RepeatCell type={type} />,
  },
  {
    title: "估算上报",
    key: "estimated",
    dataIndex: "estimated_report_total",
    width: 105,
    render: (value: number) => `${value} 次`,
  },
  {
    title: "最大单条重复",
    key: "max_repeat",
    dataIndex: "max_single_repeat_times",
    width: 120,
    render: (value: number) => `${value} 次`,
  },
  {
    title: "最长持续",
    key: "max_duration",
    dataIndex: "max_duration_sec",
    width: 170,
    render: (value: number | null) => formatDuration(value),
  },
  {
    title: "最短相邻间隔",
    key: "min_gap",
    dataIndex: "min_adjacent_gap_sec",
    width: 125,
    render: (value: number | null) => formatDuration(value),
  },
  {
    title: "标记",
    key: "flags",
    width: 230,
    render: (_value, type) => <FlagTags flags={type.flags} />,
  },
  {
    title: "首次 / 最近上报",
    key: "timestamps",
    width: 180,
    render: (_value, type) => (
      <Space direction="vertical" size={0}>
        <Typography.Text style={{ fontSize: 12 }}>{formatTime(type.first_raised_at)}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          最近 {formatTime(type.last_raised_at)}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "来源",
    key: "source",
    width: 250,
    render: (_value, type) => <SourceRefCell type={type} />,
  },
];

const OBJECT_COLUMNS: ColumnsType<AlarmRecurrenceObject> = [
  {
    title: "对象",
    key: "object",
    dataIndex: "object",
    width: 180,
    render: (value: string) => <Typography.Text strong>{value || "对象未知"}</Typography.Text>,
  },
  {
    title: "生命周期",
    key: "lifecycle",
    width: 110,
    render: (_value, object) => `${object.lifecycle_count} 条`,
  },
  {
    title: "原始重复 / 估算上报",
    key: "repeat",
    width: 180,
    render: (_value, object) => (
      <Space direction="vertical" size={0}>
        <Typography.Text>{object.raw_repeat_times_total} / {object.estimated_report_total} 次</Typography.Text>
        {!object.repeat_totals_complete && (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            重复汇总不完整
          </Typography.Text>
        )}
      </Space>
    ),
  },
  {
    title: "状态",
    key: "status",
    width: 330,
    render: (_value, object) => <StatusSummary counts={object.status_counts} />,
  },
  {
    title: "严重级",
    key: "severity",
    width: 300,
    render: (_value, object) => <SeveritySummary counts={object.severity_counts} />,
  },
  {
    title: "标记",
    key: "flags",
    width: 220,
    render: (_value, object) => <FlagTags flags={object.flags} />,
  },
  {
    title: "首次 / 最近上报",
    key: "timestamps",
    width: 180,
    render: (_value, object) => (
      <Space direction="vertical" size={0}>
        <Typography.Text style={{ fontSize: 12 }}>{formatTime(object.first_raised_at)}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          最近 {formatTime(object.last_raised_at)}
        </Typography.Text>
      </Space>
    ),
  },
];

const DETAIL_COLUMN_KEYS = new Set(["timestamps", "source"]);

export function AlarmRecurrencePanel({
  metadata,
  metrics,
  showAllColumns = false,
}: {
  metadata: AlarmRecurrenceMetadata;
  metrics?: AlarmRecurrenceMetric[];
  showAllColumns?: boolean;
}) {
  const totals = metadata.totals ?? {};
  const types = metadata.types ?? [];
  const fallbackRaw = types.reduce((sum, type) => sum + (type.raw_repeat_times_total ?? 0), 0);
  const fallbackEstimated = types.reduce((sum, type) => sum + (type.estimated_report_total ?? 0), 0);
  const rawTotal = metricNumber(metrics, "raw_repeat_times_total", fallbackRaw);
  const estimatedTotal = metricNumber(metrics, "estimated_reports_total", fallbackEstimated);
  const validLifecycles = metricNumber(metrics, "valid_lifecycles", totals.valid_records ?? 0);
  const alarmTypes = metricNumber(metrics, "alarm_types", totals.alarm_types ?? types.length);
  const parameters = metadata.parameters ?? {};
  const observationNote =
    metadata.coverage?.observation_note ?? "覆盖末刻是告警数据末刻，不是任务执行时刻或真实恢复时刻";

  const expandedRowRender = (type: AlarmRecurrenceType) => (
    <div data-testid="alarm-recurrence-objects">
      <Typography.Text strong>对象明细</Typography.Text>
      {type.objects?.length ? (
        <Table
          rowKey={(object) => `${type.type_key}:${object.object}`}
          size="small"
          columns={OBJECT_COLUMNS}
          dataSource={type.objects}
          pagination={false}
          scroll={{ x: 1500 }}
          style={{ marginTop: 8 }}
        />
      ) : (
        <Empty description="无对象明细" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
      {type.objects_truncated && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message={`对象明细仅展示前 100 条，共 ${type.object_count ?? type.objects?.length ?? 0} 个对象`}
        />
      )}
    </div>
  );

  return (
    <div>
      <div data-testid="alarm-recurrence-summary">
        <Space size={[6, 8]} wrap style={{ marginBottom: 8 }}>
          <Tag color="blue">有效生命周期 {validLifecycles}</Tag>
          <Tag>告警类型 {alarmTypes}</Tag>
          <Tag color="red">原始 Repeat Times {rawTotal} 次</Tag>
          <Tag color="orange">估算上报 {estimatedTotal} 次</Tag>
          <Tag>重复上报类型 {totals.repeat_reporting_types ?? 0}</Tag>
          <Tag>快速复发类型 {totals.rapid_recurrence_types ?? 0}</Tag>
          <Tag>Reset Cleared {totals.reset_cleared_records ?? 0}</Tag>
        </Space>

        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
          双计数口径：原始 Repeat Times 为 Σ Repeat Times；估算上报为 Σ(1 + Repeat Times)，不是精确事件总数。
          观察末刻：{formatTime(metadata.coverage?.end_at)}；{observationNote}。
        </Typography.Paragraph>
      </div>

      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, lg: 4 }}
        style={{ marginBottom: 12 }}
        items={[
          {
            key: "coverage",
            label: "告警覆盖区间",
            children: `${formatTime(metadata.coverage?.start_at)} ~ ${formatTime(metadata.coverage?.end_at)}`,
          },
          {
            key: "records",
            label: "有效记录",
            children: `${totals.valid_records ?? 0}/${totals.raw_rows ?? 0}`,
          },
          {
            key: "quality",
            label: "质量计数",
            children: `排除 ${totals.excluded_records ?? 0}；去重 ${totals.duplicate_records ?? 0}；失败文件 ${totals.failed_files ?? 0}`,
          },
          {
            key: "parameters",
            label: "风险阈值",
            children: `短告警 ≤ ${parameters.short_alarm_sec ?? "—"}s；${parameters.rapid_recurrence_window_sec ?? "—"}s 内 ≥ ${parameters.rapid_recurrence_min_count ?? "—"} 次`,
          },
        ]}
      />

      <Space size={[6, 8]} wrap style={{ marginBottom: 12 }}>
        <StatusSummary counts={metadata.status_counts} />
        <SeveritySummary counts={metadata.severity_counts} />
      </Space>

      {(totals.types_truncated || totals.details_truncated || totals.findings_truncated) && (
        <Alert
          data-testid="alarm-recurrence-truncated"
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="告警反复明细已截断"
          description="类型或对象明细仅展示前 100 条；汇总与指标仍基于全部有效数据。发现最多生成 100 条。"
        />
      )}

      <section data-testid="alarm-recurrence-types">
        <Typography.Text strong>告警类型聚合</Typography.Text>
        {types.length ? (
          <Table
            rowKey="type_key"
            size="small"
            columns={
              showAllColumns
                ? TYPE_COLUMNS
                : TYPE_COLUMNS.filter((column) => !DETAIL_COLUMN_KEYS.has(String(column.key)))
            }
            dataSource={types}
            pagination={types.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
            scroll={{ x: showAllColumns ? 1690 : 1320 }}
            style={{ marginTop: 8 }}
            expandable={{
              expandedRowRender,
              expandRowByClick: false,
              expandIcon: ({ expanded, onExpand, record }) => (
                <button
                  type="button"
                  aria-label={expanded ? "收起行" : "展开行"}
                  onClick={(event) => onExpand(record, event)}
                  style={{
                    border: 0,
                    background: "transparent",
                    color: "#1677ff",
                    cursor: "pointer",
                    padding: 0,
                  }}
                >
                  {expanded ? "收起" : "展开"}
                </button>
              ),
            }}
          />
        ) : (
          <Empty description="无告警类型汇总" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </section>

      {(metadata.notes ?? []).map((note) => (
        <Typography.Paragraph key={note} type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
          {note}
        </Typography.Paragraph>
      ))}
    </div>
  );
}
