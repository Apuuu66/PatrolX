import { Space, Tag } from "antd";
import { getRuleCategoryOptionsText } from "../utils/ruleCategories";
import type { RuleCategoryCount } from "../utils/ruleResults";

type RuleCategoryFilterProps = {
  categories: RuleCategoryCount[];
  value: string | null;
  onChange: (category: string | null) => void;
};

export function RuleCategoryFilter({ categories, value, onChange }: RuleCategoryFilterProps) {
  return (
    <Space size={6} wrap className="task-category-filter">
      <Tag.CheckableTag
        checked={value === null}
        onClick={() => onChange(null)}
        className="rule-category-chip"
      >
        全部
      </Tag.CheckableTag>
      {categories.map((category) => (
        <Tag.CheckableTag
          key={category.value}
          checked={value === category.value}
          onClick={() => onChange(category.value)}
          className="rule-category-chip"
        >
          {getRuleCategoryOptionsText(category.value, category.count)}
        </Tag.CheckableTag>
      ))}
    </Space>
  );
}
