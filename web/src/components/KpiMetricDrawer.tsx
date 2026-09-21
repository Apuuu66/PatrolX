import { Collapse, Descriptions, Drawer, Space, Table, Tag, Typography } from "antd";

import { getKpiMetricDetailView, type KpiCatalogItem } from "./kpiCatalogModel";
import { KpiMetricTrend } from "./KpiMetricTrend";
import { KpiRecordTable } from "./KpiRecordTable";

interface Props {
  item: KpiCatalogItem | null;
  open: boolean;
  onClose: () => void;
  taskId?: string;
  ruleCode?: string;
  metricNames?: Map<string, string>;
}

export function KpiMetricDrawer({ item, open, onClose, taskId, ruleCode, metricNames }: Props) {
  const displayName = (key: string) => metricNames?.get(key) ?? key;
  if (!item) {
    return <Drawer open={open} onClose={onClose} width={1020} title="指标详情" />;
  }

  const view = getKpiMetricDetailView(item);
  const hasDiagnosticTags = view.fallbackUsed || view.denominatorZero;

  return (
    <Drawer open={open} onClose={onClose} width={1020} title={view.title}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Text type="secondary">{view.description}</Typography.Text>
        <Descriptions size="small" column={2} bordered>
          <Descriptions.Item label="汇总值">
            {view.mainValueText}
            {view.unitText && <span style={{ marginLeft: 4 }}>{view.unitText}</span>}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <span style={{ color: view.statusColor, fontWeight: 600 }}>{view.statusLabel}</span>
          </Descriptions.Item>
          <Descriptions.Item label="阈值">{view.thresholdText}</Descriptions.Item>
          <Descriptions.Item label="公式">{view.formulaText}</Descriptions.Item>
        </Descriptions>

        <KpiMetricTrend result={item.result} metricName={view.title} />

        {view.unavailableReasonText !== "-" && (
          <Typography.Text type="warning">不可用原因：{view.unavailableReasonText}</Typography.Text>
        )}
        {view.missingInputs.length > 0 && (
          <div>
            <Typography.Text strong>缺失输入</Typography.Text>
            <div style={{ marginTop: 6 }}>
              {view.missingInputs.map((input) => (
                <Tag key={input} color="warning">{input}</Tag>
              ))}
            </div>
          </div>
        )}
        {hasDiagnosticTags && (
          <Space wrap>
            {view.fallbackUsed && <Tag color="blue">声明式分母兜底</Tag>}
            {view.denominatorZero && <Tag color="red">分母为零</Tag>}
          </Space>
        )}

        <div>
          <Typography.Text strong>输入指标</Typography.Text>
          <Table
            size="small"
            style={{ marginTop: 8 }}
            rowKey="key"
            pagination={false}
            dataSource={view.inputRows}
            columns={[
              { title: "实际列名", dataIndex: "sourceNamesText" },
              {
                title: "指标",
                dataIndex: "key",
                render: (_, record) => (
                  <div style={{ minWidth: 0 }}>
                    <div>{displayName(record.key)}</div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {record.key}
                    </Typography.Text>
                  </div>
                ),
              },
              { title: "值", dataIndex: "valueText", width: 110 },
              { title: "聚合", dataIndex: "aggregation", width: 130 },
            ]}
          />
        </div>

        <Collapse
          items={[
            {
              key: "trace",
              label: "数据溯源",
              children: (
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  <div>
                    <Typography.Text strong>来源文件</Typography.Text>
                    <div style={{ marginTop: 6 }}>
                      {view.sourceFiles.length ? view.sourceFiles.map((file) => <Tag key={file}>{file}</Tag>) : "-"}
                    </div>
                  </div>
                  {view.crossReferenceRows.length > 0 && (
                    <div>
                      <Typography.Text strong>直出指标参考</Typography.Text>
                      <Table
                        size="small"
                        style={{ marginTop: 8 }}
                        rowKey="key"
                        pagination={{ pageSize: 5, hideOnSinglePage: true }}
                        dataSource={view.crossReferenceRows}
                        columns={[
                          { title: "来源列", dataIndex: "sourceName" },
                          { title: "来源文件", dataIndex: "sourceFile", ellipsis: true },
                          { title: "值", dataIndex: "valueText", width: 90 },
                        ]}
                      />
                    </div>
                  )}
                </Space>
              ),
            },
            ...(taskId && ruleCode
              ? [{
                  key: "records",
                  label: "原始记录",
                  children: (
                    <KpiRecordTable
                      taskId={taskId}
                      ruleCode={ruleCode}
                      item={item}
                      sourceFiles={view.sourceFiles}
                    />
                  ),
                }]
              : []),
          ]}
        />
      </Space>
    </Drawer>
  );
}
