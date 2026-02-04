import { useState } from "react";
import { Tab } from "../types";

export default function GraphTab({ tab }: { tab: Tab }) {
  const [loading, setLoading] = useState(false);

  return (
    <div className="col" style={{ gap: "12px", padding: "16px" }}>
      <div style={{ fontSize: 15, fontWeight: 600 }}>知识图谱</div>
      
      <div style={{ 
        flex: 1, 
        background: "var(--panel-2)", 
        borderRadius: "var(--radius)",
        display: "flex", 
        alignItems: "center", 
        justifyContent: "center",
        minHeight: 300,
        color: "var(--text-muted)"
      }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🕸️</div>
          <div>知识图谱功能开发中</div>
          <div style={{ fontSize: 12, marginTop: 8, opacity: 0.7 }}>
            空间 ID: {String(tab.payload?.spaceId ?? "未指定")}
          </div>
        </div>
      </div>
    </div>
  );
}