import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getAssetDetail } from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { AssetDetail, Tab } from "../types";

export default function AssetTab({ tab }: { tab: Tab }) {
  const authSpace = useAuth((s) => s.currentSpace);
  const log = useWorkbench((s) => s.log);

  const assetId = useMemo(() => String(tab.payload?.assetId ?? ""), [tab.payload]);
  const payloadSpaceId = useMemo(
    () => (typeof tab.payload?.spacePublicId === "string" ? tab.payload.spacePublicId : undefined),
    [tab.payload],
  );
  const spacePublicId = payloadSpaceId ?? authSpace?.public_id;

  const [loading, setLoading] = useState(false);
  const [asset, setAsset] = useState<AssetDetail | null>(null);

  useEffect(() => {
    if (!assetId || !spacePublicId) {
      return;
    }
    let active = true;
    setLoading(true);

    getAssetDetail(spacePublicId, assetId)
      .then((data) => {
        if (!active) return;
        setAsset(data);
      })
      .catch((e: any) => {
        if (!active) return;
        log(`[Asset] load failed: ${e?.message ?? String(e)}`);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [assetId, spacePublicId, log]);

  if (!assetId) {
    return <div className="col">Missing asset id.</div>;
  }

  if (loading) {
    return <div className="col" style={{ padding: 12, color: "var(--text-muted)" }}>Loading asset...</div>;
  }

  if (!asset) {
    return <div className="col" style={{ padding: 12, color: "var(--text-muted)" }}>Asset not found.</div>;
  }

  return (
    <div className="col" style={{ gap: 10, minHeight: 0 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{asset.title}</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {asset.created_at} · nodes {asset.graph_snapshot?.node_count ?? 0} · edges {asset.graph_snapshot?.edge_count ?? 0}
          </div>
        </div>
        <span className="badge">asset</span>
      </div>

      <div className="md-preview" style={{ flex: 1 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{asset.content_markdown || "(empty)"}</ReactMarkdown>
      </div>
    </div>
  );
}
