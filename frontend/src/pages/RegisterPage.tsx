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
  const [isFocused, setIsFocused] = useState<string | null>(null);

  const toast = useToast();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (credential !== confirmPassword) {
      setError("Passwords do not match");
      toast.error("Registration failed", "Passwords do not match");
      return;
    }

    if (credential.length < 6) {
      setError("Password must be at least 6 characters");
      toast.error("Registration failed", "Password must be at least 6 characters");
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

      toast.success("Registration successful", "Please log in with your new account");
      navigate("/login");
    } catch (err: any) {
      const errorMsg = err?.message ?? "Registration failed. Please try again.";
      setError(errorMsg);
      toast.error("Registration failed", errorMsg);
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
          <h1 className="auth-title">Create Account</h1>
          <p className="auth-subtitle">Join us! Fill in your details to get started.</p>

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
                  placeholder="Choose an account"
                  required
                  disabled={loading}
                />
              </div>
            </div>

            <div className="input-group">
              <label className="input-label">Display Name (Optional)</label>
              <div className={`input-wrapper ${isFocused === "displayName" ? "focused" : ""}`}>
                <span className="input-icon">📛</span>
                <input
                  type="text"
                  className="input auth-input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  onFocus={() => setIsFocused("displayName")}
                  onBlur={() => setIsFocused(null)}
                  placeholder="Your display name"
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
                  placeholder="At least 6 characters"
                  required
                  disabled={loading}
                />
              </div>
            </div>

            <div className="input-group">
              <label className="input-label">Confirm Password</label>
              <div className={`input-wrapper ${isFocused === "confirmPassword" ? "focused" : ""}`}>
                <span className="input-icon">🔐</span>
                <input
                  type="password"
                  className="input auth-input"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onFocus={() => setIsFocused("confirmPassword")}
                  onBlur={() => setIsFocused(null)}
                  placeholder="Re-enter your password"
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
                  <span>Create Account</span>
                  <span className="auth-btn-arrow">→</span>
                </>
              )}
            </button>

            <div className="auth-footer">
              <span className="auth-footer-text">Already have an account?</span>
              <button
                type="button"
                className="auth-link"
                onClick={() => navigate("/login")}
              >
                Sign in
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}