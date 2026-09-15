import { useMemo, useState } from "react";
import { Alert, Empty, Input, Table, Typography } from "antd";

import { buildKpiUnclassifiedRows, parseKpiMetadata } from "./kpiCatalogModel";

interface Props {
  metadata: unknown;
}

export function KpiUnclassifiedList({ metadata }: Props) {
  const [query, setQuery] = useState("");
  const parsed = parseKpiMetadata(metadata);
  const rows = useMemo(() => buildKpiUnclassifiedRows(metadata, { query }), [metadata, query]);

  if (!parsed) return null;
  if (!rows.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有未识别指标" />;
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        message={`${rows.length} 个未登记指标`}
        description="这些列未进入指标判定。如需纳入口径，请在 deploy/config/kpi 对应领域文件中新增指标或别名。"
      />
      <Input.Search
        allowClear
        placeholder="搜索原始列名或来源文件"
        style={{ width: 280, marginTop: 12 }}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onSearch={setQuery}
      />
      <Table
        size="small"
        style={{ marginTop: 12 }}
        rowKey="sourceName"
        columns={[
          { title: "原始列名", dataIndex: "sourceName" },
          { title: "记录数", dataIndex: "recordCount", width: 90 },
          { title: "样例值", dataIndex: "sampleValues", ellipsis: true },
          { title: "来源文件", dataIndex: "sourceFiles", ellipsis: true },
          { title: "原因", dataIndex: "reason", width: 120 },
        ]}
        dataSource={rows}
        pagination={rows.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
      />
      <Typography.Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
        未识别指标只做保留展示，不改变巡检状态。
      </Typography.Text>
    </div>
  );
}
