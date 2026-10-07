import { useCallback, useEffect, useState } from "react";
import { Alert, App, Button, Card, Descriptions, Flex, Pagination, Popconfirm, Tag, Typography } from "antd";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  api,
  type InventoryObservation,
  type InventoryVersionPoint } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageSkeleton } from "../components/PageState";
import { Table } from "../components/ResizableTable";

const DIRECTION_META = {
  upgrade: { label: "升级", color: "green" },
  downgrade: { label: "降级", color: "red" },
  unchanged: { label: "未变化", color: "default" } } as const;

const VERSION_STATUS_META = {
  missing: { label: "版本缺失", color: "orange" },
  conflict: { label: "版本冲突", color: "red" },
  error: { label: "版本解析失败", color: "red" },
  not_applicable: { label: "不适用", color: "blue" } } as const;

function formatTime(value?: string | null) {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "-";
}

const historyColumns = [
  { title: "观测时间", dataIndex: "observed_at", key: "observed_at", width: 180, render: formatTime },
  { title: "任务", dataIndex: "task_id", key: "task_id", width: 260, render: (value: string) => <Link to={`/tasks/${value}`}>{value}</Link> },
  {
    title: "版本",
    dataIndex: "raw_version",
    key: "raw_version",
    width: 180,
    render: (value: string | null, record: InventoryVersionPoint) =>
      value || <Tag color={VERSION_STATUS_META[record.version_status as keyof typeof VERSION_STATUS_META]?.color || "blue"}>{VERSION_STATUS_META[record.version_status as keyof typeof VERSION_STATUS_META]?.label || record.version_status}</Tag> },
  {
    title: "方向",
    dataIndex: "direction",
    key: "direction",
    width: 110,
    render: (value: InventoryVersionPoint["direction"]) =>
      value ? <Tag color={DIRECTION_META[value].color}>{DIRECTION_META[value].label}</Tag> : "-" },
  {
    title: "缺口",
    dataIndex: "has_gap",
    key: "has_gap",
    width: 90,
    render: (value: boolean) => (value ? <Tag color="orange">有缺口</Tag> : "-") },
];

const observationColumns = [
  { title: "观测时间", dataIndex: "observed_at", key: "observed_at", width: 180, render: formatTime },
  { title: "任务", dataIndex: "task_id", key: "task_id", width: 260, render: (value: string) => <Link to={`/tasks/${value}`}>{value}</Link> },
  { title: "局点", dataIndex: "site_key", key: "site_key", width: 210, render: (value: string) => <Tag>{value}</Tag> },
  {
    title: "版本",
    dataIndex: "raw_version",
    key: "raw_version",
    width: 170,
    render: (value: string | null, record: InventoryObservation) =>
      value || <Tag color={record.version_status === "conflict" ? "red" : "orange"}>{record.version_status === "conflict" ? "版本冲突" : "版本缺失"}</Tag> },
  {
    title: "版本来源",
    dataIndex: "version_source_files",
    key: "version_source_files",
    ellipsis: true,
    render: (value: string[]) => value.join("、") },
];

export function InventoryDevicePage() {
  const { deviceId = "" } = useParams();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [observations, setObservations] = useState<InventoryObservation[]>([]);
  const [observationTotal, setObservationTotal] = useState(0);
  const [history, setHistory] = useState<InventoryVersionPoint[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [device, setDevice] = useState<Awaited<ReturnType<typeof api.getInventoryDevice>> | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [deviceData, historyData, observationData] = await Promise.all([
        api.getInventoryDevice(deviceId),
        api.getInventoryVersionHistory(deviceId, { page, page_size: pageSize }),
        api.listInventoryObservations(deviceId, { page, page_size: pageSize, order: "desc" }),
      ]);
      setDevice(deviceData);
      setHistory(historyData.items);
      setHistoryTotal(historyData.total);
      setObservations(observationData.items);
      setObservationTotal(observationData.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "设备详情加载失败");
    } finally {
      setLoading(false);
    }
  }, [deviceId, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteInventoryDevice(deviceId);
      message.success("设备台账已删除");
      navigate("/inventory");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除设备失败");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Flex vertical gap={16}>
      <Flex align="center" justify="space-between">
        <Flex align="center" gap={12}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/inventory")}>
            返回台账
          </Button>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {device?.device_name || "设备详情"}
          </Typography.Title>
        </Flex>
        <Flex gap={8}>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
          {isAdmin && device && (
            <Popconfirm
                title="确认删除该设备台账？"
                description="将物理删除设备、全部观测记录和版本历史。"
                okText="删除"
                okButtonProps={{ danger: true, loading: deleting }}
                cancelText="取消"
                onConfirm={() => void handleDelete()}
              >
                <Button danger loading={deleting}>
                  删除
                </Button>
            </Popconfirm>
          )}
        </Flex>
      </Flex>

      {error && <Alert type="error" showIcon message={error} />}
      {loading && !device && <PageSkeleton rows={6} />}
      {device && (
        <Card>
          <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
            <Descriptions.Item label="设备名称">{device.device_name}</Descriptions.Item>
            <Descriptions.Item label="省份">{device.province}</Descriptions.Item>
            <Descriptions.Item label="运营商">{device.operator}</Descriptions.Item>
            <Descriptions.Item label="当前局点">{device.site_key}</Descriptions.Item>
            <Descriptions.Item label="当前版本">{device.current_version || "版本缺失"}</Descriptions.Item>
            <Descriptions.Item label="当前版本任务">
              {device.current_version_task_id ? <Link to={`/tasks/${device.current_version_task_id}`}>{device.current_version_task_id}</Link> : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="首次观测">{formatTime(device.first_seen_at)}</Descriptions.Item>
            <Descriptions.Item label="最近观测">{formatTime(device.last_seen_at)}</Descriptions.Item>
            <Descriptions.Item label="观测次数">{device.observation_count}</Descriptions.Item>
          </Descriptions>
          {(device.has_site_conflict || device.current_version === null) && (
            <Alert
              style={{ marginTop: 16 }}
              type={device.has_site_conflict ? "warning" : "info"}
              showIcon
              message={device.has_site_conflict ? "设备存在局点归属变化" : "设备缺少版本信息"}
              description={device.current_version === null ? "版本只从 LST ME.txt 获取，缺失的观测不会参与版本方向判定。" : undefined}
            />
          )}
        </Card>
      )}

      <Card title="版本历史">
        {history.length === 0 && !loading ? (
          <EmptyState description="暂无版本历史" />
        ) : (
          <Table rowKey={(record) => `${record.task_id}-${record.observed_at}`} columns={historyColumns} dataSource={history} loading={loading} pagination={false} scroll={{ x: 820 }} />
        )}
        <Flex justify="flex-end" style={{ marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={historyTotal}
            showSizeChanger
            showTotal={(value) => `共 ${value} 个版本点`}
            onChange={(nextPage, size) => {
              setPage(nextPage);
              setPageSize(size);
            }}
          />
        </Flex>
      </Card>

      <Card title="观测历史">
        {observations.length === 0 && !loading ? (
          <EmptyState description="暂无观测记录" />
        ) : (
          <Table rowKey="observation_id" columns={observationColumns} dataSource={observations} loading={loading} pagination={false} scroll={{ x: 980 }} />
        )}
        <Flex justify="flex-end" style={{ marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={observationTotal}
            showSizeChanger
            showTotal={(value) => `共 ${value} 条观测`}
            onChange={(nextPage, size) => {
              setPage(nextPage);
              setPageSize(size);
            }}
          />
        </Flex>
      </Card>

    </Flex>
  );
}
