import { useEffect, useState } from "react";
import { App, Card, Descriptions, Typography } from "antd";
import { api, type DictsResponse } from "../api/http";
import { LoadErrorState, PageSkeleton } from "../components/PageState";

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
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        setDicts(await api.listDicts());
      } catch (err) {
        const text = err instanceof Error ? err.message : "加载失败";
        setLoadError(text);
        message.error(text);
      } finally {
        setLoading(false);
      }
    })();
  }, [message]);

  if (loading) {
    return <PageSkeleton rows={3} />;
  }
  if (!dicts) {
    return (
      <LoadErrorState
        description={loadError ?? "字典加载失败"}
        onRetry={() => {
          void (async () => {
            setLoading(true);
            setLoadError(null);
            try {
              setDicts(await api.listDicts());
            } catch (err) {
              const text = err instanceof Error ? err.message : "加载失败";
              setLoadError(text);
              message.error(text);
            } finally {
              setLoading(false);
            }
          })();
        }}
        retrying={loading}
      />
    );
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
