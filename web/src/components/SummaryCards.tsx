import { Card, Col, Row, Statistic } from "antd";
import type { TaskStats } from "../api/http";

const ITEMS = [
  { key: "total", label: "规则总数", color: "#1677ff" },
  { key: "pass", label: "通过", color: "#52c41a" },
  { key: "warn", label: "告警", color: "#faad14" },
  { key: "fail", label: "失败", color: "#ff4d4f" },
  { key: "error", label: "异常", color: "#8c8c8c" },
  { key: "skip", label: "跳过", color: "#1677ff" },
];

export function SummaryCards({ stats }: { stats?: TaskStats | null }) {
  return (
    <Row gutter={[12, 12]}>
      {ITEMS.map((item) => (
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
  );
}
