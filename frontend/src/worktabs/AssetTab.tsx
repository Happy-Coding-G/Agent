import { Tab } from "../types";
import { useMemo } from "react";

export default function AssetTab({ tab }: { tab: Tab }) {
  const assetId = useMemo(() => String(tab.payload?.assetId ?? ""), [tab.payload]);

  return (
    <div className="col">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="badge">asset detail</span>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>id: {assetId}</span>
      </div>

      <div className="kv">
        <div className="k">Name</div><div className="v">(load from /assets/{assetId})</div>
      </div>
      <div className="kv">
        <div className="k">Type</div><div className="v">doc / metric / kg_domain / ...</div>
      </div>
      <div className="kv">
        <div className="k">Security</div><div className="v">internal</div>
      </div>
      <div className="kv">
        <div className="k">Lineage</div><div className="v">(open /assets/{assetId}/lineage)</div>
      </div>

      <div style={{ color: "var(--muted)", fontSize: 12 }}>
        这是详情骨架。你接入真实接口后，把上面的 kv 替换成请求结果即可。
      </div>
    </div>
  );
}
