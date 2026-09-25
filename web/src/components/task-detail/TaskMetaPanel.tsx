import { Button, Descriptions, Space, Typography } from "antd";
import dayjs from "dayjs";
import type { SystemInspection, TaskSummary } from "../../api/http";
import { getCustomerFields } from "../../utils/taskDisplay";

type TaskMetaPanelProps = {
  task: TaskSummary;
  system: SystemInspection | null;
  deviceEditable?: boolean;
  onEditDevice?: (deviceId: string) => void;
};

export function TaskMetaPanel({ task, system, deviceEditable, onEditDevice }: TaskMetaPanelProps) {
  const customerFields = getCustomerFields(system?.customer);
  const customerText = customerFields.length ? customerFields.map((field) => `${field.label} ${field.value}`).join(" · ") : "-";
  const deviceId = task.device_id ?? system?.customer?.device_id ?? "-";

  return (
    <>
      <Descriptions
        size="small"
        column={4}
        items={[
          { key: "package", label: "数据包", children: system?.package_file ?? "-" },
          { key: "version", label: "版本", children: system?.version ?? "-" },
          { key: "mode", label: "模式", children: task.mode === "online" ? "在线" : "本地" },
          { key: "trigger", label: "触发方式", children: task.trigger },
        ]}
      />

      <Typography.Title level={5} className="task-detail-section-title">
        客户与环境
      </Typography.Title>
      <Descriptions
        size="small"
        column={3}
        items={[
          {
            key: "device_id",
            label: "设备 ID",
            children: (
              <Space size={4}>
                <Typography.Text>{deviceId}</Typography.Text>
                {deviceEditable && onEditDevice && (
                  <Button size="small" type="text" onClick={() => onEditDevice(deviceId)}>
                    编辑
                  </Button>
                )}
              </Space>
            ),
          },
          { key: "customer", label: "客户信息", children: customerText },
          { key: "empty", label: "", children: "" },
        ]}
      />

      <Typography.Title level={5} className="task-detail-section-title">
        执行时间
      </Typography.Title>
      <Descriptions
        size="small"
        column={2}
        items={[
          { key: "created_at", label: "创建时间", children: dayjs(task.created_at).format("YYYY-MM-DD HH:mm:ss") },
          {
            key: "completed_at",
            label: "完成时间",
            children: task.completed_at ? dayjs(task.completed_at).format("YYYY-MM-DD HH:mm:ss") : "-",
          },
        ]}
      />
    </>
  );
}
