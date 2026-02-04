import { useState } from "react";
import { useNavigate } from "react-router-dom";

export default function SwaggerPage() {
  const [apiUrl, setApiUrl] = useState("http://localhost:8000/docs");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleLoad = () => {
    setLoading(true);
  };

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      background: "var(--bg)"
    }}>
      <div style={{
        padding: "16px 20px",
        borderBottom: "1px solid var(--border)",
        background: "var(--panel-2)",
        display: "flex",
        alignItems: "center",
        gap: "16px"
      }}>
        <button
          className="btn btn-ghost"
          onClick={() => navigate("/")}
          style={{ fontSize: "12px" }}
        >
          ← 返回
        </button>
        <h2 style={{ 
          margin: 0, 
          fontSize: "16px", 
          fontWeight: 600,
          color: "var(--text)"
        }}>
          API 文档
        </h2>
        <div style={{ flex: 1 }} />
        <input
          type="text"
          className="input"
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          placeholder="输入 Swagger URL"
          style={{ width: "300px" }}
        />
        <a
          href={apiUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-primary"
          style={{ fontSize: "12px" }}
        >
          新窗口打开
        </a>
      </div>

      <div style={{
        flex: 1,
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        padding: "20px",
        overflow: "auto"
      }}>
        <div style={{
          width: "100%",
          height: "100%",
          maxWidth: "1400px",
          background: "var(--panel)",
          borderRadius: "var(--radius-lg)",
          border: "1px solid var(--border)",
          overflow: "hidden"
        }}>
          <iframe
            src={apiUrl}
            style={{
              width: "100%",
              height: "100%",
              border: "none",
              minHeight: "600px"
            }}
            onLoad={handleLoad}
            title="Swagger API Docs"
          />
        </div>
      </div>

      {loading && (
        <div style={{
          position: "fixed",
          bottom: "20px",
          right: "20px",
          padding: "10px 16px",
          background: "var(--panel-3)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
          fontSize: "12px",
          color: "var(--text-muted)"
        }}>
          正在加载 API 文档...
        </div>
      )}
    </div>
  );
}