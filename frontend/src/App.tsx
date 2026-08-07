import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./auth";
import { tokenStore } from "./api/client";
import Shell from "./components/Shell";
import Login from "./pages/Login";
import Library from "./pages/Library";
import AdDetailPage from "./pages/AdDetailPage";
import Users from "./pages/Users";
import { Forbidden, NotFound } from "./pages/Misc";

function RequireAuth({ children }: { children: ReactNode }) {
  if (!tokenStore.isAuthed()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return null;
  if (user && user.role !== "admin") return <Navigate to="/403" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Library />} />
        <Route path="/ads/:id" element={<AdDetailPage />} />
        <Route path="/users" element={<RequireAdmin><Users /></RequireAdmin>} />
        <Route path="/403" element={<Forbidden />} />
        <Route path="/404" element={<NotFound />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
