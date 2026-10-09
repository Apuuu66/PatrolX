import { Button, Dropdown } from "antd";
import {
  ClearOutlined,
  MoreOutlined,
  RedoOutlined,
  RollbackOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";

type TaskDetailMoreMenuProps = {
  busy: boolean;
  canRebuild: boolean;
  rebuilding: boolean;
  onOpenLogs: () => void;
  onRerunAll: () => void;
  onOpenRebuild: () => void;
  onBack: () => void;
};

/** 任务详情低频 / 危险操作入口，保持既有能力不变（FR-013）。 */
export function TaskDetailMoreMenu({
  busy,
  canRebuild,
  rebuilding,
  onOpenLogs,
  onRerunAll,
  onOpenRebuild,
  onBack,
}: TaskDetailMoreMenuProps) {
  return (
    <Dropdown
      menu={{
        items: [
          { key: "logs", label: "执行日志", icon: <UnorderedListOutlined /> },
          { key: "rerun", label: "重跑全部", icon: <RedoOutlined /> },
          {
            key: "rebuild",
            label: "增量重建",
            disabled: busy || !canRebuild || rebuilding,
            icon: <ClearOutlined />,
          },
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
  );
}

export function TaskDetailBreadcrumb() {
  return (
    <div className="task-detail-breadcrumb">
      <Link to="/tasks">巡检任务</Link>
    </div>
  );
}
