import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";
import ExplorerView from "../views/ExplorerView";
import SearchView from "../views/SearchView";
import AssetsView from "../views/AssetsView";
import GraphView from "../views/GraphView";
import UserAgentConfigView from "../views/UserAgentConfigView";
import SpaceManager from "../pages/SpaceManager";

function GraphEditorView() {
  return <GraphView mode="editor" showToolbar={false} />;
}

const VIEWS = {
  explorer: { title: "Explorer", component: ExplorerView },
  search: { title: "Search", component: SearchView },
  assets: { title: "Assets", component: AssetsView },
  kg: { title: "Knowledge Graph Editor", component: GraphEditorView },
  agent: { title: "Agent Configuration", component: UserAgentConfigView },
} as const;

type ActivityType = keyof typeof VIEWS;

function maskUserKey(key: string): string {
  if (!key) return "-";
  if (key.length <= 8) return key;
  return `${key.slice(0, 4)}...${key.slice(-4)}`;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "-";
  try {
    return new Date(dateStr).toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return "-";
  }
}

export default function SideBar() {
  const activity = useWorkbench(s => s.activity) as ActivityType;
  const currentSpace = useAuth(s => s.currentSpace);
  const user = useAuth(s => s.user);
  const showSpaceManager = useAuth(s => s.showSpaceManager);
  const setShowSpaceManager = useAuth(s => s.setShowSpaceManager);
  const logout = useAuth(s => s.logout);

  const [showUserPanel, setShowUserPanel] = useState(false);
  const userPanelRef = useRef<HTMLDivElement>(null);

  const avatarInitial = useMemo(() => {
    if (user?.display_name) return user.display_name.charAt(0).toUpperCase();
    if (user?.user_key) return user.user_key.charAt(0).toUpperCase();
    return "?";
  }, [user?.display_name, user?.user_key]);

  const maskedUserKey = useMemo(() => maskUserKey(user?.user_key ?? ""), [user?.user_key]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (userPanelRef.current && !userPanelRef.current.contains(e.target as Node)) {
        setShowUserPanel(false);
      }
    };
    if (showUserPanel) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showUserPanel]);

  const handleLogout = useCallback(() => {
    setShowUserPanel(false);
    logout();
  }, [logout]);

  const handleCopyKey = useCallback(async () => {
    if (user?.user_key) {
      try {
        await navigator.clipboard.writeText(user.user_key);
      } catch {
      }
    }
  }, [user?.user_key]);

  const CurrentView = VIEWS[activity]?.component ?? ExplorerView;

  return (
    <>
      <div className="sidebar-header" style={{ padding: "10px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            className="space-context"
            onClick={() => setShowSpaceManager(true)}
            style={{ padding: "4px 10px" }}
          >
            <span className="space-context-icon">HOME</span>
            <span className="space-context-name">
              {currentSpace?.name ?? "Select space"}
            </span>
            <span className="space-context-badge">v1</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            className="user-avatar"
            onClick={() => setShowUserPanel(!showUserPanel)}
            title="User menu"
          >
            {avatarInitial}
          </div>
        </div>
      </div>

      {showUserPanel && (
        <div className="user-panel-overlay" onClick={() => setShowUserPanel(false)}>
          <div className="user-panel" ref={userPanelRef} onClick={e => e.stopPropagation()}>
            <div className="user-panel-header">
              <div className="user-panel-avatar">{avatarInitial}</div>
              <div className="user-panel-info">
                <div className="user-panel-name">
                  {user?.display_name || user?.user_key || "Unknown user"}
                </div>
                <div className="user-panel-key">ID: {user?.id ?? "-"}</div>
              </div>
            </div>

            <div className="user-panel-section">
              <div className="user-panel-section-title">User info</div>
              <div className="user-panel-item">
                <span className="user-panel-item-key">User Key</span>
                <span
                  className="user-panel-item-value user-key-copyable"
                  onClick={handleCopyKey}
                  title="Copy"
                >
                  {maskedUserKey}
                </span>
              </div>
            </div>

            <div className="user-panel-actions">
              <button className="btn btn-ghost" style={{ flex: 1 }} onClick={handleLogout}>
                Logout
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="sidebar-body" style={{ paddingTop: "8px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "12px",
          }}
        >
          <span
            style={{
              fontSize: "10px",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              letterSpacing: "0.5px",
              fontWeight: 600,
            }}
          >
            {VIEWS[activity]?.title ?? "Explorer"}
          </span>
        </div>

        <div className="view-container">
          <CurrentView />
        </div>
      </div>

      {showSpaceManager && (
        <div className="modal-overlay" onClick={() => setShowSpaceManager(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <SpaceManager onClose={() => setShowSpaceManager(false)} />
          </div>
        </div>
      )}
    </>
  );
}
