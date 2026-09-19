import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  api,
  type KpiCapacityRulePageV4,
  type KpiCapacityRuleV4,
  type KpiCapacityStatusV4,
  type KpiCapacitySemanticsV4,
  type KpiCommonConfigV4,
  type KpiConfigAuditPageV4,
  type KpiConfigAuditV4,
  type KpiDisplayRulePageV4,
  type KpiDisplayRuleV4,
  type KpiDisplayRoleV4,
  type KpiRegisteredDomainV4,
} from "../api/http";

const DOMAINS: { value: KpiRegisteredDomainV4; label: string }[] = [
  { value: "call", label: "呼叫" },
  { value: "api", label: "接口" },
  { value: "media", label: "媒体" },
];

const CAPACITY_STATUS: { value: KpiCapacityStatusV4; label: string }[] = [
  { value: "confirmed", label: "已确认" },
  { value: "unknown", label: "未知" },
];

const CAPACITY_SEMANTICS: { value: KpiCapacitySemanticsV4; label: string }[] = [
  { value: "peak", label: "峰值" },
  { value: "concurrency", label: "并发" },
  { value: "gauge", label: "仪表" },
];

const DISPLAY_ROLES: { value: KpiDisplayRoleV4; label: string }[] = [
  { value: "highlight", label: "重点展示" },
  { value: "context", label: "上下文" },
];

export function KpiCapacityRuleEditor({ operator, onChanged }: { operator: string; onChanged?: () => void }) {
  const { message } = App.useApp();
  const [pageData, setPageData] = useState<KpiCapacityRulePageV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPageData(await api.listKpiCapacityRulesV4({ page: 1, page_size: 200 }));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "容量规则加载失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    const values = await form.validateFields();
    const payload = {
      source_name: values.source_name.trim(),
      metric_key: values.metric_key.trim(),
      domain: values.domain ?? null,
      semantics: values.status === "confirmed" ? values.semantics ?? null : null,
      status: values.status,
      operator,
    };
    setSaving(true);
    try {
      if (values.id) await api.updateKpiCapacityRuleV4(values.id, payload);
      else await api.createKpiCapacityRuleV4(payload);
      message.success("容量规则已保存");
      setOpen(false);
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (record: KpiCapacityRuleV4) => {
    try {
      await api.deleteKpiCapacityRuleV4(record.id);
      message.success("容量规则已删除");
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const columns: ColumnsType<KpiCapacityRuleV4> = [
    { title: "源列名", dataIndex: "source_name", width: 180, ellipsis: true },
    { title: "指标 Key", dataIndex: "metric_key", ellipsis: true },
    { title: "业务域", dataIndex: "domain", width: 90, render: (value) => value ?? "-" },
    { title: "语义", dataIndex: "semantics", width: 100, render: (value) => value ?? "-" },
    { title: "状态", dataIndex: "status", width: 100 },
    {
      title: "操作",
      key: "actions",
      width: 130,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => { form.setFieldsValue(record); setOpen(true); }}>
            编辑
          </Button>
          <Button size="small" type="link" danger onClick={() => void remove(record)}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <Card title="容量规则" extra={<Button type="primary" onClick={() => { form.resetFields(); form.setFieldsValue({ status: "confirmed" }); setOpen(true); }}>新增</Button>} styles={{ body: { paddingTop: 8 } }}>
      <Table rowKey="id" size="small" loading={loading} columns={columns} dataSource={pageData?.items ?? []} pagination={false} />
      <Modal title="容量规则" open={open} confirmLoading={saving} okText="保存" cancelText="取消" onOk={() => void submit()} onCancel={() => setOpen(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="source_name" label="源列名" rules={[{ required: true, message: "请输入源列名" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="metric_key" label="指标 Key" rules={[{ required: true, message: "请输入指标 Key" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="domain" label="业务域（可选）">
            <Select allowClear options={DOMAINS} />
          </Form.Item>
          <Form.Item name="status" label="状态" rules={[{ required: true }]}>
            <Select options={CAPACITY_STATUS} />
          </Form.Item>
          <Form.Item name="semantics" label="容量语义">
            <Select allowClear options={CAPACITY_SEMANTICS} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

export function KpiDisplayRuleEditor({ operator, onChanged }: { operator: string; onChanged?: () => void }) {
  const { message } = App.useApp();
  const [pageData, setPageData] = useState<KpiDisplayRulePageV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPageData(await api.listKpiDisplayRulesV4({ page: 1, page_size: 200 }));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "展示规则加载失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    const values = await form.validateFields();
    const payload = { ...values, metric_key: values.metric_key.trim(), operator };
    setSaving(true);
    try {
      if (values.id) await api.updateKpiDisplayRuleV4(values.id, payload);
      else await api.createKpiDisplayRuleV4(payload);
      message.success("展示规则已保存");
      setOpen(false);
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (record: KpiDisplayRuleV4) => {
    try {
      await api.deleteKpiDisplayRuleV4(record.id);
      message.success("展示规则已删除");
      await load();
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const columns: ColumnsType<KpiDisplayRuleV4> = [
    { title: "业务域", dataIndex: "domain", width: 100 },
    { title: "指标 Key", dataIndex: "metric_key", ellipsis: true },
    { title: "展示角色", dataIndex: "role", width: 120 },
    {
      title: "操作",
      key: "actions",
      width: 130,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => { form.setFieldsValue(record); setOpen(true); }}>编辑</Button>
          <Button size="small" type="link" danger onClick={() => void remove(record)}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <Card title="展示规则" extra={<Button type="primary" onClick={() => { form.resetFields(); setOpen(true); }}>新增</Button>} styles={{ body: { paddingTop: 8 } }}>
      <Table rowKey="id" size="small" loading={loading} columns={columns} dataSource={pageData?.items ?? []} pagination={false} />
      <Modal title="展示规则" open={open} confirmLoading={saving} okText="保存" cancelText="取消" onOk={() => void submit()} onCancel={() => setOpen(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="domain" label="业务域" rules={[{ required: true }]}>
            <Select options={DOMAINS} />
          </Form.Item>
          <Form.Item name="metric_key" label="指标 Key" rules={[{ required: true, message: "请输入指标 Key" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role" label="展示角色" rules={[{ required: true }]}>
            <Select options={DISPLAY_ROLES} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

export function KpiCommonConfigEditor({ operator, onChanged }: { operator: string; onChanged?: () => void }) {
  const { message } = App.useApp();
  const [config, setConfig] = useState<KpiCommonConfigV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    api.getKpiCommonConfigV4()
      .then((value) => {
        setConfig(value);
        form.setFieldsValue(value);
      })
      .catch((err) => message.error(err instanceof Error ? err.message : "公共配置加载失败"))
      .finally(() => setLoading(false));
  }, [form, message]);

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const updated = await api.updateKpiCommonConfigV4({ ...values, operator });
      setConfig(updated);
      message.success("公共配置已保存");
      onChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="公共配置" styles={{ body: { paddingTop: 16 } }}>
      <Form form={form} layout="vertical" disabled={loading} style={{ maxWidth: 680 }}>
        <Form.Item name="input_timezone" label="输入时区" rules={[{ required: true, message: "请输入 IANA 时区" }]}>
          <Input placeholder="Asia/Shanghai" />
        </Form.Item>
        <Form.Item name="max_files" label="每个业务域最大文件数" rules={[{ required: true }]}>
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="max_records" label="每个业务域最大记录数" rules={[{ required: true }]}>
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Button type="primary" loading={saving} onClick={() => void submit()}>保存</Button>
        {config && (
          <div style={{ marginTop: 8, color: "rgba(0,0,0,0.45)" }}>
            更新时间：{dayjs(config.updated_at).format("YYYY-MM-DD HH:mm:ss")}；配置版本：{config.rule_config_version}
          </div>
        )}
      </Form>
    </Card>
  );
}

export function KpiConfigAuditTable() {
  const [pageData, setPageData] = useState<KpiConfigAuditPageV4 | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const load = useCallback(async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    try {
      setPageData(await api.listKpiConfigAuditsV4({ page: nextPage, page_size: nextPageSize }));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<KpiConfigAuditV4> = [
    { title: "实体", dataIndex: "entity_type", width: 130 },
    { title: "Key", dataIndex: "entity_key", ellipsis: true },
    { title: "操作", dataIndex: "operation", width: 90 },
    { title: "操作人", dataIndex: "operator", width: 110 },
    { title: "结果", dataIndex: "result", width: 110 },
    { title: "配置版本", dataIndex: "rule_config_version", width: 100 },
    { title: "操作时间", dataIndex: "operated_at", width: 160, render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss") },
  ];

  return (
    <Card title="动态配置审计" styles={{ body: { paddingTop: 8 } }}>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={pageData?.items ?? []}
        pagination={{
          current: pageData?.page ?? page,
          pageSize: pageData?.page_size ?? pageSize,
          total: pageData?.total ?? 0,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
            void load(nextPage, nextPageSize);
          },
        }}
      />
    </Card>
  );
}
