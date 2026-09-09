import { useEffect, useMemo, useState } from "react";
import { App, Card, Input, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api, type InspectorInfo } from "../api/http";
import { SeverityTag } from "../components/StatusBadge";

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
  const [items, setItems] = useState<InspectorInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<string | undefined>();
  const [keyword, setKeyword] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        setItems(await api.listInspectors());
      } catch (err) {
        message.error(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [message]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return items.filter((i) => {
      if (category && i.category !== category) return false;
      if (kw && !`${i.code} ${i.name} ${i.description ?? ""}`.toLowerCase().includes(kw)) return false;
      return true;
    });
  }, [items, category, keyword]);

  const columns: ColumnsType<InspectorInfo> = [
    { title: "规则编码", dataIndex: "code", width: 200 },
    { title: "名称", dataIndex: "name", width: 150 },
    {
      title: "类别",
      dataIndex: "category",
      width: 90,
      render: (v: string) => <Tag>{CATEGORY_LABELS[v] ?? v}</Tag>,
    },
    { title: "优先级", dataIndex: "priority", width: 80, render: (v: number) => `P${v}` },
    { title: "严重度", dataIndex: "severity", width: 90, render: (v: string) => <SeverityTag severity={v} /> },
    { title: "版本", dataIndex: "rule_version", width: 80 },
    { title: "描述", dataIndex: "description" },
    { title: "处理建议", dataIndex: "recommendation" },
    {
      title: "输入依赖",
      dataIndex: "inputs",
      width: 160,
      render: (v: string[]) => (v ?? []).map((i) => <Tag key={i}>{i}</Tag>),
    },
    {
      title: "产出",
      dataIndex: "outputs",
      width: 180,
      render: (v: InspectorInfo["outputs"]) => (v?.artifacts ?? []).map((a) => <Tag key={a}>{a}</Tag>),
    },
  ];

  return (
    <Card
      title={<Typography.Text strong>规则管理（只读）</Typography.Text>}
      extra={
        <Space>
          <Select
            allowClear
            placeholder="类别筛选"
            style={{ width: 120 }}
            options={Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label }))}
            onChange={setCategory}
          />
          <Input.Search placeholder="搜索编码 / 名称 / 描述" allowClear style={{ width: 240 }} onChange={(e) => setKeyword(e.target.value)} />
        </Space>
      }
    >
      <Table rowKey="code" size="small" loading={loading} dataSource={filtered} columns={columns} pagination={{ pageSize: 20 }} />
    </Card>
  );
}
