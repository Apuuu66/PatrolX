import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
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
import type { AlarmActiveMetadata } from "../components/AlarmActiveStatePanel";
import type { AlarmFlappingMetadata } from "../components/AlarmFlappingPanel";
import type { AlarmRecurrenceMetadata } from "../components/AlarmRecurrencePanel";
import { CopyTextButton } from "../components/CopyTextButton";
import { getStatusTextColor } from "../utils/statusTextColors";
import { PageHeader } from "../components/PageHeader";
import { FindingItem } from "../components/FindingItem";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { RuleStatusTag, SeverityTag } from "../components/StatusBadge";
import { RESULT_STATUS_META } from "../components/statusLabels";
import { getRuleCategoryLabel } from "../utils/ruleCategories";

/** 重跑状态轮询间隔与上限（FR-023）。 */
const RERUN_POLL_INTERVAL_MS = 1500;
const RERUN_POLL_TIMEOUT_MS = 120_000;

const AlarmActiveStatePanel = lazy(() =>
  import("../components/AlarmActiveStatePanel").then((module) => ({ default: module.AlarmActiveStatePanel })),
);
const AlarmFlappingPanel = lazy(() =>
  import("../components/AlarmFlappingPanel").then((module) => ({ default: module.AlarmFlappingPanel })),
);
const AlarmRecurrencePanel = lazy(() =>
  import("../components/AlarmRecurrencePanel").then((module) => ({ default: module.AlarmRecurrencePanel })),
);
const MetricPanel = lazy(() =>
  import("../components/MetricPanel").then((module) => ({ default: module.MetricPanel })),
);

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
  const isHistorical = meta === null;

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
    if (rerunning || isHistorical) return;
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
  }, [isHistorical, message, refreshResult, rerunning, result, ruleCode, taskId]);

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
  const alarmActive = (result.metadata ?? {})["alarm_active"] as AlarmActiveMetadata | undefined;
  const alarmRecurrence = (result.metadata ?? {})["alarm_recurrence"] as AlarmRecurrenceMetadata | undefined;
  const alarmFlapping = (result.metadata ?? {})["alarm_flapping"] as AlarmFlappingMetadata | undefined;
  const hasEvidence =
    Boolean(alarmActive) || Boolean(alarmRecurrence) || Boolean(alarmFlapping) || metrics.length > 0;

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

      {isHistorical && (
        <Alert
          className="rule-offline-banner"
          data-testid="rule-offline-banner"
          type="warning"
          showIcon
          message="该规则已下线，仅供历史查看"
          description="该规则已不在当前活动规则库中；历史结果不可重跑或重建。"
        />
      )}

      {/* 结论 + 建议（FR-020）：状态、严重度、结论摘要、处理建议与重跑入口都在首屏。 */}
      <Card className="conclusion-hero rule-detail-panel" data-testid="rule-section-conclusion">
        <PageHeader
          title={<span title={result.name}>{result.name}</span>}
          description={`规则编码：${result.code}`}
          status={
            <Space size={8} wrap>
              <RuleStatusTag status={result.status} skipReason={result.skip_reason} />
              <SeverityTag severity={result.severity} variant="plain" />
            </Space>
          }
          actions={
            <Button
              icon={<RedoOutlined />}
              loading={rerunning}
              disabled={rerunning || isHistorical}
              onClick={() => void rerun()}
            >
              {rerunning ? "重跑中…" : "重跑本规则"}
            </Button>
          }
        />
        <div className="conclusion-hero-body">
          <div className="conclusion-hero-conclusion">
            <span
              className="conclusion-hero-tag"
              data-status={result.status}
              style={{ color: getStatusTextColor(result.status, "#595959") }}
            >
              <span aria-hidden="true" className="conclusion-hero-tag-dot" style={{ background: statusColor }} />
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
          {/* 源文件匹配降级为一行等宽元数据，不再独占区块（FR-015、R9、SC-005）。 */}
          <div className="rule-detail-source-patterns" data-testid="rule-section-source-patterns">
            <Typography.Text type="secondary" className="rule-detail-source-patterns-label">
              源文件匹配
            </Typography.Text>
            {sourcePatterns.length > 0 ? (
              <span className="rule-detail-source-patterns-value">
                <code title={sourcePatterns.join(" ")}>{sourcePatterns.join(" ")}</code>
                <CopyTextButton text={sourcePatterns.join(" ")} label="源文件匹配" />
              </span>
            ) : (
              <Typography.Text type="secondary">该规则未声明源文件匹配范围</Typography.Text>
            )}
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
                <FindingItem finding={finding} />
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
            {alarmActive && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  未清除告警
                </Typography.Text>
                <Suspense fallback={<Card size="small" loading />}>
                  <AlarmActiveStatePanel metadata={alarmActive} showAllColumns={showAllColumns} />
                </Suspense>
              </section>
            )}
            {alarmRecurrence && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  告警反复上报
                </Typography.Text>
                <Suspense fallback={<Card size="small" loading />}>
                  <AlarmRecurrencePanel
                    metadata={alarmRecurrence}
                    metrics={result.metrics}
                    showAllColumns={showAllColumns}
                  />
                </Suspense>
              </section>
            )}
            {alarmFlapping && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  告警生命周期分组
                </Typography.Text>
                <Suspense fallback={<Card size="small" loading />}>
                  <AlarmFlappingPanel metadata={alarmFlapping} showAllColumns={showAllColumns} />
                </Suspense>
              </section>
            )}
            {metrics.length > 0 && (
              <section className="rule-evidence-section">
                <Typography.Text strong className="rule-evidence-title">
                  指标
                </Typography.Text>
                <Suspense fallback={<Card size="small" loading />}>
                  <MetricPanel metrics={metrics} showAllColumns={showAllColumns} />
                </Suspense>
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
