import { Suspense, lazy } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { App as AntApp, ConfigProvider, Spin } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MainLayout } from "./layouts/MainLayout";
import { AuthProvider } from "./auth/AuthContext";

const TaskListPage = lazy(() =>
  import("./pages/TaskListPage").then(({ TaskListPage }) => ({ default: TaskListPage })),
);
const TaskDetailPage = lazy(() =>
  import("./pages/TaskDetailPage").then(({ TaskDetailPage }) => ({ default: TaskDetailPage })),
);
const RuleDetailPage = lazy(() =>
  import("./pages/RuleDetailPage").then(({ RuleDetailPage }) => ({ default: RuleDetailPage })),
);
const ReportPage = lazy(() => import("./pages/ReportPage").then(({ ReportPage }) => ({ default: ReportPage })));
const LogsPage = lazy(() => import("./pages/LogsPage").then(({ LogsPage }) => ({ default: LogsPage })));
const InspectorsPage = lazy(() =>
  import("./pages/InspectorsPage").then(({ InspectorsPage }) => ({ default: InspectorsPage })),
);
const DictsPage = lazy(() => import("./pages/DictsPage").then(({ DictsPage }) => ({ default: DictsPage })));
const KpiResourcesPage = lazy(() =>
  import("./pages/KpiResourcesPage").then(({ KpiResourcesPage }) => ({ default: KpiResourcesPage })),
);
const UsersPage = lazy(() => import("./pages/UsersPage").then(({ UsersPage }) => ({ default: UsersPage })));

const PageFallback = (
  <div style={{ display: "grid", placeItems: "center", minHeight: 320 }}>
    <Spin />
  </div>
);

const router = createBrowserRouter([
  {
    path: "/",
    element: <MainLayout />,
    children: [
      { index: true, element: <TaskListPage /> },
      { path: "tasks", element: <TaskListPage /> },
      { path: "tasks/:taskId", element: <TaskDetailPage /> },
      { path: "tasks/:taskId/rules/:ruleCode", element: <RuleDetailPage /> },
      { path: "tasks/:taskId/report", element: <ReportPage /> },
      { path: "tasks/:taskId/logs", element: <LogsPage /> },
      { path: "inspectors", element: <InspectorsPage /> },
      { path: "kpi-resources", element: <KpiResourcesPage /> },
      { path: "dicts", element: <DictsPage /> },
      { path: "users", element: <UsersPage /> },
    ],
  },
]);

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <AuthProvider>
        <AntApp>
          <Suspense fallback={PageFallback}>
            <RouterProvider router={router} />
          </Suspense>
        </AntApp>
      </AuthProvider>
    </ConfigProvider>
  );
}
