import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Input, Segmented, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Link } from "react-router-dom";
import { api, type KpiClassificationCluePageV4, type KpiClassificationClueV4, type KpiClueStatusV4 } from "../api/http";
import { KpiMetricCatalogProvider, KpiMetricName, useKpiMetricCatalog } from "./KpiMetricSelect";
import { hasActionableKpiClassificationClues } from "./kpiClassificationCluesModel";
import { formatKpiMetricNames } from "./kpiMetricCatalogModel";

const STATUS_KEYS: KpiClueStatusV4[] = [
  "unclassified",
  "classified",
  "unregistered",
  "ambiguous",
  "reserved",
];

const STATUS_LABELS: Record<KpiClueStatusV4, string> = {
  unclassified: "待分类",
  classified: "已分类",
  unregistered: "未注册",
  ambiguous: "歧义",
  reserved: "预留",
};

const STATUS_COLORS: Record<KpiClueStatusV4, string> = {
  unclassified: "orange",
  classified: "green",
  unregistered: "red",
  ambiguous: "purple",
  reserved: "default",
};

function KpiClassificationClueContent({ taskId }: { taskId: string }) {
  const [pageData, setPageData] = useState<KpiClassificationCluePageV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [clueStatus, setClueStatus] = useState<KpiClueStatusV4>("unclassified");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const { metrics, metricIndex } = useKpiMetricCatalog();

  const summary: Partial<Record<KpiClueStatusV4, number>> = pageData?.summary ?? {};
  const actionableCount = (summary["unclassified"] ?? 0) + (summary["unregistered"] ?? 0) + (summary["ambiguous"] ?? 0);

  const load = useCallback(
    async (
      nextPage = page,
      nextPageSize = pageSize,
      nextStatus = clueStatus,
      nextSearch = search,
    ) => {
      setLoading(true);
      try {
        setPageData(
          await api.listKpiClassificationCluesV4(taskId, {
            clue_status: nextStatus,
            search: nextSearch || undefined,
            page: nextPage,
            page_size: nextPageSize,
          }),
        );
      } finally {
        setLoading(false);
      }
    },
    [clueStatus, page, pageSize, search, taskId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<KpiClassificationClueV4> = [
    {
      title: "源名称",
      dataIndex: "source_name",
      width: 360,
      ellipsis: { showTitle: true },
      render: (value: string, record) => (
        <Space size={8}>
          <span>{value}</span>
          <Tag color={STATUS_COLORS[record.clue_status]}>{STATUS_LABELS[record.clue_status]}</Tag>
        </Space>
      ),
    },
    {
      title: "匹配指标",
      dataIndex: "metric_key",
      width: 220,
      render: (value, record) => {
        if (value) return <KpiMetricName metricKey={value} />;
        if (record.candidates?.length) {
          const candidateNames = formatKpiMetricNames(
            record.candidates.slice(0, 3).map((candidate) => candidate.metric_key),
            metrics,
            metricIndex,
          );
          return (
            <Space wrap size={4}>
              {record.candidates.slice(0, 3).map((candidate, index) => (
                <Tag key={candidate.metric_key}>
                  <div>{candidateNames[index]}</div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {candidate.metric_key}
                  </Typography.Text>
                </Tag>
              ))}
            </Space>
          );
        }
        return "-";
      },
    },
    { title: "业务域", dataIndex: "domain", width: 100 },
    { title: "规则", dataIndex: "rule_code", width: 160, ellipsis: true },
    { title: "记录数", dataIndex: "record_count", width: 90 },
    {
      title: "来源文件",
      dataIndex: "source_files",
      render: (values: string[]) => values.join("；"),
      ellipsis: true,
    },
    {
      title: "操作",
      key: "actions",
      width: 120,
      render: (_, record) => {
        if (record.clue_status !== "unclassified" && record.clue_status !== "ambiguous") return null;
        const searchKey = record.metric_key ?? record.candidates?.[0]?.metric_key ?? record.source_name;
        return (
          <Link to={`/kpi-resources?search=${encodeURIComponent(searchKey)}`}>
            <Button size="small" type="link">去分类</Button>
          </Link>
        );
      },
    },
  ];

  if (!pageData || !hasActionableKpiClassificationClues(summary)) return null;

  return (
    <Card
      title="KPI 按需分类线索"
      extra={
        <Space wrap>
          <Segmented
            value={clueStatus}
            options={STATUS_KEYS.map((key) => ({
              value: key,
              label: `${STATUS_LABELS[key]} (${summary[key] ?? 0})`,
            }))}
            onChange={(value) => {
              const nextStatus = value as KpiClueStatusV4;
              setClueStatus(nextStatus);
              setPage(1);
              void load(1, pageSize, nextStatus, search);
            }}
          />
          <Input.Search
            allowClear
            placeholder="搜索源名称 / 指标"
            style={{ width: 240 }}
            onSearch={(value) => {
              setSearch(value);
              setPage(1);
              void load(1, pageSize, clueStatus, value);
            }}
          />
        </Space>
      }
      styles={{ body: { paddingTop: 8 } }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="线索仅辅助分类，不改变规则结果"
        description="完成分类和动态配置后，请在任务详情手动重跑受影响的 KPI 规则。"
      />
      {actionableCount > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${actionableCount} 个指标待处理`}
          description={`待分类 ${summary["unclassified"] ?? 0} · 未注册 ${summary["unregistered"] ?? 0} · 歧义 ${summary["ambiguous"] ?? 0}`}
        />
      )}
      <Table
        rowKey="source_name"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={pageData?.items ?? []}
        pagination={{
          current: pageData?.page ?? page,
          pageSize: pageData?.page_size ?? pageSize,
          total: pageData?.total ?? 0,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
            void load(nextPage, nextPageSize, clueStatus, search);
          },
        }}
      />
    </Card>
  );
}

export function KpiClassificationClues({ taskId }: { taskId: string }) {
  return (
    <KpiMetricCatalogProvider>
      <KpiClassificationClueContent taskId={taskId} />
    </KpiMetricCatalogProvider>
  );
}
