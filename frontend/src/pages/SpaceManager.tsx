import { useState, useEffect } from "react";
import { createSpace, deleteSpace, getSpaces } from "../api/auth";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { Space } from "../types";

interface SpaceManagerProps {
  onClose?: () => void;
}

export default function SpaceManager({ onClose }: SpaceManagerProps) {
  const auth = useAuth();
  const incrementRefreshKey = useWorkbench(s => s.incrementSpaceRefreshKey);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newSpaceName, setNewSpaceName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSpaces = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSpaces();
      setSpaces(data);
      auth.setSpaces(data);
    } catch (err: any) {
      setError(err?.message ?? "加载空间失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSpaces();
  }, []);

  const handleCreateSpace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSpaceName.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const newSpace = await createSpace(newSpaceName);
      auth.addSpace(newSpace);
      setSpaces([...spaces, newSpace]);
      setNewSpaceName("");
      setShowCreateModal(false);
    } catch (err: any) {
      setError(err?.message ?? "创建空间失败");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteSpace = async (spaceId: string) => {
    if (!confirm("确定要删除这个空间吗？此操作不可恢复。")) return;

    setLoading(true);
    setError(null);
    try {
      await deleteSpace(spaceId);
      auth.removeSpace(spaceId);
      setSpaces(spaces.filter(s => s.public_id !== spaceId));
    } catch (err: any) {
      setError(err?.message ?? "删除空间失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSwitchSpace = (space: Space) => {
    auth.setCurrentSpace(space);
    incrementRefreshKey();
    onClose?.();
  };

  const currentSpaceId = auth.currentSpace?.public_id;

  return (
    <div className="col" style={{ padding: "12px", gap: "12px" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <span className="badge">空间管理</span>
        <button
          className="btn btn-primary"
          onClick={() => setShowCreateModal(true)}
          disabled={loading}
          style={{ fontSize: "12px", padding: "6px 12px" }}
        >
          + 新建空间
        </button>
      </div>

      {error && (
        <div style={{
          color: "var(--danger)",
          fontSize: "12px",
          padding: "8px",
          background: "var(--danger-light)",
          borderRadius: "6px",
          border: "1px solid var(--danger)"
        }}>
          {error}
        </div>
      )}

      {loading && spaces.length === 0 && (
        <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>加载中...</div>
      )}

      {!loading && spaces.length === 0 && (
        <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>
          暂无空间，点击上方按钮创建
        </div>
      )}

      <div className="col" style={{ gap: "8px" }}>
        {spaces.map(space => (
          <div
              key={space.public_id}
              style={{
                padding: "10px 12px",
                background: currentSpaceId === space.public_id 
                  ? "var(--accent-light)" 
                  : "var(--panel-2)",
                border: currentSpaceId === space.public_id 
                  ? "1px solid var(--accent)" 
                  : "1px solid var(--border)",
                borderRadius: "8px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center"
              }}
            >
              <div className="col" style={{ gap: "4px", flex: 1 }}>
                <div style={{ 
                  fontSize: "13px", 
                  color: "var(--text)",
                  fontWeight: currentSpaceId === space.public_id ? 600 : 400
                }}>
                  {space.name}
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                  ID: {space.public_id}
                </div>
              </div>

              <div className="row" style={{ gap: "6px" }}>
                {currentSpaceId !== space.public_id && (
                  <button
                    className="btn"
                    onClick={() => handleSwitchSpace(space)}
                    disabled={loading}
                    style={{ 
                      fontSize: "11px", 
                      padding: "4px 8px",
                      background: "var(--accent)",
                      borderColor: "var(--accent)",
                      color: "white"
                    }}
                  >
                    切换
                  </button>
                )}
              <button
                className="btn"
                onClick={() => handleDeleteSpace(space.public_id)}
                disabled={loading}
                style={{ 
                  fontSize: "11px", 
                  padding: "4px 8px",
                  color: "var(--danger)",
                  borderColor: "var(--danger)"
                }}
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>

      {showCreateModal && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0, 0, 0, 0.5)",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          zIndex: 1000
        }}>
          <div style={{
            background: "var(--panel)",
            padding: "24px",
            borderRadius: "12px",
            width: "100%",
            maxWidth: "320px",
            border: "1px solid var(--border)"
          }}>
            <h3 style={{ 
              margin: "0 0 16px 0", 
              fontSize: "16px", 
              color: "var(--text)" 
            }}>
              创建新空间
            </h3>
            <form onSubmit={handleCreateSpace} className="col" style={{ gap: "12px" }}>
              <input
                type="text"
                className="input"
                value={newSpaceName}
                onChange={(e) => setNewSpaceName(e.target.value)}
                placeholder="请输入空间名称"
                autoFocus
                disabled={loading}
              />
              <div className="row" style={{ gap: "8px", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setShowCreateModal(false);
                    setNewSpaceName("");
                    setError(null);
                  }}
                  disabled={loading}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={loading || !newSpaceName.trim()}
                >
                  {loading ? "创建中..." : "创建"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}