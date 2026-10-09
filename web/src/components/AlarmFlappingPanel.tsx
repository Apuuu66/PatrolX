import { Col, Descriptions, Empty, Row, Space, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Table } from "./ResizableTable";

/** `RuleResult.metadata.alarm_flapping` 的分组明细；字段口径见 030 规则结果契约。 */
export interface AlarmFlappingGroup {
  alarm_code: string;
  object: string | null;
  state: string;
  occurrence_count: number;
  cleared_count: number;
  uncleared_count: number;
  first_seen_at: string | null;
  recent_seen_at: string | null;
  recent_cleared_at: string | null;
  min_repeat_gap_sec: number | null;
  repeated: boolean;
  is_short: boolean;
  observation_insufficient: boolean;
  observation_gap_sec: number | null;
  in_window_occurrences: number;
  out_of_window_occurrences: number;
  out_of_window_reappear: boolean;
  unrecovered_after_window: boolean;
  flap_event_count: number;
  evidence_records: { source_file: string; line_no: number }[];
}

export interface AlarmFlappingMetadata {
  schema_version: number;
  policy: {
    short_alarm_sec: number;
    repeat_window_sec: number;
    min_repeat_count: number;
    flap_gap_sec: number;
    stable_observation_sec: number;
    operation_window: string;
    operation_window_enabled: boolean;
    parameter_source: string;
  };
  coverage?: { start_at: string | null; end_at: string | null; span_sec: number };
  totals: {
    rows: number;
    valid_rows: number;
    groups: number;
    excluded_rows: number;
    duplicate_rows: number;
    failed_files: number;
    findings_truncated: boolean;
    groups_truncated: boolean;
  };
  state_counts: Record<string, number>;
  groups: AlarmFlappingGroup[];
  notes?: string[];
}

const STATE_META: Record<string, { label: string; color: string; order: number }> = {
  uncleared_repeated: { label: "未清除且反复", color: "red", order: 0 },
  uncleared_single: { label: "未清除未反复", color: "gold", order: 1 },
  cleared_repeated: { label: "已清除但反复", color: "volcano", order: 2 },
  cleared_short: { label: "已清除但短告警", color: "orange", order: 3 },
  observation_insufficient: { label: "观察窗不足", color: "geekblue", order: 4 },
  cleared_stable: { label: "已清除且稳定", color: "green", order: 5 },
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm:ss") : value;
}

function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 60) return `${value} 秒`;
  if (value < 3600) return `${value} 秒（${Math.round(value / 60)} 分钟）`;
  return `${value} 秒（${(value / 3600).toFixed(1)} 小时）`;
}

function GroupKey({ group }: { group: AlarmFlappingGroup }) {
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text strong>{group.alarm_code || "未知告警码"}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {group.object || "对象未知"}
      </Typography.Text>
    </Space>
  );
}

function GroupFlags({ group }: { group: AlarmFlappingGroup }) {
  const flags: { key: string; text: string; color: string }[] = [];
  if (group.repeated) flags.push({ key: "repeated", text: `反复 ${group.flap_event_count} 段`, color: "red" });
  if (group.is_short) flags.push({ key: "short", text: "短告警", color: "orange" });
  if (group.observation_insufficient) flags.push({ key: "observation", text: "观察窗不足", color: "geekblue" });
  if (group.unrecovered_after_window) flags.push({ key: "unrecovered", text: "窗口后仍未恢复", color: "red" });
  if (group.out_of_window_reappear) flags.push({ key: "reappear", text: "窗口外再现", color: "volcano" });
  if (group.observation_gap_sec !== null && group.observation_gap_sec !== undefined && !group.observation_insufficient) {
    flags.push({ key: "gap", text: `观察窗 ${formatSeconds(group.observation_gap_sec)}`, color: "default" });
  }
  if (!flags.length) return <Typography.Text type="secondary">—</Typography.Text>;
  return (
    <Space size={4} wrap>
      {flags.map((flag) => (
        <Tag key={flag.key} color={flag.color} style={{ marginInlineEnd: 0 }}>
          {flag.text}
        </Tag>
      ))}
    </Space>
  );
}

const columns: ColumnsType<AlarmFlappingGroup> = [
  {
    title: "分组",
    dataIndex: "alarm_code",
    width: 220,
    render: (_value, group) => <GroupKey group={group} />,
  },
  {
    title: "结论",
    dataIndex: "state",
    width: 150,
    render: (state: string) => {
      const meta = STATE_META[state];
      return <Tag color={meta?.color ?? "default"}>{meta?.label ?? state}</Tag>;
    },
  },
  {
    title: "出现次数",
    dataIndex: "occurrence_count",
    width: 130,
    render: (count: number, group) => (
      <Space direction="vertical" size={0}>
        <Typography.Text>{count} 次</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已清除 {group.cleared_count} / 未清除 {group.uncleared_count}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "首次 / 最近出现",
    dataIndex: "first_seen_at",
    width: 220,
    render: (_value, group) => (
      <Space direction="vertical" size={0}>
        <Typography.Text style={{ fontSize: 12 }}>{formatTime(group.first_seen_at)}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          最近 {formatTime(group.recent_seen_at)}
        </Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          最近清除 {formatTime(group.recent_cleared_at)}
        </Typography.Text>
      </Space>
    ),
  },
  {
    title: "最短复发间隔",
    dataIndex: "min_repeat_gap_sec",
    width: 160,
    render: (value: number | null) => formatSeconds(value),
  },
  {
    title: "标记",
    key: "flags",
    render: (_value, group) => <GroupFlags group={group} />,
  },
  {
    title: "来源",
    key: "evidence",
    width: 260,
    render: (_value, group) => {
      const [first] = group.evidence_records ?? [];
      if (!first) return "—";
      const rest = (group.evidence_records?.length ?? 0) - 1;
      return (
        <Typography.Text style={{ fontSize: 12 }} ellipsis={{ tooltip: true }}>
          {first.source_file}:{first.line_no}
          {rest > 0 ? ` 等 ${group.evidence_records.length} 处` : ""}
        </Typography.Text>
      );
    },
  },
];

export function AlarmFlappingPanel({ metadata }: { metadata: AlarmFlappingMetadata }) {
  const groups = [...(metadata.groups ?? [])]
    .map((group, index) => ({ group, index }))
    .sort((left, right) => {
      const leftOrder = STATE_META[left.group.state]?.order ?? 99;
      const rightOrder = STATE_META[right.group.state]?.order ?? 99;
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      const leftSeen = left.group.recent_seen_at ?? "";
      const rightSeen = right.group.recent_seen_at ?? "";
      if (leftSeen !== rightSeen) return leftSeen < rightSeen ? 1 : -1;
      return left.index - right.index;
    })
    .map((item) => item.group);

  const totals = metadata.totals;
  const policy = metadata.policy;
  const extraCounters = [
    totals.excluded_rows ? `排除 ${totals.excluded_rows} 行` : "",
    totals.duplicate_rows ? `去重 ${totals.duplicate_rows} 行` : "",
    totals.failed_files ? `解析失败 ${totals.failed_files} 个文件` : "",
    metadata.groups.length < totals.groups ? `仅展示 ${metadata.groups.length}/${totals.groups} 个分组` : "",
  ].filter(Boolean);

  return (
    <div>
      <Space size={[4, 8]} wrap style={{ marginBottom: 12 }}>
        {Object.entries(STATE_META).map(([state, meta]) => (
          <Tag key={state} color={meta.color}>
            {meta.label} {metadata.state_counts?.[state] ?? 0}
          </Tag>
        ))}
      </Space>
      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, lg: 4 }}
        style={{ marginBottom: 12 }}
        items={[
          { key: "coverage", label: "覆盖窗口", children: `${formatTime(metadata.coverage?.start_at)} ~ ${formatTime(metadata.coverage?.end_at)}` },
          { key: "rows", label: "有效记录", children: `${totals.valid_rows}/${totals.rows}` },
          { key: "groups", label: "告警分组", children: `${totals.groups} 个` },
          {
            key: "policy",
            label: "本次阈值",
            children: (
              <Typography.Text style={{ fontSize: 12 }}>
                短告警 ≤ {policy.short_alarm_sec}s；{policy.repeat_window_sec}s 内 ≥ {policy.min_repeat_count} 次；
                闪断间隔 ≤ {policy.flap_gap_sec}s；稳定观察 ≥ {policy.stable_observation_sec}s
              </Typography.Text>
            ),
          },
          {
            key: "operation_window",
            label: "操作窗",
            children: policy.operation_window_enabled ? `${policy.operation_window}（本地时间，仅作证据）` : "未启用",
          },
          {
            key: "counters",
            label: "异常计数",
            children: extraCounters.length ? extraCounters.join("；") : "无排除、无重复、无解析失败",
          },
        ]}
      />
      {groups.length === 0 ? (
        <Empty description="无告警分组" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table
          rowKey={(group) => `${group.alarm_code}-${group.object ?? "unknown"}`}
          size="small"
          columns={columns}
          dataSource={groups}
          pagination={groups.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
          scroll={{ x: 1200 }}
        />
      )}
      {(metadata.notes ?? []).length > 0 && (
        <Row style={{ marginTop: 12 }}>
          <Col span={24}>
            {metadata.notes!.map((note) => (
              <div key={note}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {note}
                </Typography.Text>
              </div>
            ))}
          </Col>
        </Row>
      )}
    </div>
  );
}
