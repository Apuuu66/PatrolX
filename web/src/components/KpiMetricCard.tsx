import { Card, Typography } from "antd";

import { getKpiMetricCardView, type KpiCatalogItem } from "./kpiCatalogModel";

type KpiMetricCardVariant = "highlight" | "context" | "diagnostic" | "catalog";

interface Props {
  item: KpiCatalogItem;
  variant?: KpiMetricCardVariant;
  onClick?: () => void;
}

export function KpiMetricCard({ item, variant = "catalog", onClick }: Props) {
  const view = getKpiMetricCardView(item);
  const valueSize = variant === "highlight" ? 26 : 21;
  const borderColor =
    view.statusColor === "#ff4d4f" ? "#ffccc7" : view.statusColor === "#faad14" ? "#ffe58f" : "#f0f0f0";

  return (
    <Card
      size="small"
      style={{ height: "100%", borderColor, cursor: onClick ? "pointer" : undefined }}
      variant="outlined"
      onClick={onClick}
    >
      <Typography.Text type="secondary">{view.subtitle}</Typography.Text>
      <div style={{ fontWeight: 600, marginTop: 2 }}>{view.title}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 8 }}>
        <span style={{ fontSize: valueSize, fontWeight: 600 }}>{view.mainValueText}</span>
        {view.unitText && <span style={{ fontSize: 12, color: "#8c8c8c" }}>{view.unitText}</span>}
      </div>
      <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8, fontSize: 12, color: "#666" }}>
        <span style={{ color: view.statusColor, fontWeight: 600 }}>{view.statusLabel}</span>
        <span>{view.thresholdText}</span>
        {view.breachText && <span>{view.breachText}</span>}
      </div>
      <Typography.Text type="secondary" style={{ display: "block", marginTop: 6, fontSize: 12 }}>
        汇总：{view.aggregationText}
      </Typography.Text>
    </Card>
  );
}
