import { lazy } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { MainLayout } from "./layouts/MainLayout";

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
const MeasurementUnitsPage = lazy(() =>
  import("./pages/MeasurementUnitsPage").then(({ MeasurementUnitsPage }) => ({ default: MeasurementUnitsPage })),
);
const UsersPage = lazy(() => import("./pages/UsersPage").then(({ UsersPage }) => ({ default: UsersPage })));
const InventoryPage = lazy(() =>
  import("./pages/InventoryPage").then(({ InventoryPage }) => ({ default: InventoryPage })),
);
const InventoryDevicePage = lazy(() =>
  import("./pages/InventoryDevicePage").then(({ InventoryDevicePage }) => ({
    default: InventoryDevicePage,
  })),
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
      { path: "inventory", element: <InventoryPage /> },
      { path: "inventory/devices/:deviceId", element: <InventoryDevicePage /> },
      { path: "inspectors", element: <InspectorsPage /> },
      { path: "measurement-units", element: <MeasurementUnitsPage /> },
      { path: "dicts", element: <DictsPage /> },
      { path: "users", element: <UsersPage /> },
    ],
  },
]);

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
