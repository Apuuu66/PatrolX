import { Typography } from "antd";

interface ResourceNameCellProps {
  name?: string | null;
  id?: string | null;
}

/** 中文名优先展示；名称缺失时回退 ID，ID 作为次要信息保留。 */
export function ResourceNameCell({ name, id }: ResourceNameCellProps) {
  const displayName = name || id;
  if (!displayName) return <>-</>;
  return (
    <div>
      <div>{displayName}</div>
      {name && id && name !== id ? (
        <Typography.Text type="secondary">{id}</Typography.Text>
      ) : null}
    </div>
  );
}
