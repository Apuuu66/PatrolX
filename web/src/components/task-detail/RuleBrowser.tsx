import { Card, Input, Select, Space } from "antd";
import type { RuleResult } from "../../api/http";
import { RuleCategoryFilter } from "../RuleCategoryFilter";
import { RuleResultTable } from "../RuleResultTable";
import type { RuleCategoryCount, RuleSortMode } from "../../utils/ruleResults";
import type { StatusFilter } from "../../utils/taskFilter";

type RuleBrowserProps = {
  attentionRules: RuleResult[];
  attentionHiddenCount: number;
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
  attentionRules,
  attentionHiddenCount,
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
  const attentionTotal = attentionRules.length + attentionHiddenCount;

  return (
    <>
      {attentionRules.length > 0 && (
        <Card
          title={`重点关注（${attentionTotal}）`}
          className="task-detail-panel"
          styles={{ header: { borderColor: "#ffccc7" } }}
        >
          <RuleResultTable rules={attentionRules} onOpenRule={onOpenRule} onRerunRule={onRerunRule} />
        </Card>
      )}

      <Card
        title="全部规则"
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
        <RuleCategoryFilter
          categories={categoryCounts}
          value={category}
          onChange={onCategoryChange}
        />
        <RuleResultTable
          rules={sortedRules}
          focusCategory={category}
          emptyDescription={
            statusFilter || search.trim()
              ? "暂无匹配的规则结果"
              : "暂无规则结果"
          }
          onOpenRule={onOpenRule}
          onRerunRule={onRerunRule}
        />
      </Card>
    </>
  );
}
