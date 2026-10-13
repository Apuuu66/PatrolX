import { Alert, Card } from "antd";
import { LoadErrorState, PageSkeleton } from "../PageState";
import { useTaskReport } from "../../hooks/useTaskReport";
import { isSceneCleaned, SCENE_CLEANED_ADVICE } from "../../utils/sceneError";

type TaskReportContentProps = {
  taskId: string;
  /** 报告框样式类名，任务详情与独立报告页各自保留既有版式。 */
  frameClassName?: string;
};

/** 报告正文加载与现场缺失提示；410 scene_cleaned 时展示服务端消息与恢复建议（FR-011）。 */
export function TaskReportContent({ taskId, frameClassName = "task-report-frame" }: TaskReportContentProps) {
  const { state, loading, reload } = useTaskReport(taskId);

  if (state.status === "loading") {
    return <PageSkeleton rows={2} />;
  }

  if (state.status === "error") {
    if (isSceneCleaned(state.error)) {
      return (
        <Alert
          type="warning"
          showIcon
          data-testid="report-scene-cleaned"
          message={state.error.message}
          description={SCENE_CLEANED_ADVICE}
        />
      );
    }
    return (
      <LoadErrorState
        description={state.error.message}
        onRetry={() => void reload()}
        retrying={loading}
      />
    );
  }

  return <iframe srcDoc={state.html} title="巡检报告" className={frameClassName} />;
}

export function TaskReportPanel({ taskId }: { taskId: string }) {
  return (
    <Card title="巡检报告" styles={{ body: { padding: 0 } }}>
      <TaskReportContent taskId={taskId} />
    </Card>
  );
}
