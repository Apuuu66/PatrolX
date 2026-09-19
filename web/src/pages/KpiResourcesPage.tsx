import { useCallback, useEffect, useState } from "react";
import { Alert, App, Button, Card, Descriptions, Input, Select, Space, Table, Tabs, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useSearchParams } from "react-router-dom";
import {
  api,
  type KpiClassificationAudit,
  type KpiResourceMetricPage,
} from "../api/http";
import { KpiResourceTable } from "../components/KpiResourceTable";
import { RESOURCE_DOMAIN_LABELS, type ResourceDomain } from "../components/kpiResourceModel";
import { KpiFormulaEditor } from "../components/KpiFormulaEditor";
import { KpiThresholdEditor } from "../components/KpiThresholdEditor";
import { KpiMetricCatalogProvider } from "../components/KpiMetricSelect";
import {
  KpiCapacityRuleEditor,
  KpiCommonConfigEditor,
  KpiConfigAuditTable,
  KpiDisplayRuleEditor,
} from "../components/KpiOperationalConfig";

const DOMAIN_OPTIONS = (Object.keys(RESOURCE_DOMAIN_LABELS) as ResourceDomain[]).map((value) => ({
  value,
  label: RESOURCE_DOMAIN_LABELS[value],
}));

export function KpiResourcesPage() {
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const [pageData, setPageData] = useState<KpiResourceMetricPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [domain, setDomain] = useState<ResourceDomain | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [targetDomain, setTargetDomain] = useState<ResourceDomain>();
  const [operator, setOperator] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [audits, setAudits] = useState<KpiClassificationAudit[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(10);
  const [auditLoading, setAuditLoading] = useState(true);

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

  const loadAudits = useCallback(
    async (nextPage = auditPage, nextPageSize = auditPageSize) => {
      setAuditLoading(true);
      try {
        const data = await api.listKpiClassificationAudits({
          page: nextPage,
          page_size: nextPageSize,
        });
        setAudits(data.items);
        setAuditTotal(data.total);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "审计加载失败");
      } finally {
        setAuditLoading(false);
      }
    },
    [auditPage, auditPageSize, message],
  );

  useEffect(() => {
    void load();
    // 页面初始化只需要加载一次，后续由搜索和分页显式触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadAudits();
  }, [loadAudits]);

  const refresh = () => {
    void load(1, pageSize, search, domain);
    void loadAudits(1, auditPageSize);
    setAuditPage(1);
    setSelectedKeys([]);
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

  const handleAuditPageChange = (nextPage: number, nextPageSize: number) => {
    setAuditPage(nextPage);
    setAuditPageSize(nextPageSize);
    void loadAudits(nextPage, nextPageSize);
  };

  const handleClassify = async () => {
    const normalizedOperator = operator.trim();
    if (!normalizedOperator) {
      message.warning("请输入操作人");
      return;
    }
    if (!pageData || !targetDomain || selectedKeys.length === 0) return;
    setSubmitting(true);
    try {
      const result = await api.classifyKpiResourceMetrics({
        metric_keys: selectedKeys,
        domain: targetDomain,
        operator: normalizedOperator,
      });
      message.success(`已分类 ${result.metric_keys.length} 个指标`);
      refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "分类失败");
    } finally {
      setSubmitting(false);
    }
  };

  const auditColumns: ColumnsType<KpiClassificationAudit> = [
    { title: "指标 Key", dataIndex: "metric_key", width: 180, ellipsis: true },
    { title: "操作", dataIndex: "operation", width: 100 },
    { title: "操作人", dataIndex: "operator", width: 120 },
    { title: "原业务域", dataIndex: "from_domain", width: 110 },
    { title: "新业务域", dataIndex: "to_domain", width: 110 },
    {
      title: "操作时间",
      dataIndex: "operated_at",
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
  ];

  const summary = pageData?.summary;

  return (
    <KpiMetricCatalogProvider>
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title={<strong>基础指标配置</strong>}>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {pageData && (
            <Descriptions
              size="small"
              column={3}
              items={[{ key: "total", label: "指标总数", children: pageData.total }]}
            />
          )}
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
              options={DOMAIN_OPTIONS}
              value={targetDomain}
              onChange={setTargetDomain}
            />
            <Input
              placeholder="操作人"
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              style={{ width: 140 }}
            />
            <Button
              type="primary"
              disabled={!targetDomain || selectedKeys.length === 0}
              loading={submitting}
              onClick={handleClassify}
            >
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
      <Card title="分类审计" styles={{ body: { paddingTop: 8 } }}>
        <Table
          rowKey="id"
          size="small"
          loading={auditLoading}
          columns={auditColumns}
          dataSource={audits}
          pagination={{
            current: auditPage,
            pageSize: auditPageSize,
            total: auditTotal,
            showSizeChanger: true,
            showTotal: (value) => `共 ${value} 条`,
            onChange: handleAuditPageChange,
          }}
        />
      </Card>

      {!operator.trim() ? (
        <Alert
          type="warning"
          showIcon
          message="动态口径配置需要在上方输入操作人"
          description="操作人用于配置审计追溯。输入后即可维护指标公式、阈值、容量规则、展示规则和公共配置。"
        />
      ) : (
        <Tabs
          defaultActiveKey="formula"
          items={[
            {
              key: "formula",
              label: "指标公式",
              children: <KpiFormulaEditor operator={operator.trim()} />,
            },
            {
              key: "thresholds",
              label: "阈值",
              children: <KpiThresholdEditor operator={operator.trim()} />,
            },
            {
              key: "rules",
              label: "容量与展示",
              children: (
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <KpiCapacityRuleEditor operator={operator.trim()} />
                  <KpiDisplayRuleEditor operator={operator.trim()} />
                </Space>
              ),
            },
            {
              key: "common",
              label: "公共配置",
              children: <KpiCommonConfigEditor operator={operator.trim()} />,
            },
            {
              key: "audits",
              label: "配置审计",
              children: <KpiConfigAuditTable />,
            },
          ]}
        />
      )}
    </Space>
    </KpiMetricCatalogProvider>
  );
}
