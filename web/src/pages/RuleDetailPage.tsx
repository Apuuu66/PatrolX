import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Breadcrumb,
  Button,
  Card,
  Collapse,
  Descriptions,
  List,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { RedoOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type InspectorInfo, type RuleResult, type TaskStatus } from "../api/http";
import { AlarmFlappingPanel, type AlarmFlappingMetadata } from "../components/AlarmFlappingPanel";
import { MeasurementInspectionPanel } from "../components/MeasurementInspectionPanel";
import { MetricPanel } from "../components/MetricPanel";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { RuleStatusTag, SeverityTag } from "../components/StatusBadge";
import { RESULT_STATUS_META } from "../components/statusLabels";
import { getRuleCategoryLabel } from "../utils/ruleCategories";

/** 重跑状态轮询间隔与上限（FR-023）。 */
const RERUN_POLL_INTERVAL_MS = 1500;
const RERUN_POLL_TIMEOUT_MS = 120_000;

const RULE_STATUS_COLOR = new Map<string, string>(RESULT_STATUS_META.map((meta) => [meta.key, meta.color]));
const RULE_STATUS_LABEL = new Map<string, string>(RESULT_STATUS_META.map((meta) => [meta.key, meta.label]));

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/** 轻量结果指纹：执行时间、耗时、结论或证据条数任一变化即视为重跑已产出新结果。 */
function resultSignature(result: RuleResult | null): string {
  if (!result) return "";
  return [
    result.status,
    result.executed_at ?? "",
    result.duration_ms ?? "",
    result.summary ?? "",
    (result.findings ?? []).length,
    (result.metrics ?? []).length,
  ].join("|");
}

export function RuleDetailPage() {
  const { taskId = "", ruleCode = "" } = useParams();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [result, setResult] = useState<RuleResult | null>(null);
  const [meta, setMeta] = useState<InspectorInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showAllColumns, setShowAllColumns] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchPageData = useCallback(async () => {
    const [ruleResult, inspectors] = await Promise.all([
      api.getRuleResult(taskId, ruleCode, ruleCode === "kpi.measurement_units"),
      api.listInspectors(undefined, true),
    ]);
    return { ruleResult, inspector: inspectors.find((item) => item.code === ruleCode) ?? null };
  }, [ruleCode, taskId]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const { ruleResult, inspector } = await fetchPageData();
      setResult(ruleResult);
      setMeta(inspector);
    } catch (err) {
      const text = err instanceof Error ? err.message : "加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      setLoading(false);
    }
  }, [fetchPageData, message]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 只刷新本页规则结果，不触发整页或其它区块重新加载（FR-023）。 */
  const refreshResult = useCallback(async () => {
    try {
      const { ruleResult } = await fetchPageData();
      if (mountedRef.current) setResult(ruleResult);
      return ruleResult;
    } catch {
      return null;
    }
  }, [fetchPageData]);

  const rerun = useCallback(async () => {
    if (rerunning) return;
    const before = result;
    setRerunning(true);
    try {
      await api.rerunTask(taskId, [ruleCode]);
      message.success(`已受理重跑 ${ruleCode}`);
      const deadline = Date.now() + RERUN_POLL_TIMEOUT_MS;
      let sawRunning = false;
      let finished = false;
      while (!finished && Date.now() < deadline) {
        await delay(RERUN_POLL_INTERVAL_MS);
        if (!mountedRef.current) return;
        const latest = await refreshResult();
        if (latest && resultSignature(latest) !== resultSignature(before)) {
          finished = true;
          break;
        }
        let status: TaskStatus | null = null;
        try {
          status = (await api.getTask(taskId)).status;
        } catch {
          status = null;
        }
        if (status === "pending" || status === "running") sawRunning = true;
        if (sawRunning && (status === "completed" || status === "failed")) finished = true;
      }
      await refreshResult();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重跑失败");
    } finally {
      if (mountedRef.current) setRerunning(false);
    }
  }, [message, refreshResult, rerunning, result, ruleCode, taskId]);

  if (loading && !result) {
    return <PageSkeleton rows={5} />;
  }
  if (!result) {
    if (loadError) {
      return <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />;
    }
    return (
      <EmptyState
        description="规则结果不存在"
        action={
          <Button onClick={() => navigate(`/tasks/${taskId}`)}>
            返回任务详情
          </Button>
        }
      />
    );
  }

  const conclusion = result.summary || meta?.description || "已完成规则执行";
  const recommendation = (meta?.recommendation ?? "").trim() || "该规则未声明处理建议，请结合发现与证据判断。";
  const statusColor = RULE_STATUS_COLOR.get(result.status) ?? "#8c8c8c";
  const statusLabel = RULE_STATUS_LABEL.get(result.status) ?? result.status;
  const skipReason = (result.skip_reason ?? "").trim() || "未提供跳过原因";
  const findings = result.findings ?? [];
  const metrics = result.metrics ?? [];
  const sourcePatterns = meta?.source_patterns ?? [];
  const hasMeasurementResults = Object.prototype.hasOwnProperty.call(result.metadata ?? {}, "measurement_units");
  const alarmFlapping = (result.metadata ?? {})["alarm_flapping"] as AlarmFlappingMetadata | undefined;
  const hasEvidence = Boolean(alarmFlapping) || hasMeasurementResults || metrics.length > 0;

  return (
    <div className="rule-detail-page">
      <Breadcrumb
        className="task-detail-breadcrumb"
        items={[
          { title: <Link to="/tasks">巡检任务</Link> },
          { title: <Link to={`/tasks/${taskId}`}>任务详情</Link> },
          { title: result.name },
        ]}
      />

      {/* 结论 + 建议（FR-020）：状态、严重度、结论摘要、处理建议与重跑入口都在首屏。 */}
      <Card className="conclusion-hero rule-detail-panel" data-testid="rule-section-conclusion">
        <PageHeader
          title={<span title={result.name}>{result.name}</span>}
          description={`规则编码：${result.code}`}
          status={
            <Space size={8} wrap>
              <RuleStatusTag status={result.status} skipReason={result.skip_reason} />
              <SeverityTag severity={result.severity} />
            </Space>
          }
          actions={
            <Button
              icon={<RedoOutlined />}
              loading={rerunning}
              disabled={rerunning}
              onClick={() => void rerun()}
            >
              {rerunning ? "重跑中…" : "重跑本规则"}
            </Button>
          }
        />
        <div className="conclusion-hero-body">
          <div className="conclusion-hero-conclusion">
            <span className="conclusion-hero-tag" style={{ background: statusColor }}>
              {statusLabel}
            </span>
            <Typography.Text strong className="conclusion-hero-sentence">
              {conclusion}
            </Typography.Text>
          </div>
          <div className="rule-detail-recommendation" data-testid="rule-recommendation">
            <Typography.Text type="secondary" className="rule-detail-recommendation-label">
              处理建议
            </Typography.Text>
            <Typography.Text>{recommendation}</Typography.Text>
          </div>
          {result.status === "skip" && (
            <Alert
              className="rule-detail-skip"
              data-testid="rule-skip-reason"
              type="info"
              showIcon
              message="该规则已跳过，不是通过"
              description={`跳过原因：${skipReason}`}
            />
          )}
          {rerunning && (
            <Alert
              className="rule-detail-rerun-progress"
              data-testid="rule-rerun-progress"
              type="info"
              showIcon
              message="规则重跑进行中"
              description="重跑已受理，完成后自动刷新本页结果。"
            />
          )}
        </div>
      </Card>

      {/* 源文件匹配（FR-020）：规则声明的 source_patterns 独立成区块。 */}
      <Card title="源文件匹配" className="rule-detail-panel" data-testid="rule-section-source-patterns">
        {sourcePatterns.length > 0 ? (
          <Space size={[4, 8]} wrap>
            {sourcePatterns.map((pattern) => (
              <Tag key={pattern} className="rule-source-pattern">
                {pattern}
              </Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">该规则未声明源文件匹配范围</Typography.Text>
        )}
      </Card>

      <Card
        title={`发现（${findings.length}）`}
        className="rule-detail-panel"
        data-testid="rule-section-findings"
      >
        {findings.length === 0 ? (
          <Typography.Text type="secondary">无发现</Typography.Text>
        ) : (
          <List
            dataSource={findings}
            renderItem={(finding) => (
              <List.Item>
                <div className="rule-finding">
                  <Space size={8} wrap>
                    <SeverityTag severity={finding.severity} />
                    <Typography.Text strong>{finding.title}</Typography.Text>
                  </Space>
                  <div className="rule-finding-body">
                    {finding.source_file && <div>来源：{finding.source_file}</div>}
                    {finding.evidence && <div>证据：{finding.evidence}</div>}
                    {finding.details && <div>详情：{finding.details}</div>}
                    {finding.recommendation && <div>建议：{finding.recommendation}</div>}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </Card>

      {/* 证据面板（FR-020、FR-022）：按规则条件渲染，默认精简列。 */}
      <Card
        title="证据"
        className="rule-detail-panel"
        data-testid="rule-section-evidence"
        extra={
          hasEvidence ? (
            <Space size={8}>
              <Typography.Text type="secondary">显示全部列</Typography.Text>
              <Switch
                size="small"
                checked={showAllColumns}
                aria-label="显示全部列"
                onChange={setShowAllColumns}
              />
            </Space>
          ) : null
        }
      >
        {hasEvidence ? (
          <div className="rule-evidence-sections">
            {alarmFlapping && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  告警生命周期分组
                </Typography.Text>
                <AlarmFlappingPanel metadata={alarmFlapping} showAllColumns={showAllColumns} />
              </section>
            )}
            {hasMeasurementResults && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  KPI 测量单元巡检
                </Typography.Text>
                <MeasurementInspectionPanel
                  metadata={result.metadata}
                  taskId={taskId}
                  ruleCode={ruleCode}
                  showAllColumns={showAllColumns}
                />
              </section>
            )}
            {metrics.length > 0 && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  指标
                </Typography.Text>
                <MetricPanel metrics={metrics} showAllColumns={showAllColumns} />
              </section>
            )}
          </div>
        ) : (
          <Typography.Text type="secondary">该规则未产生证据数据</Typography.Text>
        )}
      </Card>

      {/* 技术信息默认折叠（FR-005、FR-020）。 */}
      <Collapse
        className="task-technical-collapse rule-detail-technical"
        data-testid="rule-section-technical"
        items={[
          {
            key: "technical",
            label: "技术信息",
            children: (
              <Descriptions
                size="small"
                column={2}
                items={[
                  {
                    key: "code",
                    label: "规则编码",
                    children: (
                      <Typography.Text copyable={{ text: result.code }}>{result.code}</Typography.Text>
                    ),
                  },
                  { key: "name", label: "规则名称", children: result.name },
                  { key: "category", label: "分类", children: getRuleCategoryLabel(result.category) },
                  { key: "priority", label: "优先级", children: `P${result.priority}` },
                  { key: "execution_order", label: "执行序号", children: result.execution_order },
                  { key: "rule_version", label: "规则版本", children: meta?.rule_version ?? "-" },
                  {
                    key: "duration",
                    label: "执行耗时",
                    children: result.duration_ms == null ? "-" : `${result.duration_ms}ms`,
                  },
                  {
                    key: "executed_at",
                    label: "执行时间",
                    children: result.executed_at
                      ? dayjs(result.executed_at).format("YYYY-MM-DD HH:mm:ss")
                      : "-",
                  },
                  { key: "description", label: "规则描述", children: meta?.description ?? "-" },
                  {
                    key: "recommendation",
                    label: "处理建议",
                    children: meta?.recommendation ?? "-",
                  },
                  ...(result.status === "skip"
                    ? [{ key: "skip_reason", label: "跳过原因", children: skipReason }]
                    : []),
                  {
                    key: "source_patterns",
                    label: "源文件匹配",
                    children:
                      sourcePatterns.length > 0 ? (
                        <Space size={[4, 8]} wrap>
                          {sourcePatterns.map((pattern) => (
                            <Tag key={pattern} className="rule-source-pattern">
                              {pattern}
                            </Tag>
                          ))}
                        </Space>
                      ) : (
                        "-"
                      ),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </div>
  );
}
