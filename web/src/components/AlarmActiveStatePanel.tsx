import { Alert, Descriptions, Empty, Space, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

import { Table } from "./ResizableTable";

export interface AlarmActiveSourceRef {
  source_file: string;
  line_no: number;
}

export interface AlarmActiveGroup {
  group_key: string;
  app_name: string;
  alarm_id: string;
  alarm_name: string;
  object: string;
  severity: string;
  first_raised_at: string | null;
  last_raised_at: string | null;
  duration_sec: number;
  lifecycle_count: number;
  raw_repeat_times_total: number;
  max_single_repeat_times: number;
  estimated_report_total: number;
  repeat_totals_complete: boolean;
  source_refs: AlarmActiveSourceRef[];
}

export interface AlarmActiveRecord {
  app_name: string;
  alarm_id: string;
  alarm_name: string;
  object: string;
  severity: string;
  state: string;
  raised_at: string | null;
  cleared_at: string | null;
  duration_sec: number;
  repeat_times: number | null;
  estimated_report_count: number | null;
  source_file: string;
  line_no: number;
}

export interface AlarmActiveMetadata {
  schema_version?: number;
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
    active_records?: number;
    active_groups?: number;
    repeat_totals_complete?: boolean;
    estimated_report_totals_complete?: boolean;
    details_truncated?: boolean;
    findings_truncated?: boolean;
  };
  status_counts?: Record<string, number>;
  active_severity_counts?: Record<string, number>;
  active_summary?: {
    highest_severity?: string;
    raw_repeat_times_total?: number;
    max_single_repeat_times?: number;
    estimated_report_total?: number;
    estimated_total_is_estimate?: boolean;
  };
  groups?: AlarmActiveGroup[];
  records?: AlarmActiveRecord[];
  notes?: string[];
}

const SEVERITY_META: Record<string, { label: string; color: string; order: number }> = {
  CRITICAL: { label: "紧急", color: "red", order: 0 },
  HIGH: { label: "严重", color: "volcano", order: 1 },
  MEDIUM: { label: "重要", color: "gold", order: 2 },
  LOW: { label: "次要", color: "blue", order: 3 },
  UNKNOWN: { label: "未知", color: "default", order: 4 },
  NONE: { label: "无", color: "green", order: 5 },
};

const STATUS_LABEL: Record<string, string> = {
  "Not Cleared": "未清除",
  "Normal Cleared": "正常清除",
  "Reset Cleared": "重置清除",
  Unknown: "未知",
};

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

function SeverityTag({ severity }: { severity: string }) {
  const meta = SEVERITY_META[severity] ?? SEVERITY_META.UNKNOWN;
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function SourceLocation({ sourceFile, lineNo }: { sourceFile: string; lineNo: number }) {
  return (
    <Typography.Text code style={{ fontSize: 12 }}>
      {sourceFile}:{lineNo}
    </Typography.Text>
  );
}

const GROUP_COLUMNS: ColumnsType<AlarmActiveGroup> = [
  {
    title: "告警分组",
    key: "alarm",
    width: 250,
    render: (_value, group) => (
      <Space direction="vertical" size={0}>
        <Typography.Text strong>{group.alarm_name || "未知告警"}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {group.app_name} / {group.alarm_id}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "严重级",
    key: "severity",
    dataIndex: "severity",
    width: 92,
    render: (severity: string) => <SeverityTag severity={severity} />,
  },
  {
    title: "对象",
    key: "object",
    dataIndex: "object",
    width: 180,
    render: (object: string) => <Typography.Text>{object || "对象未知"}</Typography.Text>,
  },
  {
    title: "持续时长",
    key: "duration_sec",
    dataIndex: "duration_sec",
    width: 170,
    render: (value: number) => formatDuration(value),
  },
  {
    title: "生命周期",
    key: "lifecycle_count",
    dataIndex: "lifecycle_count",
    width: 92,
    render: (value: number) => `${value} 条`,
  },
  {
    title: "原始重复",
    key: "repeat",
    width: 130,
    render: (_value, group) => (
      <Space direction="vertical" size={0}>
        <Typography.Text>{group.raw_repeat_times_total} 次</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          单条最大 {group.max_single_repeat_times}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "估算上报",
    key: "estimated",
    dataIndex: "estimated_report_total",
    width: 105,
    render: (value: number) => `${value} 次`,
  },
  {
    title: "最近上报",
    key: "last_raised_at",
    dataIndex: "last_raised_at",
    width: 175,
    render: (value: string | null) => formatTime(value),
  },
  {
    title: "来源",
    key: "source",
    width: 250,
    render: (_value, group) => {
      const first = group.source_refs?.[0];
      if (!first) return "—";
      return (
        <Space direction="vertical" size={0}>
          <SourceLocation sourceFile={first.source_file} lineNo={first.line_no} />
          {group.source_refs.length > 1 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              等 {group.source_refs.length} 处
            </Typography.Text>
          )}
        </Space>
      );
    },
  },
];

const RECORD_COLUMNS: ColumnsType<AlarmActiveRecord> = [
  {
    title: "告警记录",
    key: "alarm",
    width: 260,
    render: (_value, record) => (
      <Space direction="vertical" size={0}>
        <Typography.Text strong>{record.alarm_name || "未知告警"}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {record.app_name} / {record.alarm_id}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "严重级",
    key: "severity",
    dataIndex: "severity",
    width: 92,
    render: (value: string) => <SeverityTag severity={value} />,
  },
  {
    title: "对象",
    key: "object",
    dataIndex: "object",
    width: 180,
    render: (value: string) => value || "对象未知",
  },
  {
    title: "上报时间",
    key: "raised_at",
    dataIndex: "raised_at",
    width: 175,
    render: (value: string | null) => formatTime(value),
  },
  {
    title: "持续时长",
    key: "duration_sec",
    dataIndex: "duration_sec",
    width: 170,
    render: (value: number) => formatDuration(value),
  },
  {
    title: "Repeat Times",
    key: "repeat_times",
    dataIndex: "repeat_times",
    width: 125,
    render: (value: number | null) => (value === null ? "数据缺失" : `${value} 次`),
  },
  {
    title: "估算上报",
    key: "estimated_report_count",
    dataIndex: "estimated_report_count",
    width: 105,
    render: (value: number | null) => (value === null ? "无法估算" : `${value} 次`),
  },
  {
    title: "来源",
    key: "source",
    width: 250,
    render: (_value, record) => <SourceLocation sourceFile={record.source_file} lineNo={record.line_no} />,
  },
];

const DETAIL_COLUMN_KEYS = new Set(["last_raised_at", "source"]);

export function AlarmActiveStatePanel({
  metadata,
  showAllColumns = false,
}: {
  metadata: AlarmActiveMetadata;
  showAllColumns?: boolean;
}) {
  const totals = metadata.totals ?? {};
  const summary = metadata.active_summary ?? {};
  const highest = summary.highest_severity ?? "NONE";
  const highestMeta = SEVERITY_META[highest] ?? SEVERITY_META.UNKNOWN;
  const groups = metadata.groups ?? [];
  const records = metadata.records ?? [];
  const observationNote =
    metadata.coverage?.observation_note ?? "覆盖末刻是告警数据末刻，不是任务执行时刻或真实恢复时刻";

  return (
    <div>
      <div data-testid="alarm-active-summary">
        <Space size={[6, 8]} wrap style={{ marginBottom: 8 }}>
          <Tag color={highestMeta.color}>最高严重级 {highestMeta.label}</Tag>
          <Tag>活动记录 {totals.active_records ?? records.length}</Tag>
          <Tag>活动分组 {totals.active_groups ?? groups.length}</Tag>
          <Tag color="red">原始 Repeat Times {summary.raw_repeat_times_total ?? 0} 次</Tag>
          <Tag color="orange">估算上报 {summary.estimated_report_total ?? 0} 次</Tag>
          <Tag>单条最大重复 {summary.max_single_repeat_times ?? 0}</Tag>
        </Space>

        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
          估算口径：Σ(1 + Repeat Times)，不是精确事件总数。观察末刻：{formatTime(metadata.coverage?.end_at)}；{observationNote}。
        </Typography.Paragraph>
      </div>
      <Space size={[6, 8]} wrap data-testid="alarm-active-status-counts" style={{ marginBottom: 12 }}>
        {Object.entries(STATUS_LABEL).map(([state, label]) => (
          <Tag key={state}>{label} {metadata.status_counts?.[state] ?? 0}</Tag>
        ))}
        {Object.entries(SEVERITY_META)
          .filter(([key]) => key !== "NONE")
          .map(([severity, meta]) => (
            <Tag key={severity} color={meta.color}>
              活动{meta.label} {metadata.active_severity_counts?.[severity] ?? 0}
            </Tag>
          ))}
      </Space>

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
            key: "completeness",
            label: "计数完整性",
            children:
              totals.repeat_totals_complete === false || totals.estimated_report_totals_complete === false
                ? "存在缺失或无效 Repeat Times，重复汇总不完整"
                : "完整",
          },
        ]}
      />

      {(totals.details_truncated || totals.findings_truncated) && (
        <Alert
          data-testid="alarm-active-truncated"
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="活动明细已截断"
          description="明细仅展示前 100 条；汇总仍基于全部有效活动记录。发现最多生成 100 条。"
        />
      )}

      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <section data-testid="alarm-active-groups">
          <Typography.Text strong>活动告警分组</Typography.Text>
          {groups.length ? (
            <Table
              rowKey="group_key"
              size="small"
              columns={
                showAllColumns
                  ? GROUP_COLUMNS
                  : GROUP_COLUMNS.filter((column) => !DETAIL_COLUMN_KEYS.has(String(column.key)))
              }
              dataSource={groups}
              pagination={groups.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
              scroll={{ x: showAllColumns ? 1420 : 1030 }}
              style={{ marginTop: 8 }}
            />
          ) : (
            <Empty description="无未清除告警分组" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>

        <section data-testid="alarm-active-records">
          <Typography.Text strong>活动告警记录</Typography.Text>
          {records.length ? (
            <Table
              rowKey={(record) => `${record.source_file}:${record.line_no}:${record.alarm_id}`}
              size="small"
              columns={
                showAllColumns
                  ? RECORD_COLUMNS
                  : RECORD_COLUMNS.filter((column) => !DETAIL_COLUMN_KEYS.has(String(column.key)))
              }
              dataSource={records}
              pagination={records.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
              scroll={{ x: showAllColumns ? 1420 : 1000 }}
              style={{ marginTop: 8 }}
            />
          ) : (
            <Empty description="无未清除告警记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
      </Space>

      {(metadata.notes ?? []).map((note) => (
        <Typography.Paragraph key={note} type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
          {note}
        </Typography.Paragraph>
      ))}
    </div>
  );
}
