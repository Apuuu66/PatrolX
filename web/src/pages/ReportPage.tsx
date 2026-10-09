import { Alert, Breadcrumb, Button, Card } from "antd";
import { Link, useNavigate, useParams } from "react-router-dom";
import { reportUrl } from "../api/http";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { TaskStatusTag } from "../components/StatusBadge";
import { TaskMetaPanel } from "../components/task-detail/TaskMetaPanel";
import { useTaskDetailData } from "../hooks/useTaskDetailData";

export function ReportPage() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const { data, loading, reload } = useTaskDetailData(taskId);

  const task = data?.task.status === "ready" ? data.task.data : null;
  const taskError = data?.task.status === "error" ? data.task.message : null;
  const system = data?.system.status === "ready" ? data.system.data : null;
  const systemError = data?.system.status === "error" ? data.system.message : null;

  const breadcrumb = (
    <Breadcrumb
      items={[
        { title: <Link to="/tasks">巡检任务</Link> },
        { title: <Link to={`/tasks/${taskId}`}>任务详情</Link> },
        { title: "巡检报告" },
      ]}
    />
  );

  if (loading && !task) {
    return (
      <div>
        <PageHeader breadcrumb={breadcrumb} title="巡检报告" />
        <PageSkeleton rows={3} />
      </div>
    );
  }

  if (!task) {
    if (taskError) {
      return (
        <div>
          <PageHeader breadcrumb={breadcrumb} title="巡检报告" />
          <LoadErrorState
            description={taskError}
            onRetry={() => void reload()}
            retrying={loading}
          />
        </div>
      );
    }
    return (
      <div>
        <PageHeader breadcrumb={breadcrumb} title="巡检报告" />
        <EmptyState
          description="任务不存在"
          action={
            <Button type="primary" onClick={() => navigate("/tasks")}>
              返回任务列表
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        breadcrumb={breadcrumb}
        title={task.name}
        description="巡检报告"
        status={<TaskStatusTag status={task.status} />}
      />
      <Card title="任务信息" className="report-task-card">
        {systemError && (
          <Alert
            type="warning"
            showIcon
            message="系统结果加载失败"
            description={systemError}
            action={
              <Button size="small" loading={loading} onClick={() => void reload()}>
                重试
              </Button>
            }
            style={{ marginBottom: 16 }}
          />
        )}
        <TaskMetaPanel task={task} system={system} />
      </Card>
      <Card title="巡检报告" styles={{ body: { padding: 0 } }}>
        <iframe src={reportUrl(taskId)} title="巡检报告" className="report-page-frame" />
      </Card>
    </div>
  );
}
