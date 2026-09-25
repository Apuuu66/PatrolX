import { Card } from "antd";
import { reportUrl } from "../../api/http";

type TaskReportPanelProps = {
  taskId: string;
};

export function TaskReportPanel({ taskId }: TaskReportPanelProps) {
  return (
    <Card title="巡检报告" styles={{ body: { padding: 0 } }}>
      <iframe src={reportUrl(taskId)} title="巡检报告" className="task-report-frame" />
    </Card>
  );
}
