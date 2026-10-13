/** 现场清理错误的统一识别与展示辅助（034 FR-011、FR-012）。 */

export interface ResourceErrorState {
  message: string;
  code?: string;
  statusCode?: number;
}

export const SCENE_CLEANED_CODE = "scene_cleaned";

/** 现场缺失时的后续建议：核心数据可查 + 重传同名包将提示覆盖并全量重建。 */
export const SCENE_CLEANED_ADVICE =
  "任务详情、规则结果与 KPI 等核心数据仍可在界面查询；重新上传同名数据包将提示覆盖并全量重建。";

export function toResourceError(error: unknown, fallback = "加载失败"): ResourceErrorState {
  if (error !== null && typeof error === "object" && "message" in error) {
    const source = error as { message?: unknown; code?: unknown; status?: unknown };
    return {
      message: typeof source.message === "string" ? source.message : fallback,
      code: typeof source.code === "string" ? source.code : undefined,
      statusCode: typeof source.status === "number" ? source.status : undefined,
    };
  }
  return { message: fallback };
}

export function isSceneCleaned(error: ResourceErrorState | null | undefined): boolean {
  return error?.code === SCENE_CLEANED_CODE || error?.statusCode === 410;
}
