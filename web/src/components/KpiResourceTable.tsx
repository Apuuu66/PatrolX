import { Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { KpiResourceMetric } from "../api/http";
import { resourceDomainLabel } from "./kpiResourceModel";

const DOMAIN_COLORS: Record<string, string> = {
  unclassified: "default",
  call: "blue",
  api: "geekblue",
  media: "purple",
};

interface Props {
  items: KpiResourceMetric[];
  total: number;
  page: number;
  pageSize: number;
  loading?: boolean;
  selectable?: boolean;
  selectedKeys: string[];
  onSelectedKeysChange: (keys: string[]) => void;
  onPageChange: (page: number, pageSize: number) => void;
}

export function KpiResourceTable({
  items,
  total,
  page,
  pageSize,
  loading,
  selectable = true,
  selectedKeys,
  onSelectedKeysChange,
  onPageChange,
}: Props) {
  const columns: ColumnsType<KpiResourceMetric> = [
    { title: "资源 ID", dataIndex: "resource_id", width: 140 },
    { title: "Key", dataIndex: "key", width: 140 },
    { title: "中文名", dataIndex: "name_zh", ellipsis: true },
    { title: "英文名", dataIndex: "name_en", ellipsis: true },
    {
      title: "业务域",
      dataIndex: "domain",
      width: 100,
      render: (value: string) => <Tag color={DOMAIN_COLORS[value]}>{resourceDomainLabel(value)}</Tag>,
    },
  ];

  return (
    <Table
      rowKey="key"
      size="small"
      loading={loading}
      columns={columns}
      dataSource={items}
      rowSelection={
        selectable
          ? {
              selectedRowKeys: selectedKeys,
              onChange: (keys) => onSelectedKeysChange(keys.map(String)),
            }
          : undefined
      }
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showTotal: (value) => `共 ${value} 条`,
        onChange: onPageChange,
      }}
    />
  );
}
