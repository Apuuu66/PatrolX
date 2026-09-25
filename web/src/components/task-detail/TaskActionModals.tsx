import { Alert, Input, Modal, Select } from "antd";
import type { RuleResult } from "../../api/http";

type RebuildModalProps = {
  open: boolean;
  confirming: boolean;
  rules: RuleResult[];
  ruleCodes: string[];
  onRuleCodesChange: (ruleCodes: string[]) => void;
  onCancel: () => void;
  onConfirm: () => void;
};

export function RebuildModal({
  open,
  confirming,
  rules,
  ruleCodes,
  onRuleCodesChange,
  onCancel,
  onConfirm,
}: RebuildModalProps) {
  return (
    <Modal
      title="增量重建"
      open={open}
      confirmLoading={confirming}
      okText="增量重建"
      okButtonProps={{ disabled: ruleCodes.length === 0 }}
      cancelText="取消"
      onCancel={onCancel}
      onOk={() => void onConfirm()}
    >
      <Alert
        type="warning"
        showIcon
        message="将强制重建解压现场"
        description="所选规则及其私有准备会重算，未选择规则结果保持不变。"
        className="task-detail-alert"
      />
      <Select
        mode="multiple"
        showSearch
        allowClear
        placeholder="选择要重建重跑的普通规则"
        className="task-rebuild-select"
        value={ruleCodes}
        onChange={onRuleCodesChange}
        options={rules.map((rule) => ({ value: rule.code, label: `${rule.name} (${rule.code})` }))}
      />
    </Modal>
  );
}

type DeviceModalProps = {
  open: boolean;
  value: string;
  saving: boolean;
  onChange: (value: string) => void;
  onCancel: () => void;
  onSave: () => void;
};

export function DeviceModal({ open, value, saving, onChange, onCancel, onSave }: DeviceModalProps) {
  return (
    <Modal
      title="修改设备 ID"
      open={open}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      onOk={() => void onSave()}
      onCancel={onCancel}
    >
      <Input
        value={value}
        maxLength={128}
        allowClear
        placeholder="输入设备 ID"
        onChange={(event) => onChange(event.target.value)}
      />
    </Modal>
  );
}
