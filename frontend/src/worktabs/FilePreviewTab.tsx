import { useEffect, useMemo, useState } from "react";
import { Tab } from "../types";
import { searchFiles } from "../api/ptds";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";

export default function FilePreviewTab({ tab }: { tab: Tab }) {
  const space = useAuth(s => s.currentSpace);
  const log = useWorkbench(s => s.log);
  const openTab = useWorkbench(s => s.openTab);

  const folderId = useMemo(() => String(tab.payload?.folderId ?? ""), [tab.payload]);
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!space?.public_id) return;
    setLoading(true);
    try {
      const r = await searchFiles({ spaceId: space.public_id, folderId });
      setItems(r.items ?? []);
      log(`[Files] folder=${folderId} total=${r.total ?? 0}`);
    } catch (e: any) {
      log(`[Files] error: ${e?.message ?? String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [folderId, space?.public_id]);

  return (
    <div className="col" style={{ minHeight: 0 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="badge">文件列表</span>
        <div className="row" style={{ gap: "8px", alignItems: "center" }}>
          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>文件夹: {folderId || "-"}</span>
          <button className="btn btn-ghost" onClick={() => void load()} style={{ padding: "4px 8px", fontSize: 12 }}>
            {loading ? "加载中…" : "刷新"}
          </button>
        </div>
      </div>

      {items.length === 0 && !loading && (
        <div style={{ color: "var(--text-muted)", padding: "20px", textAlign: "center" }}>
          该文件夹暂无文件
        </div>
      )}

      {items.length > 0 && (
        <table className="table" aria-label="files">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>大小</th>
            </tr>
          </thead>
          <tbody>
            {items.map(f => (
              <tr key={f.public_id} style={{ cursor: "pointer" }} onClick={() => {
                openTab({ id: `tab-file-${f.public_id}`, kind: "filePreview", title: f.name, payload: { file: f } });
              }}>
                <td>{f.name}</td>
                <td style={{ color: "var(--text-muted)" }}>{f.mime ?? "-"}</td>
                <td style={{ color: "var(--text-muted)" }}>{formatSize(f.size_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
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