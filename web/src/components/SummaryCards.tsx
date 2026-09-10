import { Card, Col, Row, Space, Statistic } from "antd";
import type { OverviewSummary, TaskStats } from "../api/http";

type OverviewMetricKey = "task_count" | "registered_rule_count" | "rule_result_count" | "finding_count";

const OVERVIEW_ITEMS: Array<{ key: OverviewMetricKey; label: string; color: string }> = [
  { key: "task_count", label: "巡检任务", color: "#1677ff" },
  { key: "registered_rule_count", label: "注册规则", color: "#1677ff" },
  { key: "rule_result_count", label: "规则结果", color: "#1677ff" },
  { key: "finding_count", label: "发现问题", color: "#1677ff" },
];

const STATUS_ITEMS = [
  { key: "pass", label: "通过", color: "#52c41a" },
  { key: "warn", label: "告警", color: "#faad14" },
  { key: "fail", label: "失败", color: "#ff4d4f" },
  { key: "error", label: "异常", color: "#8c8c8c" },
  { key: "skip", label: "跳过", color: "#1677ff" },
];


export function SummaryCards({
  overview,
  stats,
}: {
  overview?: OverviewSummary | null;
  stats?: TaskStats | null;
}) {
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
        {STATUS_ITEMS.map((item) => (
          <Col key={item.key} xs={12} sm={8} md={4}>
            <Card size="small" styles={{ body: { padding: "12px 16px" } }}>
              <Statistic
                title={item.label}
                value={stats?.[item.key as keyof TaskStats] ?? 0}
                valueStyle={{ color: item.color, fontWeight: 600 }}
              />
            </Card>
          </Col>
        ))}
      </Row>
    </Space>
  );
}
