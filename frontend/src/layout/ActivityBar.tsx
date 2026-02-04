import { useNavigate } from "react-router-dom";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";
import { Activity } from "../types";

type Item = { key: Activity; label: string; icon: string; description: string };

const items: Item[] = [
  { key: "explorer", label: "Explorer", icon: "📁", description: "浏览文件和管理" },
  { key: "search", label: "Search", icon: "🔎", description: "搜索文件和内容" },
  { key: "assets", label: "Assets", icon: "🧩", description: "管理和查看资产" },
  { key: "kg", label: "Graph", icon: "🕸️", description: "知识图谱可视化" },
];

export default function ActivityBar() {
  const activity = useWorkbench(s => s.activity);
  const setActivity = useWorkbench(s => s.setActivity);
  const auth = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    if (confirm("确定要退出登录吗？")) {
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
          <span style={{ fontSize: 20 }}>{it.icon}</span>
          <span className="tooltip">{it.label}</span>
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <div 
        className="activitybtn"
        title="API 文档（需要后端服务）"
        role="button"
        onClick={openApiDocs}
      >
        <span style={{ fontSize: 20 }}>📚</span>
        <span className="tooltip">API 文档</span>
      </div>
      <div 
        className="activitybtn"
        title="退出登录"
        role="button"
        onClick={handleLogout}
      >
        <span style={{ fontSize: 20 }}>🚪</span>
        <span className="tooltip">退出登录</span>
      </div>
    </div>
  );
}