import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Select, Space, Spin, Table, Typography } from "antd";

import { api } from "../api/http";
import type { KpiCatalogItem } from "./kpiCatalogModel";
import {
  buildKpiRecordQuery,
  getKpiRecordPageInfo,
  getKpiRecordRows,
  type KpiRecordFilters,
  type KpiRecordPage,
  type KpiRecordRow,
} from "./kpiRecordTableModel";

interface Props {
  taskId: string;
  ruleCode: string;
  item: KpiCatalogItem;
  sourceFiles: string[];
}

export function KpiRecordTable({ taskId, ruleCode, item, sourceFiles }: Props) {
  const [filters, setFilters] = useState<KpiRecordFilters>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [pageData, setPageData] = useState<KpiRecordPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const metricKey = item.definition.key;
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = buildKpiRecordQuery(metricKey, filters, page, pageSize);
      const data = await api.listKpiRecords(taskId, ruleCode, query);
      setPageData(data);
    } catch (err) {
      setPageData(null);
      setError(err instanceof Error ? err.message : "记录加载失败");
    } finally {
      setLoading(false);
    }
  }, [filters, metricKey, page, pageSize, ruleCode, taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [filters, pageSize]);

  const rows = useMemo(() => getKpiRecordRows(pageData?.items ?? []), [pageData]);

  const fileOptions = useMemo(
    () => sourceFiles.map((file) => ({ value: file, label: file })),
    [sourceFiles],
  );

  if (loading && !pageData) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <Spin />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message="原始记录加载失败"
        description={error}
        action={<Button size="small" onClick={() => void load()}>重试</Button>}
      />
    );
  }

  if (!pageData || pageData.total === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的原始记录" />;
  }

  return (
    <div>
      <Space wrap>
        <Select
          allowClear
          placeholder="来源文件"
          style={{ width: 240 }}
          value={filters.sourceFile}
          options={fileOptions}
          onChange={(value) => setFilters((current) => ({ ...current, sourceFile: value }))}
        />
        <Select
          allowClear
          placeholder="周期"
          style={{ width: 110 }}
          value={filters.periodMinutes}
          options={[5, 15, 30, 60].map((value) => ({ value, label: `${value} 分钟` }))}
          onChange={(value) => setFilters((current) => ({ ...current, periodMinutes: value }))}
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 110 }}
          value={filters.status}
          options={[
            { value: "pass", label: "通过" },
            { value: "warn", label: "告警" },
            { value: "fail", label: "失败" },
            { value: "neutral", label: "中性" },
            { value: "unavailable", label: "不可用" },
          ]}
          onChange={(value) => setFilters((current) => ({ ...current, status: value }))}
        />
      </Space>

      <Table
        size="small"
        style={{ marginTop: 12 }}
        loading={loading}
        rowKey="id"
        dataSource={rows}
        pagination={{
          current: pageData.page,
          pageSize: pageData.page_size,
          total: pageData.total,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100, 200],
          showTotal: () => getKpiRecordPageInfo(pageData),
          onChange: (nextPage, nextSize) => {
            setPage(nextPage);
            setPageSize(nextSize);
          },
        }}
        columns={[
          {
            title: "指标",
            dataIndex: "metricName",
            width: 150,
            render: (value: string) => (
              <Typography.Text style={{ whiteSpace: "normal" }}>{value}</Typography.Text>
            ),
          },
          { title: "值", dataIndex: "valueText", width: 70 },
          { title: "状态", dataIndex: "statusLabel", width: 70 },
          {
            title: "时间",
            dataIndex: "startTimeText",
            width: 170,
            render: (_, record: KpiRecordRow) => (
              <div style={{ whiteSpace: "normal" }}>
                <div>{record.startTimeText}</div>
                <div>{record.endTimeText}</div>
              </div>
            ),
          },
          { title: "来源", dataIndex: "sourceFile", ellipsis: true },
          { title: "行号", dataIndex: "lineNumber", width: 60 },
          { title: "错误", dataIndex: "errorsText", ellipsis: true },
        ]}
      />
    </div>
  );
}
