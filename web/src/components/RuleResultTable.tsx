import { Button, Empty, Popconfirm, Space, Table, Typography } from "antd";
import { RedoOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { RuleResult } from "../api/http";
import { RuleStatusTag, SeverityTag } from "./StatusBadge";
import { getRuleCategoryLabel } from "../utils/ruleCategories";

type RuleResultTableProps = {
  rules: RuleResult[];
  focusCategory?: string | null;
  emptyDescription?: string;
  onOpenRule: (ruleCode: string) => void;
  onRerunRule?: (ruleCode: string) => void;
};

export function RuleResultTable({
  rules,
  focusCategory = null,
  emptyDescription = "暂无规则结果",
  onOpenRule,
  onRerunRule,
}: RuleResultTableProps) {
  const columns: ColumnsType<RuleResult> = [
    {
      title: "规则",
      dataIndex: "code",
      render: (_, record) => (
        <div>
          <Typography.Link onClick={() => onOpenRule(record.code)}>{record.name}</Typography.Link>
          <Typography.Text type="secondary" className="rule-code-text">
            {record.code}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: "分类",
      dataIndex: "category",
      width: 110,
      render: (value: string) => getRuleCategoryLabel(value),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (value, record) => <RuleStatusTag status={value} skipReason={record.skip_reason} />,
    },
    {
      title: "严重度",
      dataIndex: "severity",
      width: 90,
      render: (value: string) => <SeverityTag severity={value} />,
    },
    { title: "结果摘要", dataIndex: "summary" },
    {
      title: "耗时",
      dataIndex: "duration_ms",
      width: 90,
      render: (value: number | null) => (value == null ? "-" : `${value}ms`),
    },
    {
      title: "操作",
      width: 150,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => onOpenRule(record.code)}>
            详情
          </Button>
          {onRerunRule && (
            <Popconfirm title={`重跑规则 ${record.code}？`} onConfirm={() => onRerunRule(record.code)}>
              <Button size="small" type="link" icon={<RedoOutlined />}>
                重跑
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  if (rules.length === 0) {
    return <Empty description={emptyDescription} />;
  }

  return (
    <Table
      rowKey="code"
      size="small"
      columns={columns}
      dataSource={rules}
      pagination={false}
      rowClassName={(record) => (record.category === focusCategory ? "rule-row-focus" : "")}
    />
  );
}
