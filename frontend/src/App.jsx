// @ts-nocheck
import { Toaster } from "@/components/ui/toaster"
import { Toaster as SonnerToaster } from "@/components/ui/sonner"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import { ThemeProvider } from '@/lib/ThemeContext';

// Layout
import AppLayout from '@/components/layout/AppLayout';
import WorkflowLayout from '@/components/layout/WorkflowLayout';

// Pages
import Login from '@/pages/Login';
import Dashboard from '@/pages/Dashboard';
import GeneraReport from '@/pages/GeneraReport';
import ProduciChecklist from '@/pages/ProduciChecklist';
import CompilaChecklist from '@/pages/CompilaChecklist';
import StoricoPratiche from '@/pages/StoricoPratiche';
import AdminPanel from '@/pages/AdminPanel';
import AdminErrorLog from '@/pages/AdminErrorLog';
import Supporto from '@/pages/Supporto';

const AppRoutes = () => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-lg brand-gradient flex items-center justify-center">
            <span className="text-white font-bold text-lg">A</span>
          </div>
          <div className="w-8 h-8 border-2 border-muted border-t-primary rounded-full animate-spin"></div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />

        <Route path="workflow" element={<WorkflowLayout />}>
          <Route index element={<Navigate to="/workflow/report" replace />} />
          <Route path="report"   element={<GeneraReport />} />
          <Route path="produce"  element={<ProduciChecklist />} />
          <Route path="compile"  element={<CompilaChecklist />} />
        </Route>

        <Route path="pratiche" element={<StoricoPratiche />} />
        <Route path="admin" element={<AdminPanel />} />
        <Route path="admin/errori" element={<AdminErrorLog />} />
        <Route path="supporto" element={<Supporto />} />
        <Route path="*" element={<PageNotFound />} />
      </Route>
    </Routes>
  );
};

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <QueryClientProvider client={queryClientInstance}>
          <Router>
            <AppRoutes />
          </Router>
          <Toaster />
          <SonnerToaster />
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
