import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { useState, useEffect } from "react";

export default function StatusBar() {
  const auth = useAuth();
  const user = auth.user;
  const activity = useWorkbench(s => s.activity);
  const [apiLatency, setApiLatency] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const ping = async () => {
      const start = performance.now();
      try {
        await fetch("/api/v1/healthz", { method: "GET" });
        setApiLatency(Math.round(performance.now() - start));
      } catch {
        setApiLatency(null);
      }
    };
    ping();
    const interval = setInterval(ping, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="statusbar">
      <div className="statusbar-left">
        <div className="statusbar-item" title="PTDS Workbench">
          <span>📦</span>
        </div>
        <div className="statusbar-item" title={`当前视图: ${activity}`}>
          <span style={{ textTransform: "capitalize" }}>{activity}</span>
        </div>
        <div className="statusbar-item" title="快捷键">
          <span>⌨️</span>
          <span>?</span>
        </div>
      </div>
      <div className="statusbar-right">
        {apiLatency !== null && (
          <div className="statusbar-item" title="API 延迟">
            <span>⚡</span>
            <span>{apiLatency}ms</span>
          </div>
        )}
        <div className="statusbar-item" title="当前时间">
          <span>🕐</span>
          <span>{currentTime.toLocaleTimeString()}</span>
        </div>
      </div>
    </div>
  );
}