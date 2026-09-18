// 只注册当前图表能力，避免把完整 ECharts 打包进默认 chunk。
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer]);

export default echarts;
