import "./App.css";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";

const Landing = lazy(() => import("./pages/Landing"));
const CheckDemo = lazy(() => import("./pages/CheckDemo"));
const Login = lazy(() => import("./pages/Login"));
const JoinWorkspace = lazy(() => import("./pages/JoinWorkspace"));
const Register = lazy(() => import("./pages/Register"));
const ForgotPassword = lazy(() => import("./pages/ForgotPassword"));
const ResetPassword = lazy(() => import("./pages/ResetPassword"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Onboarding = lazy(() => import("./pages/Onboarding"));
const CodeProjects = lazy(() => import("./pages/CodeProjects"));
const CodeWorkspace = lazy(() => import("./pages/CodeWorkspace"));
const WorkspaceLayout = lazy(() => import("./pages/WorkspaceLayout"));
const Overview = lazy(() => import("./pages/sections/Overview"));
const Brain = lazy(() => import("./pages/sections/Brain"));
const Manager = lazy(() => import("./pages/sections/Manager"));
const Agents = lazy(() => import("./pages/sections/Agents"));
const Qualification = lazy(() => import("./pages/sections/Qualification"));
const Tasks = lazy(() => import("./pages/sections/Tasks"));
const Blogs = lazy(() => import("./pages/sections/Blogs"));
const BlogEditor = lazy(() => import("./pages/sections/BlogEditor"));
const Embed = lazy(() => import("./pages/sections/Embed"));
const PublicBlog = lazy(() => import("./pages/PublicBlog"));
const Workflows = lazy(() => import("./pages/sections/Workflows"));
const AdsToCrmWorkflow = lazy(() => import("./pages/sections/AdsToCrmWorkflow"));
const CrmInbox = lazy(() => import("./pages/sections/CrmInbox"));
const Projects = lazy(() => import("./pages/sections/Projects"));
const Properties = lazy(() => import("./pages/sections/Properties"));
const ProductsServices = lazy(() => import("./pages/sections/ProductsServices"));
const Settings = lazy(() => import("./pages/sections/Settings"));

function Protected() {
  const location = useLocation();
  const { user, ready, connectionError, retryAuth } = useAuth();
  if (!ready) return <div className="min-h-screen grid place-items-center text-muted-foreground">Loading…</div>;
  if (connectionError) return <div className="min-h-screen grid place-items-center p-6"><div role="alert" className="max-w-sm rounded-xl border bg-card p-6 text-center space-y-3"><h1 className="text-lg font-semibold">Cannot reach the server</h1><p className="text-sm text-muted-foreground">Your session is saved. Check the local backend, then try again.</p><button type="button" onClick={retryAuth} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">Try again</button></div></div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  return <Outlet />;
}

function App() {
  return (
    <div className="App">
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Suspense fallback={<div className="min-h-screen grid place-items-center text-muted-foreground">Loading…</div>}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/check-demo" element={<CheckDemo />} />
              <Route path="/login" element={<Login />} />
              <Route path="/join/:token" element={<JoinWorkspace />} />
              <Route path="/register" element={<Register />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/blog/:slug" element={<PublicBlog />} />
              <Route element={<Protected />}>
                <Route path="/welcome" element={<Onboarding />} />
                <Route path="/app" element={<Dashboard />} />
                <Route path="/app/code" element={<CodeProjects />} />
                <Route path="/app/code/:pid" element={<CodeWorkspace />} />
                <Route path="/app/w/:wsId" element={<WorkspaceLayout />}>
                  <Route index element={<Overview />} />
                  <Route path="projects" element={<Projects />} />
                  <Route path="properties" element={<Properties />} />
                  <Route path="products-services" element={<ProductsServices />} />
                  <Route path="settings" element={<Settings />} />
                  <Route path="brain" element={<Brain />} />
                  <Route path="manager" element={<Manager />} />
                  <Route path="agents" element={<Agents />} />
                  <Route path="qualification" element={<Qualification />} />
                  <Route path="tasks" element={<Tasks />} />
                  <Route path="blogs" element={<Blogs />} />
                  <Route path="blogs/:blogId" element={<BlogEditor />} />
                  <Route path="embed" element={<Embed />} />
                  <Route path="workflows" element={<Workflows />} />
                  <Route path="workflows/ads-to-crm" element={<AdsToCrmWorkflow />} />
                  <Route path="crm" element={<CrmInbox />} />
                </Route>
              </Route>
            </Routes>
            </Suspense>
          </BrowserRouter>
          <Toaster position="top-right" richColors />
        </AuthProvider>
      </ThemeProvider>
    </div>
  );
}

export default App;
