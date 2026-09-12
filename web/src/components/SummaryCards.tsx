import { Card, Col, Row, Space, Statistic } from "antd";
import type { OverviewSummary, RuleStatus, TaskStats } from "../api/http";

type OverviewMetricKey = "task_count" | "registered_rule_count" | "rule_result_count" | "finding_count";

const OVERVIEW_ITEMS: Array<{ key: OverviewMetricKey; label: string; color: string }> = [
  { key: "task_count", label: "巡检任务", color: "#1677ff" },
  { key: "registered_rule_count", label: "注册规则", color: "#1677ff" },
  { key: "rule_result_count", label: "规则结果", color: "#1677ff" },
  { key: "finding_count", label: "发现问题", color: "#1677ff" },
];

const STATUS_ITEMS: Array<{ key: RuleStatus; label: string; color: string }> = [
  { key: "pass", label: "通过", color: "#52c41a" },
  { key: "warn", label: "告警", color: "#faad14" },
  { key: "fail", label: "失败", color: "#ff4d4f" },
  { key: "error", label: "异常", color: "#8c8c8c" },
  { key: "skip", label: "跳过", color: "#1677ff" },
];

export function SummaryCards({
  overview,
  stats,
  statusCounts,
  activeStatus,
  onStatusClick,
}: {
  overview?: OverviewSummary | null;
  stats?: TaskStats | null;
  /** 由可见规则列表推导的状态数量；提供后优先于 stats */
  statusCounts?: Record<RuleStatus, number>;
  /** 当前激活的状态过滤 key；null 表示无过滤 */
  activeStatus?: RuleStatus | null;
  /** 点击状态数量时的回调；不传则保持纯展示 */
  onStatusClick?: (status: RuleStatus) => void;
}) {
  const clickable = typeof onStatusClick === "function";

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {overview && (
        <Row gutter={[12, 12]}>
          {OVERVIEW_ITEMS.map((item) => (
            <Col key={item.key} xs={12} sm={12} md={6}>
              <Card size="small" styles={{ body: { padding: "12px 16px" } }}>
                <Statistic
                  title={item.label}
                  value={overview[item.key]}
                  valueStyle={{ color: item.color, fontWeight: 600 }}
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}
      <Row gutter={[12, 12]}>
        {STATUS_ITEMS.map((item) => {
          const value = statusCounts ? statusCounts[item.key] : (stats?.[item.key as keyof TaskStats] ?? 0);
          const isActive = activeStatus === item.key;
          return (
            <Col key={item.key} xs={12} sm={8} md={4}>
              <Card
                size="small"
                styles={{ body: { padding: "12px 16px" } }}
                style={
                  clickable
                    ? {
                        cursor: "pointer",
                        border: isActive ? `2px solid ${item.color}` : undefined,
                        boxShadow: isActive ? `0 0 8px ${item.color}40` : undefined,
                        transition: "box-shadow 0.2s, border-color 0.2s",
                      }
                    : undefined
                }
                onClick={clickable ? () => onStatusClick(item.key) : undefined}
              >
                <Statistic
                  title={item.label}
                  value={value}
                  valueStyle={{ color: item.color, fontWeight: 600 }}
                />
              </Card>
            </Col>
          );
        })}
      </Row>
    </Space>
  );
}
