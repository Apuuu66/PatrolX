import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Input, Select, Space, Switch, Tag, Tooltip, Typography } from "antd";
import { Table } from "../components/ResizableTable";
import type { ColumnsType } from "antd/es/table";
import { api, type InspectorState } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { DensitySegmented } from "../components/DensitySegmented";
import { useTableDensity } from "../hooks/useTableDensity";
import { TABULAR_NUMERIC_CLASS, getRelativeTimeDisplay } from "../utils/timeDisplay";
import { EmptyState, LoadErrorState } from "../components/PageState";

/** 数据分页默认 10 条（宪法"数据分页默认"）。 */
const DEFAULT_PAGE_SIZE = 10;

const CATEGORY_LABELS: Record<string, string> = {
  log: "日志",
  kpi: "KPI",
  traffic: "话统",
  alarm: "告警",
  config: "配置",
  resource: "资源",
  other: "其他",
};

export function InspectorsPage() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<InspectorState[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [updatingCode, setUpdatingCode] = useState<string>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [category, setCategory] = useState<string | undefined>();
  const [enabled, setEnabled] = useState<boolean | undefined>();
  const [search, setSearch] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const { density, tableSize, setDensity } = useTableDensity();

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await api.listInspectorStates({ page, page_size: pageSize, category, enabled, search });
      setItems(result.items ?? []);
      setTotal(result.total);
    } catch (err) {
      const text = err instanceof Error ? err.message : "加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      setLoading(false);
    }
  }, [category, enabled, message, page, pageSize, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const updateEnabled = async (rule: InspectorState, nextEnabled: boolean) => {
    setUpdatingCode(rule.code);
    try {
      const updated = await api.setInspectorStateEnabled(rule.code, nextEnabled);
      setItems((current) => current.map((item) => (item.code === updated.code ? updated : item)));
      message.success(`规则 ${rule.code} 已${nextEnabled ? "启用" : "停用"}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新失败");
    } finally {
      setUpdatingCode(undefined);
    }
  };

  const columns: ColumnsType<InspectorState> = [
    {
      title: "规则编码",
      dataIndex: "code",
      width: 220,
      render: (value: string) => (
        <Typography.Text code copyable={{ text: value }} className="inspectors-code">
          {value}
        </Typography.Text>
      ),
    },
    { title: "名称", dataIndex: "name", width: 180, ellipsis: true },
    {
      title: "类别",
      dataIndex: "category",
      width: 100,
      render: (value: string) => <Tag>{CATEGORY_LABELS[value] ?? value}</Tag>,
    },
    { title: "优先级", dataIndex: "priority", width: 90, render: (value: number) => `P${value}` },
    {
      title: "启停状态",
      dataIndex: "enabled",
      width: 120,
      render: (value: boolean, record) => (
        <Switch
          checked={value}
          checkedChildren="启用"
          unCheckedChildren="停用"
          aria-label={`${record.code} 启停状态`}
          disabled={!isAdmin || updatingCode !== undefined}
          loading={updatingCode === record.code}
          onChange={(checked) => void updateEnabled(record, checked)}
        />
      ),
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 190,
      // 相对时间为主、完整时间走 Tooltip，与任务列表口径一致（FR-017、R12）。
      sorter: (a, b) => (a.updated_at ?? "").localeCompare(b.updated_at ?? ""),
      render: (value: string) => {
        const display = getRelativeTimeDisplay(value);
        return (
          <Tooltip title={display.title || undefined}>
            <span className={TABULAR_NUMERIC_CLASS} data-testid="inspector-updated-at">
              {display.text}
            </span>
          </Tooltip>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader
        title="规则启停管理"
        description="启停巡检规则，控制后续任务的执行范围"
      />
      <Card
        title={<Typography.Text strong>规则清单</Typography.Text>}
        extra={
        <Space wrap>
          <DensitySegmented value={density} onChange={setDensity} />
          <Select
            allowClear
            placeholder="类别筛选"
            style={{ width: 120 }}
            options={Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label }))}
            onChange={(value) => {
              setPage(1);
              setCategory(value);
            }}
          />
          <Select
            allowClear
            placeholder="状态筛选"
            style={{ width: 110 }}
            options={[
              { value: true, label: "已启用" },
              { value: false, label: "已停用" },
            ]}
            onChange={(value) => {
              setPage(1);
              setEnabled(value);
            }}
          />
          <Input.Search
            placeholder="搜索编码 / 名称"
            allowClear
            style={{ width: 240 }}
            onSearch={(value) => {
              setPage(1);
              setSearch(value.trim());
            }}
          />
        </Space>
      }
    >
      {loadError ? (
        <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />
      ) : (
        <Table
          className={`inspectors-table density-${density}`}
          rowKey="code"
          size={tableSize}
          loading={loading}
          dataSource={items}
          columns={columns}
          locale={{
            emptyText: (
              <EmptyState
                description={category || enabled !== undefined || search ? "没有符合筛选条件的规则" : "暂无已注册规则"}
                action={
                  category || enabled !== undefined || search ? (
                    <Button
                      onClick={() => {
                        setPage(1);
                        setCategory(undefined);
                        setEnabled(undefined);
                        setSearch("");
                      }}
                    >
                      清除筛选
                    </Button>
                  ) : (
                    <Button onClick={() => void load()}>刷新列表</Button>
                  )
                }
              />
            ),
          }}
          pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (value) => `共 ${value} 条`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
        />
      )}
      </Card>
    </>
  );
}
