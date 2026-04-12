import { useNavigate } from "react-router-dom";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";
import { Activity } from "../types";

type Item = { key: Activity; label: string; icon: string; description: string };

const items: Item[] = [
  { key: "explorer", label: "Explorer", icon: "EX", description: "Browse files and folders" },
  { key: "search", label: "Search", icon: "SR", description: "Search files and content" },
  { key: "assets", label: "Assets", icon: "AS", description: "Manage generated assets" },
  { key: "kg", label: "Graph", icon: "KG", description: "Knowledge graph" },
  { key: "agent", label: "Agent", icon: "AG", description: "Configure your AI agent" },
  { key: "usage", label: "Usage", icon: "TK", description: "Token usage statistics" },
];

export default function ActivityBar() {
  const activity = useWorkbench((s) => s.activity);
  const setActivity = useWorkbench((s) => s.setActivity);
  const auth = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    if (confirm("Confirm logout?")) {
      auth.logout();
      navigate("/login", { replace: true });
    }
  };

  const openApiDocs = () => {
    window.open("http://localhost:8000/docs", "_blank");
  };

  return (
    <div className="activitybar" aria-label="Activity Bar">
      {items.map((it) => (
        <div
          key={it.key}
          className={`activitybtn ${activity === it.key ? "active" : ""}`}
          title={it.description}
          onClick={() => setActivity(it.key)}
          role="button"
          aria-label={it.label}
        >
          <span style={{ fontSize: 12, fontWeight: 600 }}>{it.icon}</span>
          <span className="tooltip">{it.label}</span>
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <div className="activitybtn" title="Open API docs" role="button" onClick={openApiDocs}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>API</span>
        <span className="tooltip">API Docs</span>
      </div>
      <div className="activitybtn" title="Logout" role="button" onClick={handleLogout}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>OUT</span>
        <span className="tooltip">Logout</span>
      </div>
    </div>
  );
}
