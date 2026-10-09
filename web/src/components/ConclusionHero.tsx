import type { ReactNode } from "react";
import { Button, Card, Space, Tooltip, Typography } from "antd";
import { FileTextOutlined, UnorderedListOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import type { RuleStatus, SystemInspection, TaskSummary } from "../api/http";
import { MetadataList, type MetadataListItem } from "./MetadataList";
import { PageHeader } from "./PageHeader";
import { StatusDistribution } from "./StatusDistribution";
import { TaskStatusTag } from "./StatusBadge";
import { RESULT_STATUS_META } from "./statusLabels";
import { formatTaskDuration } from "../utils/taskCard";
import { getDeviceIdDisplay } from "../utils/taskDisplay";
import { deriveTaskConclusion, type TaskConclusionTone } from "../utils/taskConclusion";
import { getStatusTextColor } from "../utils/statusTextColors";
import { getTaskFailureStage } from "../utils/taskFailure";
import type { StatusFilter } from "../utils/taskFilter";

const STATUS_COLOR = new Map<string, string>(
  RESULT_STATUS_META.map((meta) => [meta.key, meta.color]),
);

const TONE_STATUS: Record<TaskConclusionTone, RuleStatus> = {
  danger: "fail",
  warning: "warn",
  success: "pass",
  processing: "skip",
  neutral: "error",
};

function trimmed(value?: string | null): string {
  return (value ?? "").trim();
}

/**
 * FR-014 关键元数据：数据包、版本、设备、省份、运营商、网元类型、时间与耗时。
 *
 * 只收集真实有值的字段，不生成 "-" 占位；超过 4 项由 MetadataList 收纳进"更多元数据"（FR-010、R6）。
 */
function buildMetadataItems(task: TaskSummary, system: SystemInspection | null): MetadataListItem[] {
  const customer = system?.customer ?? {};
  const items: MetadataListItem[] = [];

  const push = (key: string, label: string, raw?: string | null) => {
    const value = trimmed(raw);
    if (value) items.push({ key, label, value });
  };

  push("package", "数据包", system?.package_file);
  push("version", "版本", task.customer_version ?? system?.version);

  const device = getDeviceIdDisplay(task, system?.customer);
  if (device.source !== null) {
    push(
      "device_id",
      "设备",
      device.source === "ledger" ? `${device.value}（台账解析）` : device.value,
    );
  }

  push("province", "省份", task.customer_province ?? customer.province);
  push("operator", "运营商", task.customer_operator ?? customer.operator);
  push("product", "网元类型", task.customer_product ?? customer.product);

  const createdAt = dayjs(task.created_at);
  if (createdAt.isValid()) {
    items.push({ key: "created_at", label: "创建时间", value: createdAt.format("YYYY-MM-DD HH:mm") });
  }

  const duration = formatTaskDuration(task.created_at, task.completed_at);
  if (duration) {
    items.push({ key: "duration", label: "耗时", value: duration });
  }

  return items;
}

export interface ConclusionHeroProps {
  task: TaskSummary;
  system: SystemInspection | null;
  /** 由可见规则推导的状态数量，供结论区状态计数使用 */
  statusCounts: Record<RuleStatus, number>;
  activeStatus: StatusFilter;
  onStatusClick: (status: RuleStatus) => void;
  /** 最新失败原因（来自执行日志），仅任务失败时使用 */
  failureReason?: string | null;
  onOpenReport: () => void;
  onOpenLogs: () => void;
  /** 页头右侧的次级操作（如「更多操作」菜单） */
  extraActions?: ReactNode;
}

/**
 * 任务结论 Hero：结论标签 + 一句话结论 + 状态计数 + 主操作 + 关键元数据（FR-014、FR-015、FR-019）。
 * 任务失败时主操作为失败日志入口；执行中 / 排队中禁用报告并说明原因。
 */
export function ConclusionHero({
  task,
  system,
  statusCounts,
  activeStatus,
  onStatusClick,
  failureReason = null,
  onOpenReport,
  onOpenLogs,
  extraActions,
}: ConclusionHeroProps) {
  const conclusion = deriveTaskConclusion(task, failureReason, getTaskFailureStage(task));
  const toneStatus = TONE_STATUS[conclusion.tone];
  const toneColor = STATUS_COLOR.get(toneStatus) ?? "#8c8c8c";
  // 文字用文本安全色、填充色保留标准状态色，两者分离满足 AA（FR-019、R13）。
  const toneTextColor = getStatusTextColor(toneStatus, "#595959");
  const blockedReason =
    task.status === "pending"
      ? "任务排队中，报告暂不可用。"
      : task.status === "running"
        ? "任务执行中，报告暂不可用。"
        : null;
  const primaryIsLogs = conclusion.nextAction === "logs";
  const primaryLabel = primaryIsLogs ? "查看失败日志" : "查看报告";
  const primaryIcon = primaryIsLogs ? <UnorderedListOutlined /> : <FileTextOutlined />;

  return (
    <Card className="conclusion-hero task-detail-panel" data-testid="conclusion-hero">
      <PageHeader
        title={<span title={task.name}>{task.name}</span>}
        description={`任务 ID：${task.task_id}`}
        status={<TaskStatusTag status={task.status} />}
        actions={
          <Space size={8}>
            {blockedReason ? (
              <Tooltip title={blockedReason}>
                <Button type="primary" icon={primaryIcon} disabled>
                  {primaryLabel}
                </Button>
              </Tooltip>
            ) : (
              <Button
                type="primary"
                icon={primaryIcon}
                onClick={primaryIsLogs ? onOpenLogs : onOpenReport}
              >
                {primaryLabel}
              </Button>
            )}
            {extraActions}
          </Space>
        }
      />

      <div className="conclusion-hero-body">
        <div className="conclusion-hero-conclusion">
          <span className="conclusion-hero-tag" data-status={toneStatus} style={{ color: toneTextColor }}>
            <span
              aria-hidden="true"
              className="conclusion-hero-tag-dot"
              style={{ background: toneColor }}
            />
            {conclusion.label}
          </span>
          <Typography.Text strong className="conclusion-hero-sentence">
            {conclusion.sentence}
          </Typography.Text>
        </div>
        {conclusion.detail ? (
          <Typography.Text type="secondary" className="conclusion-hero-detail">
            {conclusion.detail}
          </Typography.Text>
        ) : null}
        {blockedReason ? (
          <Typography.Text type="secondary" className="conclusion-hero-detail">
            {blockedReason}
          </Typography.Text>
        ) : null}

        <StatusDistribution
          stats={statusCounts}
          variant="full"
          activeStatus={activeStatus}
          onStatusClick={onStatusClick}
          emptyText="暂无规则结果"
        />

        <MetadataList items={buildMetadataItems(task, system)} />
      </div>
    </Card>
  );
}
