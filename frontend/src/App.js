import "./App.css";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";

import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import CodeProjects from "./pages/CodeProjects";
import CodeWorkspace from "./pages/CodeWorkspace";
import WorkspaceLayout from "./pages/WorkspaceLayout";
import Overview from "./pages/sections/Overview";
import Brain from "./pages/sections/Brain";
import Manager from "./pages/sections/Manager";
import Tasks from "./pages/sections/Tasks";
import Blogs from "./pages/sections/Blogs";
import BlogEditor from "./pages/sections/BlogEditor";
import Embed from "./pages/sections/Embed";
import PublicBlog from "./pages/PublicBlog";

function Protected() {
  const { user, ready } = useAuth();
  if (!ready) return <div className="min-h-screen grid place-items-center text-muted-foreground">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function App() {
  return (
    <div className="App">
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/blog/:slug" element={<PublicBlog />} />
              <Route element={<Protected />}>
                <Route path="/app" element={<Dashboard />} />
                <Route path="/app/code" element={<CodeProjects />} />
                <Route path="/app/code/:pid" element={<CodeWorkspace />} />
                <Route path="/app/w/:wsId" element={<WorkspaceLayout />}>
                  <Route index element={<Overview />} />
                  <Route path="brain" element={<Brain />} />
                  <Route path="manager" element={<Manager />} />
                  <Route path="tasks" element={<Tasks />} />
                  <Route path="blogs" element={<Blogs />} />
                  <Route path="blogs/:blogId" element={<BlogEditor />} />
                  <Route path="embed" element={<Embed />} />
                </Route>
              </Route>
            </Routes>
          </BrowserRouter>
          <Toaster position="top-right" richColors />
        </AuthProvider>
      </ThemeProvider>
    </div>
  );
}

export default App;
