import { Button, Descriptions, Space, Typography } from "antd";
import dayjs from "dayjs";
import type { SystemInspection, TaskSummary } from "../../api/http";
import { getCustomerFields, getDeviceIdDisplay } from "../../utils/taskDisplay";
import { getTaskDurationDisplay } from "../../utils/taskCard";

type TaskMetaPanelProps = {
  task: TaskSummary;
  system: SystemInspection | null;
  deviceEditable?: boolean;
  onEditDevice?: (deviceId: string) => void;
};

export function TaskMetaPanel({ task, system, deviceEditable, onEditDevice }: TaskMetaPanelProps) {
  const customerFields = getCustomerFields(system?.customer);
  const customerText = customerFields.length ? customerFields.map((field) => `${field.label} ${field.value}`).join(" · ") : "-";
  const device = getDeviceIdDisplay(task, system?.customer);
  const manualDeviceId = (task.device_id ?? system?.customer?.device_id ?? "").trim();

  return (
    <div className="task-meta-panel" data-testid="task-meta-panel">
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
              <Space size={4} wrap>
                <Typography.Text>{device.value}</Typography.Text>
                {device.source === "ledger" && (
                  <Typography.Text type="secondary">（台账解析）</Typography.Text>
                )}
                {deviceEditable && onEditDevice && (
                  <Button size="small" type="text" onClick={() => onEditDevice(manualDeviceId)}>
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
            // 创建时间固定为任务创建时刻，最后一次运行时间随每次运行更新（FR-008）
            key: "last_run_at",
            label: "最后运行时间",
            children: task.last_run_at ? dayjs(task.last_run_at).format("YYYY-MM-DD HH:mm:ss") : "-",
          },
          {
            // 时长取最近一次运行的起止耗时；运行中只表明尚未结束，未运行显示占位（FR-008、FR-009）
            key: "duration",
            label: "任务时长",
            children: getTaskDurationDisplay(task),
          },
          {
            key: "completed_at",
            label: "完成时间",
            children: task.completed_at ? dayjs(task.completed_at).format("YYYY-MM-DD HH:mm:ss") : "-",
          },
        ]}
      />
    </div>
  );
}
