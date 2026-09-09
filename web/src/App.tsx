import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MainLayout } from "./layouts/MainLayout";
import { TaskListPage } from "./pages/TaskListPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { RuleDetailPage } from "./pages/RuleDetailPage";
import { ReportPage } from "./pages/ReportPage";
import { LogsPage } from "./pages/LogsPage";
import { InspectorsPage } from "./pages/InspectorsPage";
import { DictsPage } from "./pages/DictsPage";

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
      { path: "dicts", element: <DictsPage /> },
    ],
  },
]);

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <RouterProvider router={router} />
      </AntApp>
    </ConfigProvider>
  );
}
