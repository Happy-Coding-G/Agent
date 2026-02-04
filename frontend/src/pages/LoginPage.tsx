import { useState } from "react";
import { login, getSpaces } from "../api/auth";
import { useAuth } from "../store/auth";
import { useNavigate } from "react-router-dom";
import useToast from "../store/toast";
import { User } from "../types";

export default function LoginPage() {
  const [identifier, setIdentifier] = useState("");
  const [credential, setCredential] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  
  const auth = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const response = await login({ 
        identifier, 
        credential,
        identity_type: "password"
      });
      
      console.log("[Login] 登录响应:", response);
      
      const user: User = {
        id: 0,
        user_key: identifier,
        display_name: identifier,
      };
      
      console.log("[Login] 设置 token 到 auth store...");
      auth.setToken(response.access_token);
      auth.setUser(user);
      
      console.log("[Login] 获取空间列表...");
      const spaces = await getSpaces();
      console.log("[Login] 获取到空间:", spaces.length);
      
      let defaultSpace = spaces.find(s => s.name === "Default Space") ?? spaces[0] ?? null;
      
      if (defaultSpace && spaces.length > 0) {
        auth.setSpaces(spaces);
        auth.setCurrentSpace(defaultSpace);
        toast.success("登录成功", `欢迎回来，当前空间: ${defaultSpace.name}`);
        navigate("/");
      } else {
        setError("暂无空间，请联系管理员");
      }
    } catch (err: any) {
      const errorMsg = err?.message ?? "登录失败，请检查账号和密码";
      setError(errorMsg);
      toast.error("登录失败", errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      minHeight: "100vh",
      background: "var(--bg)"
    }}>
      <div style={{
        background: "var(--panel)",
        padding: "40px",
        borderRadius: "var(--radius-lg)",
        width: "100%",
        maxWidth: "400px",
        border: "1px solid var(--border)",
        boxShadow: "0 8px 32px var(--shadow-lg)"
      }}>
        <h1 style={{ 
          textAlign: "center", 
          marginBottom: "30px", 
          color: "var(--text)",
          fontSize: "24px",
          fontWeight: 600
        }}>
          PTDS 登录
        </h1>

        <form onSubmit={handleSubmit} className="col" style={{ gap: "20px" }}>
          <div className="input-group">
            <label className="input-label">账号</label>
            <input
              type="text"
              className="input"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder="请输入账号"
              required
              disabled={loading}
            />
          </div>

          <div className="input-group">
            <label className="input-label">密码</label>
            <input
              type="password"
              className="input"
              value={credential}
              onChange={(e) => setCredential(e.target.value)}
              placeholder="请输入密码"
              required
              disabled={loading}
            />
          </div>

          {error && (
            <div className="badge badge-danger" style={{ padding: "10px", justifyContent: "center" }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading}
            style={{ marginTop: "10px", height: "44px" }}
          >
            {loading ? (
              <span className="spinner" style={{ width: 18, height: 18 }} />
            ) : (
              "登录"
            )}
          </button>

          <div style={{ textAlign: "center", fontSize: "13px" }}>
            <span style={{ color: "var(--text-muted)" }}>还没有账号？</span>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => navigate("/register")}
            >
              立即注册
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}