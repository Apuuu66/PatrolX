import { Button, Breadcrumb, Card, Space, Typography } from "antd";
import { ExportOutlined } from "@ant-design/icons";
import { Link, useParams } from "react-router-dom";
import { reportUrl } from "../api/http";

export function ReportPage() {
  const { taskId = "" } = useParams();
  const url = reportUrl(taskId);

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
      <Card
        title={
          <Space wrap>
            <Typography.Text strong>巡检报告</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {taskId}
            </Typography.Text>
          </Space>
        }
        extra={
          <Button icon={<ExportOutlined />} onClick={() => window.open(url, "_blank", "noopener,noreferrer")}>
            新窗口打开
          </Button>
        }
        styles={{ body: { padding: 0 } }}
      >
        <iframe src={url} title="巡检报告" style={{ width: "100%", height: "calc(100vh - 200px)", border: 0 }} />
      </Card>
    </div>
  );
}
