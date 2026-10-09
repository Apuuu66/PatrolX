import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Flex, Tag } from "antd";
import { api, type DictsResponse } from "../api/http";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";

const DICT_LABELS: Record<string, string> = {
  province: "省份",
  operator: "运营商",
  product: "网元类型",
};

export function DictsPage() {
  const { message } = App.useApp();
  const [dicts, setDicts] = useState<DictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
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
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="数据字典"
        description="省份、运营商与网元类型等基础选项"
      />
      {loading ? (
        <PageSkeleton rows={3} />
      ) : !dicts ? (
        <LoadErrorState
          description={loadError ?? "字典加载失败"}
          onRetry={() => void load()}
        />
      ) : (
        Object.entries(dicts).filter(([name]) => name in DICT_LABELS).map(([name, items]) => (
          <Card key={name} title={DICT_LABELS[name] ?? name} size="small" style={{ marginBottom: 16 }}>
            {(items ?? []).length === 0 ? (
              <EmptyState
                description="字典由部署配置维护，暂无可用选项"
                action={<Button onClick={() => void load()}>刷新字典</Button>}
              />
            ) : (
              <Flex wrap="wrap" gap={4}>
                {(items ?? []).map((d) => (
                  <Tag key={d.code} style={{ marginInlineEnd: 0 }}>
                    {d.name || d.code}
                  </Tag>
                ))}
              </Flex>
            )}
          </Card>
        ))
      )}
    </div>
  );
}
