/**
 * 上传前置校验（FR-023、FR-024、R16、data-model §5）。
 *
 * 与后端 `app/cli.py::clean_task_id` / `app/api/router.py::create_task_v3` 语义保持一致，
 * 不新增接口调用；仅把后端已有的校验前移到选择文件之后即时反馈。
 */

/** 与后端 `settings.max_upload_mb` 对齐的上限。 */
export const MAX_UPLOAD_MB = 2048;
export const MAX_FILENAME_BYTES = 255;

const PACKAGE_EXTENSIONS = [".zip", ".tar", ".gz", ".tgz"] as const;

export interface PackageFileInfo {
  name: string;
  size: number;
}

export interface PackageFileValidation {
  valid: boolean;
  formatValid: boolean;
  sizeValid: boolean;
  nameValid: boolean;
  /** 具体原因；合法时为空数组。 */
  messages: string[];
}

/** 与后端 `clean_task_id` 完全一致的清洗规则，结果带 `task-` 前缀。 */
export function deriveTaskIdPreview(fileName: string): string {
  const stem = fileName.toLowerCase().replace(/\.(zip|tar\.gz|tgz|tar)$/, "");
  const cleaned = stem.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return `task-${cleaned || "task"}`;
}

/** 文件名字节数（后端按 UTF-8 计数）。 */
export function filenameByteLength(fileName: string): number {
  return new TextEncoder().encode(fileName).length;
}

export function hasSupportedExtension(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  return PACKAGE_EXTENSIONS.some((extension) => lower.endsWith(extension));
}

export function validatePackageFile(file: PackageFileInfo): PackageFileValidation {
  const name = file.name.trim();
  const messages: string[] = [];

  const formatValid = Boolean(name) && hasSupportedExtension(name);
  if (!formatValid) {
    messages.push("仅支持 zip / tar.gz 数据包，请重新选择文件");
  }

  const nameValid = Boolean(name) && filenameByteLength(name) <= MAX_FILENAME_BYTES;
  if (Boolean(name) && !nameValid) {
    messages.push(`文件名超过 ${MAX_FILENAME_BYTES} 字节，请缩短文件名`);
  }

  const sizeValid = Number.isFinite(file.size) && file.size > 0 && file.size <= MAX_UPLOAD_MB * 1024 * 1024;
  if (!sizeValid) {
    if (!Number.isFinite(file.size) || file.size <= 0) {
      messages.push("数据包为空，请重新导出压缩包");
    } else {
      messages.push(`数据包超过 ${MAX_UPLOAD_MB} MB 上限，请拆分后重新上传`);
    }
  }

  return { valid: formatValid && sizeValid && nameValid, formatValid, sizeValid, nameValid, messages };
}

const SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

/** 人类可读文件大小；非法值返回占位符。 */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < SIZE_UNITS.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const rounded = unitIndex === 0 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${SIZE_UNITS[unitIndex]}`;
}
