import { Descriptions, Drawer, Space, Table, Tag, Typography } from "antd";

import { getKpiMetricDetailView, type KpiCatalogItem } from "./kpiCatalogModel";
import { KpiMetricTrend } from "./KpiMetricTrend";
import { KpiRecordTable } from "./KpiRecordTable";

interface Props {
  item: KpiCatalogItem | null;
  open: boolean;
  onClose: () => void;
  taskId?: string;
  ruleCode?: string;
}

export function KpiMetricDrawer({ item, open, onClose, taskId, ruleCode }: Props) {
  if (!item) {
    return <Drawer open={open} onClose={onClose} width={760} title="指标详情" />;
  }

  const view = getKpiMetricDetailView(item);

  return (
    <Drawer open={open} onClose={onClose} width={760} title={`${view.title}（${view.subtitle}）`}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Text type="secondary">{view.description}</Typography.Text>
        <Descriptions size="small" column={2} bordered>
          <Descriptions.Item label="汇总值">{view.mainValueText}</Descriptions.Item>
          <Descriptions.Item label="状态">{view.statusLabel}</Descriptions.Item>
          <Descriptions.Item label="阈值">{view.thresholdText}</Descriptions.Item>
          <Descriptions.Item label="公式">{view.formulaText}</Descriptions.Item>
        </Descriptions>

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

        <div>
          <Typography.Text strong>输入指标</Typography.Text>
          <Table
            size="small"
            style={{ marginTop: 8 }}
            rowKey="key"
            pagination={false}
            dataSource={view.inputRows}
            columns={[
              { title: "Key", dataIndex: "key" },
              { title: "值", dataIndex: "valueText", width: 110 },
              { title: "聚合", dataIndex: "aggregation", width: 130 },
            ]}
          />
        </div>

        {view.crossReferenceRows.length > 0 && (
          <div>
            <Typography.Text strong>直接列交叉参考</Typography.Text>
            <Table
              size="small"
              style={{ marginTop: 8 }}
              rowKey={(row) => `${row.sourceName}-${row.sourceFile}-${row.valueText}`}
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

        <div>
          <Typography.Text strong>来源文件</Typography.Text>
          <div style={{ marginTop: 6 }}>
            {view.sourceFiles.length ? view.sourceFiles.map((file) => <Tag key={file}>{file}</Tag>) : "-"}
          </div>
        </div>

        <Space wrap>
          {view.fallbackUsed && <Tag color="blue">声明式分母兜底</Tag>}
          {view.denominatorZero && <Tag color="red">分母为零</Tag>}
        </Space>

        <KpiMetricTrend result={item.result} metricName={view.title} />

        {taskId && ruleCode && (
          <KpiRecordTable
            taskId={taskId}
            ruleCode={ruleCode}
            item={item}
            sourceFiles={view.sourceFiles}
          />
        )}
      </Space>
    </Drawer>
  );
}
