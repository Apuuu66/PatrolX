import { useEffect, useRef, useState } from "react";
import { Button } from "antd";
import { CheckOutlined, CopyOutlined } from "@ant-design/icons";

/** 复制结果反馈的保留时长；到期后回到空闲态，避免长期噪音。 */
const FEEDBACK_DURATION_MS = 1600;

type CopyState = "idle" | "copied" | "failed";

export interface CopyTextButtonProps {
  /** 待复制的完整文本；不截断。 */
  text: string;
  /** 无障碍名称后缀，例如"来源路径"；默认"复制"。 */
  label?: string;
  size?: "small" | "middle";
  className?: string;
}

/** 优先使用异步剪贴板 API，不可用时降级到临时 textarea + execCommand。 */
async function writeToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 继续尝试降级路径
  }

  if (typeof document === "undefined" || typeof document.execCommand !== "function") {
    return false;
  }

  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "true");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

/**
 * 复制按钮（FR-010、FR-014、FR-015、contracts §7）。
 *
 * - 键盘可触发、焦点可见、点击不触发行跳转；
 * - 成功 / 失败都有可见反馈，失败时降级为可选中文本，保证用户仍能拿到内容。
 */
export function CopyTextButton({ text, label, size = "small", className }: CopyTextButtonProps) {
  const [state, setState] = useState<CopyState>("idle");
  const timerRef = useRef<number | null>(null);
  const accessibleName = label ? `复制${label}` : "复制";

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  const scheduleReset = () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setState("idle");
    }, FEEDBACK_DURATION_MS);
  };

  const handleClick = async (event: React.MouseEvent<HTMLElement>) => {
    // 复制是行内动作，不触发行点击 / 跳转（contracts §3、§7）。
    event.preventDefault();
    event.stopPropagation();
    const ok = await writeToClipboard(text);
    setState(ok ? "copied" : "failed");
    scheduleReset();
  };

  return (
    <span className={`copy-text-button${className ? ` ${className}` : ""}`}>
      <Button
        type="text"
        size={size}
        className="copy-text-button-trigger"
        aria-label={accessibleName}
        title={accessibleName}
        data-copy-state={state}
        icon={state === "copied" ? <CheckOutlined /> : <CopyOutlined />}
        onClick={(event) => void handleClick(event)}
      />
      <span className="copy-text-feedback" role="status" aria-live="polite">
        {state === "copied" ? "已复制" : state === "failed" ? "复制失败，请手动选择文本" : ""}
      </span>
      {state === "failed" ? (
        // 降级路径：内容以可选中文本呈现，用户仍可手动复制（contracts §7）。
        <code className="copy-text-fallback" data-testid="copy-text-fallback">
          {text}
        </code>
      ) : null}
    </span>
  );
}
