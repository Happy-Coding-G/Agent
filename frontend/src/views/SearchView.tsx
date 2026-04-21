import { useState } from "react";
import { searchFiles } from "../api/ptds";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";

export default function SearchView() {
  const space = useAuth(s => s.currentSpace);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const openTab = useWorkbench(s => s.openTab);
  const log = useWorkbench(s => s.log);

  const run = async () => {
    if (!space?.public_id) return;
    setLoading(true);
    try {
      const r = await searchFiles({ spaceId: space.public_id, q });
      setItems(r.items ?? []);
      log(`[Search] found ${r.total ?? 0} items for q="${q}"`);
    } catch (e: any) {
      log(`[Search] error: ${e?.message ?? String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="col" style={{ padding: "16px", gap: 16 }}>
      <div style={{ paddingBottom: "12px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: "16px" }}>🔍</span> 全局搜索
        </h3>
      </div>
      
      <div style={{ display: "flex", gap: 8 }}>
        <input 
          style={{ flex: 1, padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none" }}
          placeholder="搜索文件..." 
          value={q} 
          onChange={(e) => setQ(e.target.value)} 
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <button 
          style={{ padding: "8px 16px", fontSize: 13, background: "#3B82F6", color: "white", border: "none", borderRadius: 6, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1, fontWeight: 500 }} 
          onClick={run} 
          disabled={loading}
        >
          {loading ? "搜索中..." : "搜索"}
        </button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        {items.length > 0 && items.map(it => (
          <div 
            key={it.public_id} 
            onClick={() => {
              openTab({ id: `tab-file-${it.public_id}`, kind: "filePreview", title: it.name, payload: { file: it } });
            }}
            style={{ padding: "12px", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, cursor: "pointer", display: "flex", flexDirection: "column", gap: 6, transition: "background 0.2s" }}
            onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(255,255,255,0.05)" })}
            onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "rgba(255,255,255,0.02)" })}
          >
            <div style={{ color: "#E2E8F0", fontSize: 13, fontWeight: 500, display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: "16px" }}>📄</span> {it.name}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", color: "#94A3B8", fontSize: "12px" }}>
              <span>{it.mime ?? "未知类型"}</span>
              <span>{formatSize(it.size_bytes)}</span>
            </div>
          </div>
        ))}
      </div>

      {items.length === 0 && !loading && q && (
        <div style={{ padding: "40px 20px", textAlign: "center", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px dashed rgba(255,255,255,0.05)" }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.5 }}>🤷‍♂️</div>
          <div style={{ color: "#94A3B8", fontSize: 13 }}>未找到匹配的文件</div>
        </div>
      )}

      {items.length === 0 && !q && (
        <div style={{ padding: "60px 20px", textAlign: "center", background: "rgba(255,255,255,0.01)", borderRadius: 12, border: "1px dashed rgba(255,255,255,0.05)" }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.3 }}>⌨️</div>
          <div style={{ color: "#64748B", fontSize: 13 }}>输入关键词搜索文件</div>
        </div>
      )}
    </div>
  );
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "-";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}