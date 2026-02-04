import { useAuth } from "../store/auth";

export default function AssetsView() {
  const space = useAuth(s => s.currentSpace);

  return (
    <div className="col" style={{ gap: "12px" }}>
      <div style={{ 
        display: "flex", 
        alignItems: "center", 
        justifyContent: "space-between",
        padding: "0 4px"
      }}>
        <span style={{ 
          fontSize: "11px", 
          textTransform: "uppercase", 
          color: "var(--text-muted)",
          letterSpacing: "0.5px",
          fontWeight: 600
        }}>
          Assets
        </span>
      </div>

      <div style={{ 
        padding: "40px 20px", 
        textAlign: "center",
        color: "var(--text-muted)"
      }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📦</div>
        <div style={{ fontSize: 15, marginBottom: 8 }}>资源管理</div>
        <div style={{ fontSize: 13 }}>
          {space ? `当前空间: ${space.name}` : "请先选择空间"}
        </div>
        <div style={{ fontSize: 12, marginTop: 16, opacity: 0.7 }}>
          资源管理功能开发中...
        </div>
      </div>
    </div>
  );
}