import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Flex,
  Input,
  Pagination,
  Space,
  Select,
  Tabs,
  Tag,
  Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  api,
  type InventoryDevice,
  type InventoryQualityIssue,
  type InventoryQualityIssueType } from "../api/http";
import { EmptyState, PageSkeleton } from "../components/PageState";
import { Table } from "../components/ResizableTable";

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
  const [tab, setTab] = useState<"devices" | "quality">("devices");
  const [province, setProvince] = useState("");
  const [operator, setOperator] = useState("");
  const [issueType, setIssueType] = useState<InventoryQualityIssueType | "">(
    "",
  );

  const [devices, setDevices] = useState<InventoryDevice[]>([]);
  const [deviceTotal, setDeviceTotal] = useState(0);
  const [devicePage, setDevicePage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [issues, setIssues] = useState<InventoryQualityIssue[]>([]);
  const [issueTotal, setIssueTotal] = useState(0);
  const [issuePage, setIssuePage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <Flex vertical gap={16}>
      <Flex align="center" justify="space-between">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            设备台账
          </Typography.Title>
          <Typography.Text type="secondary">
            按任务观测持续汇总设备资产和版本路径
          </Typography.Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void load()}
          loading={loading}
        >
          刷新
        </Button>
      </Flex>

      {error && <Alert type="error" showIcon message={error} />}

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
                    <EmptyState description="暂无设备观测" />
                  ) : (
                    <Table
                      rowKey="device_id"
                      columns={deviceColumns}
                      dataSource={devices}
                      loading={loading}
                      pagination={false}
                      scroll={{ x: 1160 }}
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
                    <EmptyState description="暂无质量问题" />
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
