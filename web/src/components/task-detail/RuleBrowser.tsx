import { useMemo, useState } from "react";
import { Card, Collapse, Empty, Input, Select, Space } from "antd";
import type { RuleResult } from "../../api/http";
import { RuleCategoryFilter } from "../RuleCategoryFilter";
import { RuleResultTable } from "../RuleResultTable";
import { getRuleCategoryLabel } from "../../utils/ruleCategories";
import {
  groupRulesByCategory,
  hasAttentionRules,
  type RuleCategoryCount,
  type RuleSortMode,
} from "../../utils/ruleResults";
import type { StatusFilter } from "../../utils/taskFilter";

type RuleBrowserProps = {
  categoryCounts: RuleCategoryCount[];
  sortedRules: RuleResult[];
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
  categoryCounts,
  sortedRules,
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
  const groups = useMemo(() => groupRulesByCategory(sortedRules), [sortedRules]);
  const anomalyKeys = useMemo(
    () => groups.filter((group) => hasAttentionRules(group.rules)).map((group) => group.value),
    [groups],
  );
  const [expandedKeys, setExpandedKeys] = useState<string[] | null>(null);
  // 默认展开含异常的分组；没有异常或正在搜索时展开全部分组，
  // 避免全通过任务的证据与搜索结果被折叠隐藏（FR-017、FR-030）。
  const defaultKeys = useMemo(() => {
    if (search.trim() || anomalyKeys.length === 0) {
      return groups.map((group) => group.value);
    }
    return anomalyKeys;
  }, [anomalyKeys, groups, search]);
  // 用户手动折叠/展开后以用户选择为准。
  const activeKeys = expandedKeys ?? defaultKeys;
  const emptyDescription =
    statusFilter || search.trim() ? "暂无匹配的规则结果" : "暂无规则结果";

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
