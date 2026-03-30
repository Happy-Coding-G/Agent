import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect } from "react";
import Workbench from "./layout/Workbench";
import ToastContainer from "./components/Toast";
import { useAuth } from "./store/auth";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";

function isTokenExpired(token: string): boolean {
  try {
    const payload = token.split(".")[1];
    if (!payload) return true;
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    const exp = typeof decoded?.exp === "number" ? decoded.exp : null;
    if (!exp) return false;
    return Date.now() >= exp * 1000;
  } catch {
    return true;
  }
}

function hasValidAuth(isAuthenticated: boolean, token: string | null): boolean {
  if (!isAuthenticated || !token) return false;
  return !isTokenExpired(token);
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuth((s) => s.isAuthenticated);
  const token = useAuth((s) => s.token);
  if (!hasValidAuth(isAuthenticated, token)) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuth((s) => s.isAuthenticated);
  const token = useAuth((s) => s.token);
  if (hasValidAuth(isAuthenticated, token)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const isAuthenticated = useAuth((s) => s.isAuthenticated);
  const token = useAuth((s) => s.token);
  const logout = useAuth((s) => s.logout);

  useEffect(() => {
    if (isAuthenticated && (!token || isTokenExpired(token))) {
      logout();
    }
  }, [isAuthenticated, token, logout]);

  return (
    <BrowserRouter>
      <ToastContainer />
      <Routes>
        <Route
          path="/login"
          element={
            <PublicRoute>
              <LoginPage />
            </PublicRoute>
          }
        />
        <Route
          path="/register"
          element={
            <PublicRoute>
              <RegisterPage />
            </PublicRoute>
          }
        />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Workbench />
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
