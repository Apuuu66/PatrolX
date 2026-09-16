import { useEffect, useState } from "react";
import { Alert, App, Breadcrumb, Button, Card, Descriptions, Empty, List, Spin, Space, Tag, Typography } from "antd";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type InspectorInfo, type RuleResult } from "../api/http";
import { KpiInspectionPanel } from "../components/KpiInspectionPanel";
import { MetricPanel } from "../components/MetricPanel";
import { RuleStatusTag, SeverityTag } from "../components/StatusBadge";

export function RuleDetailPage() {
  const { taskId = "", ruleCode = "" } = useParams();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [result, setResult] = useState<RuleResult | null>(null);
  const [meta, setMeta] = useState<InspectorInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const [r, inspectors] = await Promise.all([
          api.getRuleResult(taskId, ruleCode, true),
          api.listInspectors(undefined, true),
        ]);
        setResult(r);
        setMeta(inspectors.find((i) => i.code === ruleCode) ?? null);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [taskId, ruleCode, message]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin />
      </div>
    );
  }
  if (!result) {
    return <Empty description="规则结果不存在" />;
  }

  const conclusion = result.summary || meta?.description || "已完成规则执行";
  const hasKpiResults = Object.prototype.hasOwnProperty.call(result.metadata ?? {}, "kpi_files");
  const alertType = result.status === "fail" || result.status === "error" ? "error" : result.status === "warn" ? "warning" : "info";

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link to="/tasks">巡检任务</Link> },
          { title: <Link to={`/tasks/${taskId}`}>任务详情</Link> },
          { title: result.name },
        ]}
      />
      <Alert
        type={alertType}
        showIcon
        message={
          <Space wrap>
            <Typography.Text strong>{result.name}</Typography.Text>
            <RuleStatusTag status={result.status} skipReason={result.skip_reason} />
            <SeverityTag severity={result.severity} />
            <Typography.Text type="secondary">{result.code}</Typography.Text>
          </Space>
        }
        description={
          <div>
            <div>{conclusion}</div>
            {meta?.recommendation && (
              <Typography.Text type="secondary" style={{ display: "block", marginTop: 4 }}>
                建议：{meta.recommendation}
              </Typography.Text>
            )}
          </div>
        }
        style={{ marginBottom: 16 }}
      />

      <Card title={`发现（${(result.findings ?? []).length}）`} style={{ marginBottom: 16 }}>
        {(result.findings ?? []).length === 0 ? (
          <Typography.Text type="secondary">无发现</Typography.Text>
        ) : (
          <List
            dataSource={result.findings ?? []}
            renderItem={(f) => (
              <List.Item>
                <div style={{ width: "100%" }}>
                  <Space>
                    <SeverityTag severity={f.severity} />
                    <Typography.Text strong>{f.title}</Typography.Text>
                  </Space>
                  <div style={{ marginTop: 4, color: "#666" }}>
                    {f.source_file && <div>来源：{f.source_file}</div>}
                    {f.evidence && <div>证据：{f.evidence}</div>}
                    {f.details && <div>详情：{f.details}</div>}
                    {f.recommendation && <div>建议：{f.recommendation}</div>}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </Card>

      {hasKpiResults && (
        <Card title="KPI 巡检" style={{ marginBottom: 16 }}>
          <KpiInspectionPanel metadata={result.metadata} taskId={taskId} ruleCode={ruleCode} />
        </Card>
      )}

      <Card title="指标" style={{ marginBottom: 16 }}>
        <MetricPanel metrics={result.metrics ?? []} />
      </Card>

      <Card title="技术信息" style={{ marginBottom: 16 }}>
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: "desc", label: "规则描述", children: meta?.description ?? "-" },
            { key: "version", label: "规则版本", children: meta?.rule_version ?? "-" },
            { key: "duration", label: "执行耗时", children: `${result.duration_ms ?? "-"}ms` },
            { key: "priority", label: "优先级", children: `P${result.priority}` },
            {
              key: "source_patterns",
              label: "源文件匹配",
              children: (meta?.source_patterns ?? []).length ? meta!.source_patterns.map((i) => <Tag key={i}>{i}</Tag>) : "-",
            },
          ]}
        />
      </Card>

      <Button onClick={() => navigate(`/tasks/${taskId}`)}>
        返回任务详情
      </Button>
    </div>
  );
}
