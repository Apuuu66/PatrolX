import { useCallback, useState } from "react";
import { App } from "antd";
import { api } from "../api/http";

export function useTaskActions(taskId: string, reload: () => Promise<void>) {
  const { message } = App.useApp();
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [rebuildRuleCodes, setRebuildRuleCodes] = useState<string[]>([]);
  const [rebuilding, setRebuilding] = useState(false);
  const [deviceOpen, setDeviceOpen] = useState(false);
  const [deviceValue, setDeviceValue] = useState("");
  const [deviceSaving, setDeviceSaving] = useState(false);

  const rerunAll = useCallback(async () => {
    try {
      await api.rerunTask(taskId);
      message.success("已受理全量重跑");
      await reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重跑失败");
    }
  }, [message, reload, taskId]);

  const rerunOne = useCallback(async (ruleCode: string) => {
    try {
      await api.rerunTask(taskId, [ruleCode]);
      message.success(`已受理重跑 ${ruleCode}`);
      await reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重跑失败");
    }
  }, [message, reload, taskId]);

  const openDeviceModal = useCallback((value: string) => {
    setDeviceValue(value);
    setDeviceOpen(true);
  }, []);

  const closeDeviceModal = useCallback(() => setDeviceOpen(false), []);

  const saveDeviceId = useCallback(async () => {
    setDeviceSaving(true);
    try {
      await api.updateTaskDeviceId(taskId, deviceValue.trim());
      message.success("设备 ID 已更新");
      setDeviceOpen(false);
      await reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "设备 ID 更新失败");
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
      message.error(error instanceof Error ? error.message : "增量重建失败");
    } finally {
      setRebuilding(false);
    }
  }, [closeRebuildModal, message, rebuildRuleCodes, reload, taskId]);

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
      openModal: openDeviceModal,
      closeModal: closeDeviceModal,
      save: saveDeviceId,
    },
  };
}
