import { useCallback, useState } from "react";
import { App } from "antd";
import { api } from "../api/http";
import { isSceneCleaned, SCENE_CLEANED_ADVICE, toResourceError } from "../utils/sceneError";

export function useTaskActions(taskId: string, reload: () => Promise<void>) {
  const { message, modal } = App.useApp();
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [rebuildRuleCodes, setRebuildRuleCodes] = useState<string[]>([]);
  const [rebuilding, setRebuilding] = useState(false);
  const [deviceOpen, setDeviceOpen] = useState(false);
  const [deviceValue, setDeviceValue] = useState("");
  const [deviceSaving, setDeviceSaving] = useState(false);
  const [deviceError, setDeviceError] = useState<string | null>(null);

  /** 现场已清理属于需要用户动作的失败，用模态展示服务端消息与恢复建议（FR-011）。 */
  const reportActionError = useCallback(
    (error: unknown, fallback: string) => {
      const state = toResourceError(error, fallback);
      if (isSceneCleaned(state)) {
        modal.error({
          title: "磁盘现场已清理",
          content: `${state.message}。${SCENE_CLEANED_ADVICE}`,
          okText: "知道了",
        });
        return;
      }
      message.error(state.message);
    },
    [message, modal],
  );

  const rerunAll = useCallback(async () => {
    try {
      await api.rerunTask(taskId);
      message.success("已受理全量重跑");
      await reload();
    } catch (error) {
      reportActionError(error, "重跑失败");
    }
  }, [message, reload, reportActionError, taskId]);

  const rerunOne = useCallback(async (ruleCode: string) => {
    try {
      await api.rerunTask(taskId, [ruleCode]);
      message.success(`已受理重跑 ${ruleCode}`);
      await reload();
    } catch (error) {
      reportActionError(error, "重跑失败");
    }
  }, [message, reload, reportActionError, taskId]);

  const openDeviceModal = useCallback((value: string) => {
    setDeviceValue(value);
    setDeviceError(null);
    setDeviceOpen(true);
  }, []);

  const closeDeviceModal = useCallback(() => {
    setDeviceOpen(false);
    setDeviceError(null);
  }, []);

  const saveDeviceId = useCallback(async () => {
    setDeviceSaving(true);
    setDeviceError(null);
    try {
      await api.updateTaskDeviceId(taskId, deviceValue.trim());
      message.success("设备 ID 已更新");
      setDeviceOpen(false);
      await reload();
    } catch (error) {
      // 台账校验失败等服务端拒绝：弹窗内保留服务端消息，任务原值不变（FR-010、SC-005）。
      const detail = error instanceof Error ? error.message : "设备 ID 更新失败";
      setDeviceError(detail);
      message.error(detail);
    } finally {
      setDeviceSaving(false);
    }
  }, [deviceValue, message, reload, taskId]);

  const openRebuildModal = useCallback(() => setRebuildOpen(true), []);
  const closeRebuildModal = useCallback(() => {
    setRebuildOpen(false);
    setRebuildRuleCodes([]);
  }, []);

  const rebuildIncremental = useCallback(async () => {
    if (rebuildRuleCodes.length === 0) return;
    setRebuilding(true);
    try {
      await api.rebuildTask(taskId, {
        mode: "incremental",
        confirmed: true,
        rule_codes: rebuildRuleCodes,
        trigger_source: "ui",
      });
      message.success("已受理增量重建");
      closeRebuildModal();
      await reload();
    } catch (error) {
      if (isSceneCleaned(toResourceError(error))) {
        closeRebuildModal();
      }
      reportActionError(error, "增量重建失败");
    } finally {
      setRebuilding(false);
    }
  }, [closeRebuildModal, message, rebuildRuleCodes, reload, reportActionError, taskId]);

  return {
    rerunAll,
    rerunOne,
    rebuild: {
      open: rebuildOpen,
      ruleCodes: rebuildRuleCodes,
      setRuleCodes: setRebuildRuleCodes,
      rebuilding,
      openModal: openRebuildModal,
      closeModal: closeRebuildModal,
      rebuild: rebuildIncremental,
    },
    device: {
      open: deviceOpen,
      value: deviceValue,
      setValue: setDeviceValue,
      saving: deviceSaving,
      error: deviceError,
      openModal: openDeviceModal,
      closeModal: closeDeviceModal,
      save: saveDeviceId,
    },
  };
}
