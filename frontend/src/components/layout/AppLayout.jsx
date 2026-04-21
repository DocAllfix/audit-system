import React, { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Outlet } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/lib/AuthContext';
import { api } from '@/api/apiClient';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import WelcomeOverlay from '@/components/shared/WelcomeOverlay';

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const { user, logout } = useAuth();

  const { data: unresolvedErrors = [] } = useQuery({
    queryKey: ['unresolved-errors-count'],
    queryFn: () => api.errors.listUnresolved(),
    initialData: [],
    refetchInterval: 30000,
    enabled: user?.role === 'admin',
  });

  return (
    <div className="h-screen flex overflow-hidden">
      <div className="relative flex-shrink-0">
        <Sidebar
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          userRole={user?.role}
          errorCount={unresolvedErrors.length}
        />
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="absolute -right-4 top-1/2 -translate-y-1/2 z-50 w-8 h-8 rounded-full
            bg-primary text-primary-foreground
            border-2 border-background
            shadow-lg flex items-center justify-center
            hover:bg-primary/80 transition-all duration-150"
        >
          {collapsed
            ? <ChevronRight className="w-4 h-4" />
            : <ChevronLeft className="w-4 h-4" />
          }
        </button>
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar
          user={user}
          onLogout={logout}
          errorCount={unresolvedErrors.length}
        />
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[1440px] mx-auto p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
        <WelcomeOverlay user={user} />
      </div>
    </div>
  );
}
