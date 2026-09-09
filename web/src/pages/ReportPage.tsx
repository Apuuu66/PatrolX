import { Breadcrumb, Card } from "antd";
import { Link, useParams } from "react-router-dom";
import { reportUrl } from "../api/http";

export function ReportPage() {
  const { taskId = "" } = useParams();
  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link to="/tasks">巡检任务</Link> },
          { title: <Link to={`/tasks/${taskId}`}>任务详情</Link> },
          { title: "巡检报告" },
        ]}
      />
      <Card title="巡检报告" styles={{ body: { padding: 0 } }}>
        <iframe src={reportUrl(taskId)} title="巡检报告" style={{ width: "100%", height: "calc(100vh - 200px)", border: 0 }} />
      </Card>
    </div>
  );
}
