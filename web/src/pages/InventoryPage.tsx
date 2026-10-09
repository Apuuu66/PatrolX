import { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Flex,
  Input,
  Pagination,
  Popconfirm,
  Space,
  Select,
  Tabs,
  Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  api,
  type InventoryDevice,
  type InventoryQualityIssue,
  type InventoryQualityIssueType } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { Table } from "../components/ResizableTable";

/** 数据分页默认 10 条（contracts/ui-baseline §4.4）。 */
const DEFAULT_PAGE_SIZE = 10;

const QUALITY_LABELS: Record<
  InventoryQualityIssueType,
  { label: string; color: string }
> = {
  missing_site: { label: "缺少局点", color: "red" },
  missing_device_identity: { label: "缺少设备身份", color: "red" },
  missing_version: { label: "版本缺失", color: "orange" },
  version_conflict: { label: "版本冲突", color: "red" },
  device_identity_conflict: { label: "设备身份冲突", color: "red" },
  site_ownership_change: { label: "局点归属变化", color: "orange" } };

function formatTime(value?: string | null) {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "-";
}

const deviceColumns = [
  {
    title: "设备名称",
    dataIndex: "device_name",
    key: "device_name",
    ellipsis: true },
  { title: "省份", dataIndex: "province", key: "province", width: 110 },
  { title: "运营商", dataIndex: "operator", key: "operator", width: 110 },
  {
    title: "当前局点",
    dataIndex: "site_key",
    key: "site_key",
    width: 220,
    render: (value: string) => <Tag>{value}</Tag> },
  {
    title: "当前版本",
    dataIndex: "current_version",
    key: "current_version",
    width: 170,
    render: (value: string | null) => value || <Tag color="orange">缺失</Tag> },
  {
    title: "最近观测",
    dataIndex: "last_seen_at",
    key: "last_seen_at",
    width: 170,
    render: formatTime },
  {
    title: "观测次数",
    dataIndex: "observation_count",
    key: "observation_count",
    width: 100,
    align: "right" as const },
  {
    title: "质量",
    key: "quality",
    width: 190,
    render: (_: unknown, record: InventoryDevice) => {
      const types = record.quality_issue_types ?? [];
      if (
        record.has_site_conflict &&
        !types.includes("site_ownership_change")
      ) {
        types.push("site_ownership_change");
      }
      if (
        record.current_version === null &&
        !types.includes("missing_version")
      ) {
        types.push("missing_version");
      }
      return (
        <Flex gap={4} wrap="wrap">
          {types.map((item) => (
            <Tag key={item} color={QUALITY_LABELS[item].color}>
              {QUALITY_LABELS[item].label}
            </Tag>
          ))}
        </Flex>
      );
    } },
];

const qualityColumns = [
  {
    title: "类型",
    dataIndex: "issue_type",
    key: "issue_type",
    width: 150,
    render: (value: InventoryQualityIssueType) => (
      <Tag color={QUALITY_LABELS[value].color}>
        {QUALITY_LABELS[value].label}
      </Tag>
    ) },
  { title: "描述", dataIndex: "message", key: "message", ellipsis: true },
  {
    title: "省份",
    dataIndex: "province",
    key: "province",
    width: 100,
    render: (value?: string | null) => value || "-" },
  {
    title: "运营商",
    dataIndex: "operator",
    key: "operator",
    width: 100,
    render: (value?: string | null) => value || "-" },
  {
    title: "发现时间",
    dataIndex: "detected_at",
    key: "detected_at",
    width: 170,
    render: formatTime },
  {
    title: "追溯",
    key: "links",
    width: 150,
    render: (_: unknown, record: InventoryQualityIssue) => (
      <Space size={4} wrap>
        {record.task_id && (
          <Button type="link" size="small" href={`/tasks/${record.task_id}`}>
            任务
          </Button>
        )}
        {record.device_id && (
          <Button
            type="link"
            size="small"
            href={`/inventory/devices/${record.device_id}`}
          >
            设备
          </Button>
        )}
      </Space>
    ) },
];

export function InventoryPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<"devices" | "quality">("devices");
  const [province, setProvince] = useState("");
  const [operator, setOperator] = useState("");
  const [issueType, setIssueType] = useState<InventoryQualityIssueType | "">(
    "",
  );

  const [devices, setDevices] = useState<InventoryDevice[]>([]);
  const [deviceTotal, setDeviceTotal] = useState(0);
  const [devicePage, setDevicePage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [issues, setIssues] = useState<InventoryQualityIssue[]>([]);
  const [issueTotal, setIssueTotal] = useState(0);
  const [issuePage, setIssuePage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const hasDeviceFilters = Boolean(province || operator);
  const hasIssueFilters = Boolean(issueType || province || operator);

  const clearFilters = () => {
    setProvince("");
    setOperator("");
    setIssueType("");
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === "devices") {
        const data = await api.listInventoryDevices({
          page: devicePage,
          page_size: pageSize,
          province: province || undefined,
          operator: operator || undefined,
          quality_status: "all" });
        setDevices(data.items);
        setDeviceTotal(data.total);
      } else {
        const data = await api.listInventoryQualityIssues({
          page: issuePage,
          page_size: pageSize,
          issue_type: issueType || undefined,
          province: province || undefined,
          operator: operator || undefined });
        setIssues(data.items);
        setIssueTotal(data.total);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "台账加载失败");
    } finally {
      setLoading(false);
    }
  }, [devicePage, issuePage, issueType, operator, pageSize, province, tab]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setDevicePage(1);
    setIssuePage(1);
  }, [province, operator, tab]);

  const handleDeleteDevice = async (record: InventoryDevice) => {
    setDeletingId(record.device_id);
    try {
      await api.deleteInventoryDevice(record.device_id);
      message.success("设备台账已删除");
      if (devices.length === 1 && devicePage > 1) {
        setDevicePage(devicePage - 1);
      } else {
        await load();
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除设备失败");
    } finally {
      setDeletingId(null);
    }
  };

  const deviceColumnsWithActions = isAdmin
    ? [
        ...deviceColumns,
        {
          title: "操作",
          key: "actions",
          width: 100,
          fixed: "right" as const,
          render: (_: unknown, record: InventoryDevice) => (
            <span onClick={(event) => event.stopPropagation()}>
              <Popconfirm
                title="确认删除该设备台账？"
                description="将物理删除设备、全部观测记录和版本历史。"
                okText="删除"
                okButtonProps={{
                  danger: true,
                  loading: deletingId === record.device_id } }
                cancelText="取消"
                onConfirm={() => void handleDeleteDevice(record)}
              >
                <Button
                  type="link"
                  size="small"
                  danger
                  loading={deletingId === record.device_id}
                >
                  删除
                </Button>
              </Popconfirm>
            </span>
          ) },
      ]
    : deviceColumns;

  return (
    <Flex vertical gap={16}>
      <PageHeader
        title="设备台账"
        description="按任务观测持续汇总设备资产和版本路径"
        actions={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void load()}
            loading={loading}
          >
            刷新
          </Button>
        }
      />

      {error && (
        <LoadErrorState
          description={error}
          onRetry={() => void load()}
          retrying={loading}
        />
      )}

      <Card styles={{ body: { paddingTop: 16 } }}>
        <Tabs
          activeKey={tab}
          onChange={(key) => setTab(key as "devices" | "quality")}
          items={[
            {
              key: "devices",
              label: "设备台账",
              children: (
                <Flex vertical gap={16}>
                  <Flex justify="space-between" wrap="wrap" gap={12}>
                    <Space wrap>
                      <Input
                        allowClear
                        placeholder="按省份筛选"
                        prefix="省份"
                        style={{ width: 180 }}
                        value={province}
                        onChange={(event) => setProvince(event.target.value)}
                      />
                      <Input
                        allowClear
                        placeholder="按运营商筛选"
                        prefix="运营商"
                        style={{ width: 180 }}
                        value={operator}
                        onChange={(event) => setOperator(event.target.value)}
                      />
                    </Space>
                  </Flex>
                  {loading && devices.length === 0 ? (
                    <PageSkeleton rows={5} />
                  ) : devices.length === 0 && !error ? (
                    <EmptyState
                      description={
                        hasDeviceFilters ? "没有符合筛选条件的设备" : "暂无设备观测"
                      }
                      action={
                        hasDeviceFilters ? (
                          <Button onClick={clearFilters}>清空筛选</Button>
                        ) : (
                          <Button type="primary" onClick={() => navigate("/tasks")}>
                            去上传数据包
                          </Button>
                        )
                      }
                    />
                  ) : (
                    <Table
                      rowKey="device_id"
                      columns={deviceColumnsWithActions}
                      dataSource={devices}
                      loading={loading}
                      pagination={false}
                      scroll={{ x: isAdmin ? 1260 : 1160 }}
                      onRow={(record) => ({
                        onClick: () =>
                          navigate(`/inventory/devices/${record.device_id}`),
                        style: { cursor: "pointer" } })}
                    />
                  )}
                  <Flex justify="flex-end">
                    <Pagination
                      current={devicePage}
                      pageSize={pageSize}
                      total={deviceTotal}
                      showSizeChanger
                      showTotal={(value) => `共 ${value} 台设备`}
                      onChange={(page, size) => {
                        setDevicePage(page);
                        setPageSize(size);
                      }}
                    />
                  </Flex>
                </Flex>
              ) },
            {
              key: "quality",
              label: "质量问题",
              children: (
                <Flex vertical gap={16}>
                  <Space wrap>
                    <Select
                      allowClear
                      placeholder="按类型筛选"
                      style={{ width: 180 }}
                      value={issueType || undefined}
                      options={(
                        Object.keys(
                          QUALITY_LABELS,
                        ) as InventoryQualityIssueType[]
                      ).map((item) => ({
                        value: item,
                        label: QUALITY_LABELS[item].label }))}
                      onChange={(value) => setIssueType(value ?? "")}
                    />
                    <Input
                      allowClear
                      placeholder="按省份筛选"
                      prefix="省份"
                      style={{ width: 180 }}
                      value={province}
                      onChange={(event) => setProvince(event.target.value)}
                    />
                    <Input
                      allowClear
                      placeholder="按运营商筛选"
                      prefix="运营商"
                      style={{ width: 180 }}
                      value={operator}
                      onChange={(event) => setOperator(event.target.value)}
                    />
                  </Space>
                  {loading && issues.length === 0 ? (
                    <PageSkeleton rows={5} />
                  ) : issues.length === 0 && !error ? (
                    <EmptyState
                      description={
                        hasIssueFilters ? "没有符合筛选条件的质量问题" : "暂无质量问题"
                      }
                      action={
                        hasIssueFilters ? (
                          <Button onClick={clearFilters}>清空筛选</Button>
                        ) : (
                          <Button type="primary" onClick={() => navigate("/tasks")}>
                            去上传数据包
                          </Button>
                        )
                      }
                    />
                  ) : (
                    <Table
                      rowKey="issue_id"
                      columns={qualityColumns}
                      dataSource={issues}
                      loading={loading}
                      pagination={false}
                      scroll={{ x: 980 }}
                    />
                  )}
                  <Flex justify="flex-end">
                    <Pagination
                      current={issuePage}
                      pageSize={pageSize}
                      total={issueTotal}
                      showSizeChanger
                      showTotal={(value) => `共 ${value} 条质量问题`}
                      onChange={(page, size) => {
                        setIssuePage(page);
                        setPageSize(size);
                      }}
                    />
                  </Flex>
                </Flex>
              ) },
          ]}
        />
      </Card>

    </Flex>
  );
}
