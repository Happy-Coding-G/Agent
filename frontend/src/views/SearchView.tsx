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
    <div className="col">
      <div className="row">
        <input 
          className="input" 
          placeholder="搜索文件..." 
          value={q} 
          onChange={(e) => setQ(e.target.value)} 
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <button className="btn btn-primary" onClick={run} disabled={loading}>
          {loading ? "搜索中…" : "搜索"}
        </button>
      </div>

      {items.length > 0 && (
        <table className="table" aria-label="search result">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>大小</th>
            </tr>
          </thead>
          <tbody>
            {items.map(it => (
              <tr key={it.public_id} style={{ cursor: "pointer" }} onClick={() => {
                openTab({ id: `tab-file-${it.public_id}`, kind: "filePreview", title: it.name, payload: { file: it } });
              }}>
                <td>{it.name}</td>
                <td style={{ color: "var(--text-muted)" }}>{it.mime ?? "-"}</td>
                <td style={{ color: "var(--text-muted)" }}>{formatSize(it.size_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {items.length === 0 && !loading && q && (
        <div style={{ color: "var(--text-muted)", padding: "20px", textAlign: "center" }}>
          未找到匹配的文件
        </div>
      )}

      {items.length === 0 && !q && (
        <div style={{ color: "var(--text-muted)", padding: "20px", textAlign: "center" }}>
          输入关键词搜索文件
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