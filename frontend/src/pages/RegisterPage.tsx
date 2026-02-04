import { useState } from "react";
import { register } from "../api/auth";
import { useNavigate } from "react-router-dom";
import useToast from "../store/toast";

export default function RegisterPage() {
  const [identifier, setIdentifier] = useState("");
  const [credential, setCredential] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  
  const toast = useToast();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (credential !== confirmPassword) {
      setError("两次输入的密码不一致");
      toast.error("注册失败", "两次输入的密码不一致");
      return;
    }

    if (credential.length < 6) {
      setError("密码长度至少为6位");
      toast.error("注册失败", "密码长度至少为6位");
      return;
    }

    setLoading(true);

    try {
      const response = await register({ 
        identifier, 
        credential,
        identity_type: "password",
        display_name: displayName || undefined
      });
      
      toast.success("注册成功", response.message || "请使用注册的账号登录");
      navigate("/login");
    } catch (err: any) {
      const errorMsg = err?.message ?? "注册失败，请稍后重试";
      setError(errorMsg);
      toast.error("注册失败", errorMsg);
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
          PTDS 注册
        </h1>

        <form onSubmit={handleSubmit} className="col" style={{ gap: "16px" }}>
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
            <label className="input-label">显示名称（可选）</label>
            <input
              type="text"
              className="input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="请输入显示名称"
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
              placeholder="请输入密码（至少6位）"
              required
              disabled={loading}
            />
          </div>

          <div className="input-group">
            <label className="input-label">确认密码</label>
            <input
              type="password"
              className="input"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="请再次输入密码"
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
              "注册"
            )}
          </button>

          <div style={{ textAlign: "center", fontSize: "13px" }}>
            <span style={{ color: "var(--text-muted)" }}>已有账号？</span>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => navigate("/login")}
            >
              立即登录
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}