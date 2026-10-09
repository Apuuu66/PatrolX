import { useMemo, useState } from "react";
import { Button, Card, Collapse, Empty, Input, Select, Space, Typography } from "antd";
import type { RuleResult } from "../../api/http";
import { RuleCategoryFilter } from "../RuleCategoryFilter";
import { RuleResultTable } from "../RuleResultTable";
import { getRuleCategoryLabel } from "../../utils/ruleCategories";
import {
  getRuleCategoryOptions,
  groupRulesByCategory,
  hasAttentionRules,
  type RuleSortMode,
} from "../../utils/ruleResults";
import type { StatusFilter } from "../../utils/taskFilter";

type RuleBrowserProps = {
  sortedRules: RuleResult[];
  /** 已在「重点关注」展示的规则 code，默认从「全部规则」排除（FR-011、R7）。 */
  attentionRuleCodes?: readonly string[];
  /** 分类筛选项的全量规则来源；缺省时退回 `sortedRules`。 */
  categorySourceRules?: readonly RuleResult[];
  statusFilter: StatusFilter;
  search: string;
  sort: RuleSortMode;
  category: string | null;
  onSearchChange: (search: string) => void;
  onSortChange: (sort: RuleSortMode) => void;
  onCategoryChange: (category: string | null) => void;
  onOpenRule: (ruleCode: string) => void;
  onRerunRule: (ruleCode: string) => void;
};

export function RuleBrowser({
  sortedRules,
  attentionRuleCodes = [],
  categorySourceRules = sortedRules,
  statusFilter,
  search,
  sort,
  category,
  onSearchChange,
  onSortChange,
  onCategoryChange,
  onOpenRule,
  onRerunRule,
}: RuleBrowserProps) {
  const [includeAttention, setIncludeAttention] = useState(false);
  const attentionSet = useMemo(() => new Set(attentionRuleCodes), [attentionRuleCodes]);
  const searching = search.trim().length > 0;
  // 状态 / 分类 / 搜索筛选生效时保持既有筛选语义，不做去重（R7）。
  const filtering = Boolean(statusFilter) || Boolean(category) || searching;

  // 默认排除已在「重点关注」中的规则，避免同一规则等权重复（FR-011、SC-004）。
  const hiddenAttentionCodes = useMemo(() => {
    if (filtering || includeAttention) return new Set<string>();
    return new Set(
      sortedRules.filter((rule) => attentionSet.has(rule.code)).map((rule) => rule.code),
    );
  }, [attentionSet, filtering, includeAttention, sortedRules]);

  const displayRules = useMemo(
    () =>
      hiddenAttentionCodes.size === 0
        ? sortedRules
        : sortedRules.filter((rule) => !hiddenAttentionCodes.has(rule.code)),
    [hiddenAttentionCodes, sortedRules],
  );

  // 分类计数沿用既有筛选语义：按全量规则枚举分类（计数为 0 仍展示），
  // 计数基于状态 / 搜索筛选结果，不受去重影响（R7 不改变筛选语义）。
  const categoryCounts = useMemo(
    () => getRuleCategoryOptions([...categorySourceRules], sortedRules),
    [categorySourceRules, sortedRules],
  );
  const groups = useMemo(() => groupRulesByCategory(displayRules), [displayRules]);
  const anomalyKeys = useMemo(
    () => groups.filter((group) => hasAttentionRules(group.rules)).map((group) => group.value),
    [groups],
  );
  const [expandedKeys, setExpandedKeys] = useState<string[] | null>(null);
  // 默认展开含异常的分组；没有异常或正在搜索时展开全部分组，
  // 避免全通过任务的证据与搜索结果被折叠隐藏（FR-017、FR-030）。
  const defaultKeys = useMemo(() => {
    if (searching || anomalyKeys.length === 0) {
      return groups.map((group) => group.value);
    }
    return anomalyKeys;
  }, [anomalyKeys, groups, searching]);
  // 用户手动折叠/展开后以用户选择为准。
  const activeKeys = expandedKeys ?? defaultKeys;
  const emptyDescription =
    groups.length === 0 && hiddenAttentionCodes.size > 0
      ? "规则都已在上方重点关注，可展开查看"
      : statusFilter || searching
        ? "暂无匹配的规则结果"
        : "暂无规则结果";

  return (
    <Card
      title="全部规则"
      className="task-detail-panel"
      data-testid="rule-browser"
      styles={{ body: { paddingTop: 8 } }}
      extra={
        <Space size={8} wrap>
          <Input
            aria-label="规则搜索"
            allowClear
            placeholder="搜索名称 / 编码"
            className="task-detail-search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
          <Select
            aria-label="规则排序"
            className="task-detail-sort"
            value={sort}
            options={[
              { value: "default", label: "默认排序" },
              { value: "severity", label: "严重度优先" },
            ]}
            onChange={onSortChange}
          />
        </Space>
      }
    >
      <RuleCategoryFilter categories={categoryCounts} value={category} onChange={onCategoryChange} />
      {hiddenAttentionCodes.size > 0 && (
        <div className="rule-browser-dedupe" data-testid="rule-browser-dedupe">
          <Typography.Text type="secondary">
            另有 {hiddenAttentionCodes.size} 条已在上方重点关注
          </Typography.Text>
          <Button
            type="link"
            size="small"
            data-testid="rule-browser-show-all"
            onClick={() => setIncludeAttention(true)}
          >
            显示全部
          </Button>
        </div>
      )}
      {includeAttention && !filtering && attentionSet.size > 0 && (
        <div className="rule-browser-dedupe" data-testid="rule-browser-show-all-active">
          <Typography.Text type="secondary">已包含重点关注中的规则</Typography.Text>
          <Button
            type="link"
            size="small"
            data-testid="rule-browser-hide-all"
            onClick={() => setIncludeAttention(false)}
          >
            只看其余规则
          </Button>
        </div>
      )}
      {groups.length === 0 ? (
        <Empty description={emptyDescription} />
      ) : (
        <Collapse
          className="rule-category-collapse"
          activeKey={activeKeys}
          onChange={(keys) => setExpandedKeys(Array.isArray(keys) ? keys : [keys])}
          items={groups.map((group) => ({
            key: group.value,
            label: `${getRuleCategoryLabel(group.value)}（${group.rules.length}）`,
            children: (
              <RuleResultTable
                rules={group.rules}
                focusCategory={category}
                onOpenRule={onOpenRule}
                onRerunRule={onRerunRule}
              />
            ),
          }))}
        />
      )}
    </Card>
  );
}
