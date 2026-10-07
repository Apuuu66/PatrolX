import { Alert, Descriptions, Flex, List, Space, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Link } from "react-router-dom";
import type { components } from "../../api/client";
import { Table } from "../ResizableTable";
type MatchedDevice = components["schemas"]["TaskInventoryMatchedDevice"];
type InventoryRecord = components["schemas"]["TaskInventoryRecord"];

const PARSE_STATUS_META = {
  archived: { label: "已归档", color: "green" },
  not_archived: { label: "未归档", color: "orange" },
  not_applicable: { label: "不涉及台账", color: "blue" },
  failed: { label: "解析失败", color: "red" },
} as const;

const FIELD_STATUS_LABELS = {
  ok: "正常",
  missing: "缺失",
  conflict: "冲突",
  error: "解析失败",
  not_applicable: "不适用",
  matched_multiple: "多设备匹配",
} as const;

const PACKAGE_LABELS = {
  inspection: "巡检包",
  log_supplement: "日志补充包",
} as const;

const NOT_ARCHIVED_REASONS: Record<string, string> = {
  missing_site: "上传元数据缺少省份或运营商",
  network_element_type_filter_missing: "上传时未选择网元类型",
  network_element_type_no_match: "LST ME.txt 中没有网元类型相等的设备记录",
  matched_device_version_conflict: "匹配设备的版本存在冲突，未写入台账",
  source_file_missing: "压缩包中未找到 LST ME.txt",
  parse_error: "台账解析失败",
};

const NOT_APPLICABLE_REASONS: Record<string, string> = {
  log_supplement_package: "日志补充包不采集设备信息",
};

function fieldTag(status?: components["schemas"]["InventoryFieldStatus"]) {
  if (!status) return "-";
  const color = status === "ok" ? "green" : status === "conflict" || status === "error" ? "red" : "orange";
  return <Tag color={color}>{FIELD_STATUS_LABELS[status]}</Tag>;
}

function formatLines(sourceFiles: string[], lines: number[]) {
  if (!lines.length) return "-";
  const files = sourceFiles.length ? sourceFiles : ["LST ME.txt"];
  return `${files.join("、")} 第 ${lines.join("、")} 行`;
}

function deviceColumns(): ColumnsType<MatchedDevice> {
  return [
    {
      title: "设备名称",
      dataIndex: "normalized_name",
      key: "device_name",
      width: 220,
      ellipsis: true,
    },
    {
      title: "网元类型",
      dataIndex: "network_element_type",
      key: "network_element_type",
      width: 160,
      render: (value?: string | null) => value || <Tag color="orange">缺失</Tag>,
    },
    {
      title: "版本",
      key: "version",
      width: 240,
      render: (_, record) => {
        if (record.version.status === "ok" && record.version.raw_version) {
          return record.version.raw_version;
        }
        return fieldTag(record.version.status);
      },
    },
    {
      title: "来源",
      key: "source",
      ellipsis: true,
      render: (_, record) =>
        formatLines(record.source_files ?? [], record.version.source_lines ?? []),
    },
  ];
}

export function TaskInventoryPanel({ task }: { task: components["schemas"]["TaskSummary"] }) {
  const inventory = task.inventory;
  if (!inventory) {
    return <Alert type="info" showIcon message="任务尚未生成设备台账证据" />;
  }

  if (inventory.package_kind === "log_supplement") {
    return (
      <Alert
        type="info"
        showIcon
        message="日志补充包不涉及设备台账"
        description="该类型不解析设备信息，也不产生台账观测或质量问题。"
      />
    );
  }

  const devices = inventory.devices ?? [];
  const records = inventory.records ?? [];
  const archivedDevices = inventory.archived.devices ?? [];
  const filter = inventory.network_element_type_filter;
  const conflictText = (inventory.conflicts ?? [])
    .map((item) => JSON.stringify(item))
    .join("；");
  const errorText = (inventory.errors ?? []).map((item) => JSON.stringify(item)).join("；");
  const notArchivedReason =
    NOT_ARCHIVED_REASONS[inventory.not_archived_reason ?? ""] || inventory.not_archived_reason;
  const notApplicableReason =
    NOT_APPLICABLE_REASONS[inventory.not_applicable_reason ?? ""] || inventory.not_applicable_reason;

  const recordColumns: ColumnsType<InventoryRecord> = [
    {
      title: "设备名称",
      dataIndex: "normalized_name",
      key: "normalized_name",
      width: 200,
      render: (value?: string | null, record?: InventoryRecord, index?: number) => value || record?.raw_name || String(index ?? "-"),
    },
    {
      title: "网元类型",
      key: "network_element_type",
      width: 180,
      render: (_, record) => record.normalized_network_element_type || record.raw_network_element_type || <Tag color="orange">缺失</Tag>,
    },
    {
      title: "版本",
      dataIndex: "raw_version",
      key: "raw_version",
      width: 200,
      render: (value?: string | null, record?: InventoryRecord) => value || fieldTag(record?.version_status),
    },
    {
      title: "来源",
      key: "source",
      ellipsis: true,
      render: (_, record) => {
        const lines = record.type_source_lines?.length ? record.type_source_lines : record.name_source_lines;
        return `${record.source_file || "LST ME.txt"} 第 ${lines?.join("、") || "-"} 行`;
      },
    },
  ];

  return (
    <Flex vertical gap={16}>
      {inventory.status === "failed" && (
        <Alert type="error" showIcon message="设备台账解析失败，任务结果不受影响" description={errorText || undefined} />
      )}
      {inventory.status === "not_applicable" && notApplicableReason && (
        <Alert type="info" showIcon message="不涉及台账" description={notApplicableReason} />
      )}
      {inventory.status === "not_archived" && (
        <Alert type="warning" showIcon message="设备观测未归档" description={notArchivedReason} />
      )}

      <Descriptions
        column={{ xs: 1, sm: 2, lg: 3 }}
        size="small"
        items={[
          { key: "package_kind", label: "包类型", children: PACKAGE_LABELS[inventory.package_kind] },
          {
            key: "status",
            label: "归档状态",
            children: (
              <Tag color={PARSE_STATUS_META[inventory.status].color}>{PARSE_STATUS_META[inventory.status].label}</Tag>
            ),
          },
          { key: "parser", label: "解析器", children: `${inventory.parser_id} v${inventory.parser_version}` },
          { key: "province", label: "省份", children: inventory.site?.province || "-" },
          { key: "operator", label: "运营商", children: inventory.site?.operator || "-" },
          { key: "site_key", label: "局点", children: inventory.site?.site_key || "-" },
          {
            key: "filter",
            label: "网元类型筛选",
            children:
              filter?.requested ||
              notArchivedReason ||
              NOT_ARCHIVED_REASONS.network_element_type_filter_missing,
          },
          { key: "filter_status", label: "筛选状态", children: filter ? <Tag color={filter.status === "ok" ? "green" : "orange"}>{filter.status === "ok" ? "正常" : filter.status === "missing" ? "缺失" : "无匹配"}</Tag> : "-" },
          {
            key: "match_count",
            label: "记录匹配",
            children: filter ? `${filter.matched_count} 匹配 / ${filter.unmatched_count} 不匹配` : "-",
          },
          { key: "archived", label: "是否入库", children: inventory.archived.archived ? "是" : "否" },
          {
            key: "archived_count",
            label: "入库设备数",
            children: String(archivedDevices.length || (inventory.archived.device_id ? 1 : 0)),
          },
          { key: "updated_at", label: "任务完成时间", children: dayjs(task.completed_at || task.created_at).format("YYYY-MM-DD HH:mm:ss") },
        ]}
      />

      <div>
        <Typography.Title level={5} style={{ marginBottom: 8 }}>
          匹配设备
        </Typography.Title>
        {devices.length ? (
          <Table
            rowKey="normalized_name"
            size="small"
            columns={deviceColumns()}
            dataSource={devices}
            pagination={false}
            scroll={{ x: 780 }}
          />
        ) : (
          <Typography.Text type="secondary">
            {notArchivedReason || "暂无与所选网元类型匹配的设备记录"}
          </Typography.Text>
        )}
      </div>

      {records.length > 0 && (
        <div>
          <Typography.Title level={5} style={{ marginBottom: 8 }}>
            匹配记录明细
          </Typography.Title>
          <Table
            rowKey={(record, index) =>
              `${record.source_file || "LST ME.txt"}-${record.name_source_lines?.join("-") || index}`
            }
            size="small"
            columns={recordColumns}
            dataSource={records}
            pagination={false}
            scroll={{ x: 880 }}
          />
        </div>
      )}

      <div>
        <Typography.Title level={5} style={{ marginBottom: 8 }}>
          解析来源
        </Typography.Title>
        {(inventory.source_files ?? []).length ? (
          <List
            size="small"
            bordered
            dataSource={inventory.source_files ?? []}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        ) : (
          <Typography.Text type="secondary">无来源文件</Typography.Text>
        )}
      </div>

      {((inventory.conflicts ?? []).length > 0 || (inventory.errors ?? []).length > 0) && (
        <Alert
          type={(inventory.conflicts ?? []).length ? "warning" : "info"}
          showIcon
          message={(inventory.conflicts ?? []).length ? "存在字段冲突" : "存在解析提示"}
          description={
            <Space direction="vertical">
              {conflictText && <Typography.Text>{conflictText}</Typography.Text>}
              {errorText && <Typography.Text type="secondary">{errorText}</Typography.Text>}
            </Space>
          }
        />
      )}

      {archivedDevices.length > 0 ? (
        <Flex wrap="wrap" gap={8}>
          {archivedDevices.map((item) => (
            <Link key={item.device_id} to={`/inventory/devices/${item.device_id}`}>
              查看设备台账：{item.normalized_name}
            </Link>
          ))}
        </Flex>
      ) : inventory.archived.device_id ? (
        <Link to={`/inventory/devices/${inventory.archived.device_id}`}>查看设备台账详情</Link>
      ) : null}
    </Flex>
  );
}
