import { Button, Card, Dropdown, Space, Typography } from "antd";
import {
  ClearOutlined,
  FileTextOutlined,
  MoreOutlined,
  RedoOutlined,
  RollbackOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";
import type { TaskSummary } from "../../api/http";
import { TaskStatusTag } from "../StatusBadge";

type TaskDetailHeaderProps = {
  task: TaskSummary;
  busy: boolean;
  canRebuild: boolean;
  rebuilding: boolean;
  onOpenReport: () => void;
  onOpenLogs: () => void;
  onRerunAll: () => void;
  onOpenRebuild: () => void;
  onBack: () => void;
};

export function TaskDetailHeader({
  task,
  busy,
  canRebuild,
  rebuilding,
  onOpenReport,
  onOpenLogs,
  onRerunAll,
  onOpenRebuild,
  onBack,
}: TaskDetailHeaderProps) {
  return (
    <Card
      title={
        <Space>
          <Typography.Text strong>{task.name}</Typography.Text>
          <TaskStatusTag status={task.status} />
        </Space>
      }
      extra={
        <Space>
          <Button type="primary" icon={<FileTextOutlined />} onClick={onOpenReport}>
            查看报告
          </Button>
          <Dropdown
            menu={{
              items: [
                { key: "logs", label: "执行日志", icon: <UnorderedListOutlined /> },
                { key: "rerun", label: "重跑全部", icon: <RedoOutlined /> },
                { key: "rebuild", label: "增量重建", disabled: busy || !canRebuild || rebuilding, icon: <ClearOutlined /> },
                { type: "divider" },
                { key: "back", label: "返回列表", icon: <RollbackOutlined /> },
              ],
              onClick: ({ key }) => {
                if (key === "logs") onOpenLogs();
                if (key === "rerun") onRerunAll();
                if (key === "rebuild") onOpenRebuild();
                if (key === "back") onBack();
              },
            }}
            trigger={["click"]}
          >
            <Button aria-label="更多操作" icon={<MoreOutlined />} />
          </Dropdown>
        </Space>
      }
      className="task-detail-panel"
    />
  );
}

export function TaskDetailBreadcrumb() {
  return (
    <div className="task-detail-breadcrumb">
      <Link to="/tasks">巡检任务</Link>
    </div>
  );
}
