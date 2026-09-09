import { useEffect, useState } from "react";
import { App, Card, Descriptions, Empty, Spin, Typography } from "antd";
import { api, type DictsResponse } from "../api/http";

const DICT_LABELS: Record<string, string> = {
  province: "省份",
  operator: "运营商",
  product: "产品形态",
  version: "版本",
};

export function DictsPage() {
  const { message } = App.useApp();
  const [dicts, setDicts] = useState<DictsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        setDicts(await api.listDicts());
      } catch (err) {
        message.error(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [message]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin />
      </div>
    );
  }
  if (!dicts) {
    return <Empty description="字典加载失败" />;
  }

  return (
    <div>
      <Typography.Title level={5} style={{ marginTop: 0 }}>
        预制数据字典
      </Typography.Title>
      {Object.entries(dicts).map(([name, items]) => (
        <Card key={name} title={DICT_LABELS[name] ?? name} size="small" style={{ marginBottom: 16 }}>
          {(items ?? []).length === 0 ? (
            <Typography.Text type="secondary">暂无数据</Typography.Text>
          ) : (
            <Descriptions
              size="small"
              column={3}
              bordered
              items={(items ?? []).map((d) => ({ key: d.code, label: d.name || d.code, children: d.code }))}
            />
          )}
        </Card>
      ))}
    </div>
  );
}
