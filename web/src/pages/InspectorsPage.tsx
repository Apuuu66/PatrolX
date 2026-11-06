import { useCallback, useEffect, useRef, useState, type Key } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";

import {
  api,
  type DictItem,
  type KpiRuleAssignmentBatchRequestV6,
  type KpiRuleNetworkAssignmentQueryV6,
  type KpiRuleNetworkAssignmentV6,
  type KpiRuleAssignmentWriteResultV6,
} from "../api/http";
import { Table } from "../components/ResizableTable";
import { PageHeader } from "../components/PageHeader";
import { DensitySegmented } from "../components/DensitySegmented";
import { useTableDensity } from "../hooks/useTableDensity";
import { TABULAR_NUMERIC_CLASS, getRelativeTimeDisplay } from "../utils/timeDisplay";
import { EmptyState, LoadErrorState } from "../components/PageState";

/** 数据分页默认 10 条（宪法"数据分页默认"）。 */
const DEFAULT_PAGE_SIZE = 10;

const CATEGORY_LABELS: Record<string, string> = {
  log: "日志",
  kpi: "KPI",
  traffic: "话统",
  alarm: "告警",
  config: "配置",
  resource: "资源",
  other: "其他",
};

type AssignmentFilter = `network:${string}` | "unassigned";

interface SingleUnassignPending {
  kind: "single";
  rule: KpiRuleNetworkAssignmentV6;
  networkElementTypes: string[];
}

interface BatchUnassignPending {
  kind: "batch";
  items: KpiRuleNetworkAssignmentV6[];
  networkElementTypes: string[];
}

type UnassignPending = SingleUnassignPending | BatchUnassignPending;

function networkTypeOfFilter(filter: AssignmentFilter | undefined): string | undefined {
  return filter?.startsWith("network:") ? filter.slice("network:".length) : undefined;
}

function sameNetworkTypes(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((value) => rightSet.has(value));
}

function applyWriteResult(
  current: KpiRuleNetworkAssignmentV6,
  result: KpiRuleAssignmentWriteResultV6,
): KpiRuleNetworkAssignmentV6 {
  return {
    ...current,
    assignment_state: result.assignment_state,
    network_element_types: result.network_element_types,
    revision: result.revision,
    updated_at: result.updated_at,
  };
}

export function InspectorsPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<KpiRuleNetworkAssignmentV6[]>([]);
  const [networkElementTypes, setNetworkElementTypes] = useState<DictItem[]>([]);
  const [total, setTotal] = useState(0);
  const [globalRevision, setGlobalRevision] = useState(0);
  const [canWrite, setCanWrite] = useState(false);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [assignmentFilter, setAssignmentFilter] = useState<AssignmentFilter | undefined>();
  const [search, setSearch] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedRuleCodes, setSelectedRuleCodes] = useState<Key[]>([]);
  const [editingRule, setEditingRule] = useState<KpiRuleNetworkAssignmentV6 | null>(null);
  const [editingNetworkTypes, setEditingNetworkTypes] = useState<string[]>([]);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchRules, setBatchRules] = useState<KpiRuleNetworkAssignmentV6[]>([]);
  const [batchNetworkTypes, setBatchNetworkTypes] = useState<string[]>([]);
  const [savingSingle, setSavingSingle] = useState(false);
  const [savingBatch, setSavingBatch] = useState(false);
  const [unassignPending, setUnassignPending] = useState<UnassignPending | null>(null);
  const requestSeq = useRef(0);
  const { density, tableSize, setDensity } = useTableDensity();

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    const networkElementType = networkTypeOfFilter(assignmentFilter);
    const query: KpiRuleNetworkAssignmentQueryV6 = {
      page,
      page_size: pageSize,
      ...(networkElementType ? { network_element_type: networkElementType } : {}),
      ...(assignmentFilter === "unassigned" ? { assignment_state: "unassigned" } : {}),
      ...(search ? { search } : {}),
    };

    setLoading(true);
    setLoadError(null);
    try {
      const result = await api.listKpiRuleNetworkAssignmentsV6(query);
      if (seq !== requestSeq.current) return;
      setItems(result.items);
      setTotal(result.total);
      setGlobalRevision(result.global_revision);
      setCanWrite(result.can_write);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      const text = err instanceof Error ? err.message : "规则归属加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [assignmentFilter, message, page, pageSize, search]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let active = true;
    void api.listDicts()
      .then((result) => {
        if (active) setNetworkElementTypes(result.product ?? []);
      })
      .catch((err: unknown) => {
        if (!active) return;
        message.error(err instanceof Error ? err.message : "网元类型加载失败");
      });
    return () => {
      active = false;
    };
  }, [message]);

  useEffect(() => {
    setSelectedRuleCodes([]);
  }, [assignmentFilter, page, pageSize, search]);

  const networkTypeOptions = networkElementTypes.map((item) => ({
    label: item.code,
    value: item.code,
  }));

  const openSingleEditor = (rule: KpiRuleNetworkAssignmentV6) => {
    setEditingRule(rule);
    setEditingNetworkTypes([...rule.network_element_types]);
  };

  const closeSingleEditor = () => {
    if (savingSingle) return;
    setEditingRule(null);
    setEditingNetworkTypes([]);
  };

  const saveSingleAssignment = async (
    rule: KpiRuleNetworkAssignmentV6,
    nextNetworkTypes: string[],
    confirmUnassign: boolean,
  ) => {
    setSavingSingle(true);
    try {
      const updated = await api.updateKpiRuleNetworkAssignmentV6(rule.rule_code, {
        expected_revision: rule.revision,
        network_element_types: nextNetworkTypes,
        confirm_unassign: confirmUnassign,
      });
      setItems((current) => current.map((item) => (
        item.rule_code === updated.rule_code ? applyWriteResult(item, updated) : item
      )));
      setGlobalRevision(updated.global_revision);
      setEditingRule(null);
      setEditingNetworkTypes([]);
      setUnassignPending(null);
      message.success(`规则 ${rule.rule_code} 的网元归属已更新`);
    } catch (err) {
      // revision 冲突等写失败必须保留服务端错误，不更新本地归属。
      message.error(err instanceof Error ? err.message : "规则归属保存失败");
    } finally {
      setSavingSingle(false);
    }
  };

  const requestSingleSave = () => {
    if (!editingRule) return;
    if (sameNetworkTypes(editingRule.network_element_types, editingNetworkTypes)) {
      message.info("规则归属没有变化");
      closeSingleEditor();
      return;
    }
    if (editingNetworkTypes.length === 0 && editingRule.network_element_types.length > 0) {
      setUnassignPending({
        kind: "single",
        rule: editingRule,
        networkElementTypes: [],
      });
      return;
    }
    void saveSingleAssignment(editingRule, editingNetworkTypes, editingNetworkTypes.length === 0);
  };

  const openBatchEditor = () => {
    const selected = new Set(selectedRuleCodes.map(String));
    const rules = items.filter((item) => selected.has(item.rule_code));
    setBatchRules(rules);
    setBatchNetworkTypes([]);
    setBatchOpen(true);
  };

  const closeBatchEditor = () => {
    if (savingBatch) return;
    setBatchOpen(false);
    setBatchRules([]);
    setBatchNetworkTypes([]);
  };

  const saveBatchAssignment = async (
    rules: KpiRuleNetworkAssignmentV6[],
    nextNetworkTypes: string[],
    confirmUnassign: boolean,
  ) => {
    const changedRules = rules.filter(
      (rule) => !sameNetworkTypes(rule.network_element_types, nextNetworkTypes),
    );
    if (changedRules.length === 0) {
      message.info("所选规则归属没有变化");
      return;
    }

    const payload: KpiRuleAssignmentBatchRequestV6 = {
      items: changedRules.map((rule) => ({
        rule_code: rule.rule_code,
        expected_revision: rule.revision,
        network_element_types: nextNetworkTypes,
        confirm_unassign: confirmUnassign,
      })),
    };

    setSavingBatch(true);
    try {
      const result = await api.batchUpdateKpiRuleNetworkAssignmentsV6(payload);
      const updatedByCode = new Map(result.items.map((item) => [item.rule_code, item]));
      setItems((current) => current.map((item) => {
        const updated = updatedByCode.get(item.rule_code);
        return updated ? applyWriteResult(item, updated) : item;
      }));
      setGlobalRevision(result.global_revision);
      setBatchOpen(false);
      setBatchRules([]);
      setBatchNetworkTypes([]);
      setUnassignPending(null);
      setSelectedRuleCodes([]);
      message.success(`已更新 ${result.items.length} 条规则归属`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "批量保存规则归属失败");
    } finally {
      setSavingBatch(false);
    }
  };

  const requestBatchSave = () => {
    const changedRules = batchRules.filter(
      (rule) => !sameNetworkTypes(rule.network_element_types, batchNetworkTypes),
    );
    if (changedRules.length === 0) {
      message.info("所选规则归属没有变化");
      return;
    }
    const clearsAssignments = changedRules.some(
      (rule) => rule.network_element_types.length > 0 && batchNetworkTypes.length === 0,
    );
    if (clearsAssignments) {
      setUnassignPending({
        kind: "batch",
        items: changedRules,
        networkElementTypes: [],
      });
      return;
    }
    void saveBatchAssignment(changedRules, batchNetworkTypes, batchNetworkTypes.length === 0);
  };

  const confirmUnassign = () => {
    if (!unassignPending) return;
    if (unassignPending.kind === "single") {
      void saveSingleAssignment(
        unassignPending.rule,
        unassignPending.networkElementTypes,
        true,
      );
      return;
    }
    void saveBatchAssignment(unassignPending.items, unassignPending.networkElementTypes, true);
  };

  const columns: ColumnsType<KpiRuleNetworkAssignmentV6> = [
    {
      title: "规则编码",
      dataIndex: "rule_code",
      width: 220,
      render: (value: string) => (
        <Typography.Text code copyable={{ text: value }} className="inspectors-code">
          {value}
        </Typography.Text>
      ),
    },
    { title: "名称", dataIndex: "name", width: 180, ellipsis: true },
    {
      title: "类别",
      dataIndex: "category",
      width: 100,
      render: (value: string) => <Tag>{CATEGORY_LABELS[value] ?? value}</Tag>,
    },
    {
      title: "归属网元类型",
      dataIndex: "network_element_types",
      key: "network_element_types",
      width: 230,
      render: (values: string[]) => values.length > 0 ? (
        <Space size={[4, 4]} wrap>
          {values.map((value) => <Tag color="blue" key={value}>{value}</Tag>)}
        </Space>
      ) : (
        <Space size={[4, 4]} wrap>
          <Tag>未归属</Tag>
          <Typography.Text type="secondary">待配置 · 不执行</Typography.Text>
        </Space>
      ),
    },
    { title: "优先级", dataIndex: "priority", width: 90, render: (value: number) => `P${value}` },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 190,
      sorter: (a, b) => (a.updated_at ?? "").localeCompare(b.updated_at ?? ""),
      render: (value: string | null | undefined) => {
        const display = value ? getRelativeTimeDisplay(value) : { text: "从未更新", title: "" };
        return (
          <Tooltip title={display.title || undefined}>
            <span className={TABULAR_NUMERIC_CLASS} data-testid="rule-assignment-updated-at">
              {display.text}
            </span>
          </Tooltip>
        );
      },
    },
    ...(canWrite ? [{
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: KpiRuleNetworkAssignmentV6) => (
        <Button size="small" onClick={() => openSingleEditor(record)}>
          编辑归属
        </Button>
      ),
    }] : []),
  ];

  const hasActiveFilter = assignmentFilter !== undefined || search.length > 0;

  return (
    <>
      <PageHeader
        title="规则网元归属"
        description="无公共规则；同一规则可归属多个网元类型。未归属规则待配置且不执行，也不会生成 skip 结果。"
      />
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type={canWrite ? "info" : "warning"}
          showIcon
          message={canWrite ? "归属变更只影响后续启动或显式重建的任务" : "只读"}
          description={canWrite
            ? "规则在任务启动时冻结归属范围，运行中的任务不受本次配置变更影响。"
            : "当前仅可查看规则归属，不能修改或批量设置。"}
        />
        <Card
          title={<Typography.Text strong>规则归属清单</Typography.Text>}
          extra={(
            <Space wrap>
              <DensitySegmented value={density} onChange={setDensity} />
              <Select
                allowClear
                aria-label="归属筛选"
                placeholder="归属筛选"
                value={assignmentFilter}
                style={{ width: 140 }}
                options={[
                  { value: "unassigned", label: "未归属" },
                  ...networkTypeOptions.map((option) => ({
                    value: `network:${option.value}`,
                    label: option.label,
                  })),
                ]}
                onChange={(value) => {
                  setPage(1);
                  setAssignmentFilter(value as AssignmentFilter | undefined);
                }}
              />
              <Input.Search
                placeholder="搜索编码 / 名称"
                allowClear
                style={{ width: 240 }}
                onSearch={(value) => {
                  setPage(1);
                  setSearch(value.trim());
                }}
              />
              {canWrite ? (
                <Button
                  type="primary"
                  disabled={selectedRuleCodes.length === 0}
                  onClick={openBatchEditor}
                >
                  批量设置归属{selectedRuleCodes.length > 0 ? `（${selectedRuleCodes.length}）` : ""}
                </Button>
              ) : null}
            </Space>
          )}
        >
          {loadError ? (
            <LoadErrorState description={loadError} onRetry={() => void load()} retrying={loading} />
          ) : (
            <Table
              className={`inspectors-table density-${density}`}
              rowKey="rule_code"
              size={tableSize}
              loading={loading}
              dataSource={items}
              columns={columns}
              rowSelection={canWrite ? {
                selectedRowKeys: selectedRuleCodes,
                onChange: (keys) => setSelectedRuleCodes(keys),
              } : undefined}
              locale={{
                emptyText: (
                  <EmptyState
                    description={hasActiveFilter ? "没有符合筛选条件的规则" : "暂无已注册规则"}
                    action={hasActiveFilter ? (
                      <Button
                        onClick={() => {
                          setPage(1);
                          setAssignmentFilter(undefined);
                          setSearch("");
                        }}
                      >
                        清除筛选
                      </Button>
                    ) : (
                      <Button onClick={() => void load()}>刷新列表</Button>
                    )}
                  />
                ),
              }}
              pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: true,
                showTotal: (value) => `共 ${value} 条 · 全局版本 ${globalRevision}`,
                onChange: (nextPage, nextPageSize) => {
                  setPage(nextPageSize === pageSize ? nextPage : 1);
                  setPageSize(nextPageSize);
                },
              }}
            />
          )}
        </Card>
      </Space>

      <Modal
        open={editingRule !== null}
        title="编辑规则归属"
        okText="保存归属"
        cancelText="取消"
        confirmLoading={savingSingle}
        onOk={requestSingleSave}
        onCancel={closeSingleEditor}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text>
            规则 <Typography.Text code>{editingRule?.rule_code}</Typography.Text>
          </Typography.Text>
          <Typography.Text type="secondary">
            选择一个或多个网元类型；清空全部归属后规则将停止参与后续任务。
          </Typography.Text>
          <Checkbox.Group
            aria-label="网元类型"
            options={networkTypeOptions}
            value={editingNetworkTypes}
            onChange={(values) => setEditingNetworkTypes(values.map(String))}
          />
        </Space>
      </Modal>

      <Modal
        open={batchOpen}
        title="批量设置规则归属"
        okText="保存批量归属"
        cancelText="取消"
        confirmLoading={savingBatch}
        onOk={requestBatchSave}
        onCancel={closeBatchEditor}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text>
            将对已选择的 {batchRules.length} 条规则应用同一组网元类型，仅提交归属发生变化的规则。
          </Typography.Text>
          <Typography.Text type="secondary">
            清空归属会使规则停止参与后续任务；批量写入失败时整批不会生效。
          </Typography.Text>
          <Checkbox.Group
            aria-label="批量网元类型"
            options={networkTypeOptions}
            value={batchNetworkTypes}
            onChange={(values) => setBatchNetworkTypes(values.map(String))}
          />
        </Space>
      </Modal>

      <Modal
        open={unassignPending !== null}
        title="确认清空规则归属"
        okText="确认清空"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        confirmLoading={savingSingle || savingBatch}
        onOk={confirmUnassign}
        onCancel={() => setUnassignPending(null)}
      >
        <Space direction="vertical" size={8}>
          <Typography.Text strong>
            清空后，相关规则将停止参与后续任务，且不会生成 skip 结果。
          </Typography.Text>
          <Typography.Text type="secondary">
            {unassignPending?.kind === "batch"
              ? `本次将清空 ${unassignPending.items.length} 条规则的归属。`
              : `规则 ${unassignPending?.kind === "single" ? unassignPending.rule.rule_code : ""} 将进入待配置状态。`}
          </Typography.Text>
          <Typography.Text type="secondary">
            历史结果不会改写；如需重新执行，请在归属配置完成后重建任务。
          </Typography.Text>
        </Space>
      </Modal>
    </>
  );
}
