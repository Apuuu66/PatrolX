import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Input, Select, Space, Tag, Typography, Upload } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { api, type KpiResourceMetricPage } from "../api/http";
import { KpiResourceTable } from "../components/KpiResourceTable";
import { RESOURCE_DOMAIN_LABELS, type ResourceDomain } from "../components/kpiResourceModel";

const DOMAIN_OPTIONS = (Object.keys(RESOURCE_DOMAIN_LABELS) as ResourceDomain[]).map((value) => ({
  value,
  label: RESOURCE_DOMAIN_LABELS[value],
}));

const CLASSIFICATION_OPTIONS = DOMAIN_OPTIONS.filter((item) => item.value !== "unclassified");

export function KpiResourcesPage() {
  const { message } = App.useApp();
  const [pageData, setPageData] = useState<KpiResourceMetricPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState<ResourceDomain | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [targetDomain, setTargetDomain] = useState<Exclude<ResourceDomain, "unclassified"> | undefined>();
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(
    async (nextPage = page, nextPageSize = pageSize, nextSearch = search, nextDomain = domain) => {
      setLoading(true);
      try {
        const data = await api.listKpiResourceMetrics({
          search: nextSearch || undefined,
          domain: nextDomain,
          page: nextPage,
          page_size: nextPageSize,
        });
        setPageData(data);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "指标加载失败");
      } finally {
        setLoading(false);
      }
    },
    [domain, message, page, pageSize, search],
  );

  useEffect(() => {
    void load();
    // 页面初始化只需要加载一次，后续由搜索和分页显式触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = (revision?: number) => {
    void load(1, pageSize, search, domain);
    setSelectedKeys([]);
    return revision;
  };

  const handleSearch = (value: string) => {
    setSearch(value);
    setPage(1);
    void load(1, pageSize, value, domain);
  };

  const handleDomainChange = (value: ResourceDomain | undefined) => {
    setDomain(value);
    setPage(1);
    void load(1, pageSize, search, value);
  };

  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    setPage(nextPage);
    setPageSize(nextPageSize);
    void load(nextPage, nextPageSize, search, domain);
  };

  const handleImport = async (file: File) => {
    try {
      const report = await api.importKpiResourceMetrics(file);
      message.success(
        `导入完成：新增 ${report.summary.new_metrics}，更新 ${report.summary.updated_metrics}，无效 ${report.summary.invalid_rows}`,
      );
      setSelectedKeys([]);
      void load(1, pageSize, search, domain);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "资源 CSV 导入失败");
    }
    return false;
  };

  const handleClassify = async () => {
    if (!pageData || !targetDomain || selectedKeys.length === 0) return;
    setSubmitting(true);
    try {
      const result = await api.classifyKpiResourceMetrics({
        metric_keys: selectedKeys,
        domain: targetDomain,
        expected_revision: pageData.revision,
      });
      message.success(`已分类 ${result.metric_keys.length} 个指标到 ${RESOURCE_DOMAIN_LABELS[result.domain]}`);
      refresh(result.revision);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "分类失败");
    } finally {
      setSubmitting(false);
    }
  };

  const summary = pageData?.summary;

  return (
    <Card
      title={<Typography.Text strong>KPI 指标库</Typography.Text>}
      extra={
        <Space wrap>
          <Upload accept=".csv,text/csv" beforeUpload={handleImport} showUploadList={false}>
            <Button icon={<UploadOutlined />}>导入资源 CSV</Button>
          </Upload>
        </Space>
      }
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          {summary &&
            (Object.keys(RESOURCE_DOMAIN_LABELS) as ResourceDomain[]).map((key) => (
              <Tag key={key}>
                {RESOURCE_DOMAIN_LABELS[key]}: {summary[key]}
              </Tag>
            ))}
        </Space>
        <Space wrap>
          <Input.Search
            placeholder="搜索资源 ID / 中文名 / 英文名"
            allowClear
            style={{ width: 280 }}
            onSearch={handleSearch}
          />
          <Select
            allowClear
            placeholder="业务域"
            style={{ width: 140 }}
            options={DOMAIN_OPTIONS}
            value={domain}
            onChange={handleDomainChange}
          />
          <Select
            allowClear
            placeholder="分类到"
            style={{ width: 140 }}
            options={CLASSIFICATION_OPTIONS}
            value={targetDomain}
            onChange={setTargetDomain}
          />
          <Button type="primary" disabled={!targetDomain || selectedKeys.length === 0} loading={submitting} onClick={handleClassify}>
            批量分类（{selectedKeys.length}）
          </Button>
        </Space>
        <KpiResourceTable
          items={pageData?.items ?? []}
          total={pageData?.total ?? 0}
          page={pageData?.page ?? page}
          pageSize={pageData?.page_size ?? pageSize}
          loading={loading}
          selectedKeys={selectedKeys}
          onSelectedKeysChange={setSelectedKeys}
          onPageChange={handlePageChange}
        />
      </Space>
    </Card>
  );
}
