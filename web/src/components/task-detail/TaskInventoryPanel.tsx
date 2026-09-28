import { Alert, Descriptions, Flex, List, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { Link } from "react-router-dom";
import type { TaskSummary } from "../../api/http";

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
} as const;

const PACKAGE_LABELS = {
  inspection: "巡检包",
  log_supplement: "日志补充包",
} as const;

function fieldTag(status?: TaskSummary["inventory"] extends null ? never : keyof typeof FIELD_STATUS_LABELS) {
  if (!status) return "-";
  return <Tag color={status === "ok" ? "green" : status === "conflict" || status === "error" ? "red" : "orange"}>{FIELD_STATUS_LABELS[status]}</Tag>;
}

export function TaskInventoryPanel({ task }: { task: TaskSummary }) {
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

  const conflictText = (inventory.conflicts ?? [])
    .map((item) => JSON.stringify(item))
    .join("；");
  const errorText = (inventory.errors ?? []).map((item) => JSON.stringify(item)).join("；");

  return (
    <Flex vertical gap={16}>
      {inventory.status === "failed" && (
        <Alert type="error" showIcon message="设备台账解析失败，任务结果不受影响" description={errorText || undefined} />
      )}
      {inventory.status === "not_archived" && (
        <Alert type="warning" showIcon message="设备观测未归档" description={inventory.not_archived_reason || undefined} />
      )}

      <Descriptions
        column={{ xs: 1, sm: 2, lg: 3 }}
        size="small"
        items={[
          { key: "package_kind", label: "包类型", children: PACKAGE_LABELS[inventory.package_kind] },
          { key: "status", label: "归档状态", children: <Tag color={PARSE_STATUS_META[inventory.status].color}>{PARSE_STATUS_META[inventory.status].label}</Tag> },
          { key: "parser", label: "解析器", children: `${inventory.parser_id} v${inventory.parser_version}` },
          { key: "site", label: "局点", children: inventory.site ? fieldTag(inventory.site.status) : "-" },
          { key: "device", label: "设备身份", children: inventory.device ? fieldTag(inventory.device.status) : "-" },
          { key: "version", label: "版本", children: inventory.version ? fieldTag(inventory.version.status) : "-" },
          { key: "province", label: "省份", children: inventory.site?.province || "-" },
          { key: "operator", label: "运营商", children: inventory.site?.operator || "-" },
          { key: "site_key", label: "site_key", children: inventory.site?.site_key || "-" },
          { key: "raw_version", label: "原始版本", children: inventory.version?.raw_version || "-" },
          { key: "archived", label: "是否入库", children: inventory.archived.archived ? "是" : "否" },
          { key: "device_id", label: "设备 ID", children: inventory.archived.device_id || "-" },
        ]}
      />

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

      {inventory.version?.raw_version && inventory.version.source_lines?.length ? (
        <Typography.Text type="secondary">
          版本来自 LST ME.txt 第 {inventory.version.source_lines.join("、")} 行。
        </Typography.Text>
      ) : null}

      <Typography.Text type="secondary">
        证据更新时间：{dayjs(task.completed_at || task.created_at).format("YYYY-MM-DD HH:mm:ss")}
      </Typography.Text>
      {inventory.archived.device_id && (
        <Link to={`/inventory/devices/${inventory.archived.device_id}`}>查看设备台账详情</Link>
      )}
    </Flex>
  );
}
