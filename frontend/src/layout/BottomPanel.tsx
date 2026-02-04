import { useState, useEffect } from "react";
import { useWorkbench } from "../store/workbench";

type TabType = "debug" | "audit" | "tool-calls";

interface LogEntry {
  time: string;
  level: "info" | "success" | "warning" | "error";
  message: string;
  raw?: string;
}

function parseLogEntry(raw: string): LogEntry {
  const now = new Date();
  const time = now.toLocaleTimeString("zh-CN", { hour12: false });
  
  if (raw.includes("failed") || raw.includes("error") || raw.includes("Error")) {
    const match = raw.match(/\[(\w+)\]\s*(.+)/);
    return {
      time,
      level: "error",
      message: match ? match[2] : raw,
      raw
    };
  }
  
  if (raw.includes("warning") || raw.includes("Warning")) {
    const match = raw.match(/\[(\w+)\]\s*(.+)/);
    return {
      time,
      level: "warning",
      message: match ? match[2] : raw,
      raw
    };
  }
  
  if (raw.includes("success") || raw.includes("created") || raw.includes("deleted")) {
    const match = raw.match(/\[(\w+)\]\s*(.+)/);
    return {
      time,
      level: "success",
      message: match ? match[2] : raw,
      raw
    };
  }
  
  return { time, level: "info", message: raw, raw };
}

function friendlyError(message: string): { title: string; suggestion: string } | null {
  if (message.includes("get tree failed") || message.includes("404")) {
    return {
      title: "无法获取目录树",
      suggestion: "请检查网络连接或空间权限"
    };
  }
  if (message.includes("network") || message.includes("NetworkError")) {
    return {
      title: "网络连接失败",
      suggestion: "请检查您的网络连接后重试"
    };
  }
  if (message.includes("unauthorized") || message.includes("401")) {
    return {
      title: "认证失败",
      suggestion: "请重新登录后操作"
    };
  }
  return null;
}

export default function BottomPanel() {
  const logs = useWorkbench(s => s.bottomLogs);
  const setBottomHeight = useWorkbench(s => s.setBottomHeight);
  const [activeTab, setActiveTab] = useState<TabType>("debug");
  const [collapsed, setCollapsed] = useState(true);

  const addLog = useWorkbench(s => s.addLog);
  
  useEffect(() => {
    if (logs.length > 0 && collapsed) {
      setCollapsed(false);
    }
  }, [logs.length, collapsed]);

  const getFilteredLogs = () => {
    return logs.map(parseLogEntry);
  };

  const handleMinimize = () => {
    setCollapsed(true);
    setBottomHeight(0);
  };

  if (collapsed) {
    return (
      <div 
        style={{ 
          borderTop: "1px solid var(--border)",
          background: "var(--panel-2)",
          cursor: "pointer"
        }}
        onClick={() => {
          setCollapsed(false);
          setBottomHeight(180);
        }}
      >
        <div style={{ 
          padding: "4px 12px", 
          fontSize: "11px",
          color: "var(--text-muted)",
          display: "flex",
          alignItems: "center",
          gap: "8px"
        }}>
          <span>▼ OUTPUT</span>
          {logs.length > 0 && (
            <span className="badge badge-primary" style={{ fontSize: "10px" }}>
              {logs.length}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="bottompanel" style={{ height: "auto", maxHeight: "350px" }}>
      <div className="bottompanel-header">
        <div className="bottompanel-tabs">
          <span 
            className={`bottompanel-tab ${activeTab === "debug" ? "active" : ""}`}
            onClick={() => setActiveTab("debug")}
          >
            DEBUG
          </span>
          <span 
            className={`bottompanel-tab ${activeTab === "audit" ? "active" : ""}`}
            onClick={() => setActiveTab("audit")}
          >
            AUDIT
          </span>
          <span 
            className={`bottompanel-tab ${activeTab === "tool-calls" ? "active" : ""}`}
            onClick={() => setActiveTab("tool-calls")}
          >
            TOOL-CALLS
          </span>
        </div>
        <div className="bottompanel-actions">
          <span 
            className="bottompanel-btn" 
            onClick={() => {
              addLog(`[Audit] clear output at ${new Date().toLocaleTimeString()}`);
            }}
            title="清空"
          >
            🗑️
          </span>
          <span 
            className="bottompanel-btn" 
            onClick={handleMinimize}
            title="收起"
          >
            △
          </span>
        </div>
      </div>
      <div className="bottompanel-body">
        {getFilteredLogs().map((entry, i) => {
          const friendly = friendlyError(entry.message);
          
          if (friendly) {
            return (
              <div key={i} className={`log-entry-friendly ${entry.level}`}>
                <span className="log-friendly-icon">
                  {entry.level === "error" ? "⚠️" : entry.level === "warning" ? "⚡" : "ℹ️"}
                </span>
                <div className="log-friendly-content">
                  <div className="log-friendly-title">{friendly.title}</div>
                  <div className="log-friendly-message">
                    {entry.message}
                    {friendly.suggestion && (
                      <div className="log-friendly-action">{friendly.suggestion}</div>
                    )}
                  </div>
                </div>
              </div>
            );
          }
          
          return (
            <div key={i} className="log-entry" style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
              <span className="log-time">{entry.time}</span>
              <span className={`log-level log-level-${entry.level}`}>
                {entry.level.toUpperCase()}
              </span>
              <span>{entry.message}</span>
            </div>
          );
        })}
        
        {logs.length === 0 && (
          <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "20px" }}>
            暂无日志输出
          </div>
        )}
      </div>
    </div>
  );
}