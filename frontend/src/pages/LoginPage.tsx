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
  const [isFocused, setIsFocused] = useState<"identifier" | "credential" | null>(null);

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
        identity_type: "password",
      });

      const user: User = {
        id: 0,
        user_key: identifier,
        display_name: identifier,
      };

      auth.setToken(response.access_token);
      auth.setUser(user);

      const spaces = await getSpaces();
      const defaultSpace = spaces.find((s) => s.name === "Default Space") ?? spaces[0] ?? null;

      if (defaultSpace && spaces.length > 0) {
        auth.setSpaces(spaces);
        auth.setCurrentSpace(defaultSpace);
        toast.success("Login success", `Current space: ${defaultSpace.name}`);
        navigate("/");
      } else {
        setError("No space available. Contact administrator.");
      }
    } catch (err: any) {
      const errorMsg = err?.message ?? "Login failed. Check account and password.";
      setError(errorMsg);
      toast.error("Login failed", errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-bg-shapes">
        <div className="auth-shape auth-shape-1"></div>
        <div className="auth-shape auth-shape-2"></div>
        <div className="auth-shape auth-shape-3"></div>
      </div>
      <div className="auth-container">
        <div className="auth-card">
          <div className="auth-logo">
            <div className="auth-logo-icon">P</div>
          </div>
          <h1 className="auth-title">PTDS Login</h1>
          <p className="auth-subtitle">Welcome back! Please sign in to continue.</p>

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="input-group">
              <label className="input-label">Account</label>
              <div className={`input-wrapper ${isFocused === "identifier" ? "focused" : ""}`}>
                <span className="input-icon">👤</span>
                <input
                  type="text"
                  className="input auth-input"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  onFocus={() => setIsFocused("identifier")}
                  onBlur={() => setIsFocused(null)}
                  placeholder="Enter your account"
                  required
                  disabled={loading}
                />
              </div>
            </div>

            <div className="input-group">
              <label className="input-label">Password</label>
              <div className={`input-wrapper ${isFocused === "credential" ? "focused" : ""}`}>
                <span className="input-icon">🔒</span>
                <input
                  type="password"
                  className="input auth-input"
                  value={credential}
                  onChange={(e) => setCredential(e.target.value)}
                  onFocus={() => setIsFocused("credential")}
                  onBlur={() => setIsFocused(null)}
                  placeholder="Enter your password"
                  required
                  disabled={loading}
                />
              </div>
            </div>

            {error && (
              <div className="auth-error">
                <span className="auth-error-icon">⚠</span>
                {error}
              </div>
            )}

            <button
              type="submit"
              className="btn btn-primary auth-btn"
              disabled={loading}
            >
              {loading ? (
                <span className="spinner" style={{ width: 18, height: 18 }} />
              ) : (
                <>
                  <span>Sign In</span>
                  <span className="auth-btn-arrow">→</span>
                </>
              )}
            </button>

            <div className="auth-footer">
              <span className="auth-footer-text">Don't have an account?</span>
              <button type="button" className="auth-link" onClick={() => navigate("/register")}>
                Create one
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
