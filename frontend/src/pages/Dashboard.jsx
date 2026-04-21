// @ts-nocheck
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/apiClient';
import { FileText, ListChecks, ClipboardCheck, Activity } from 'lucide-react';
import StatCard from '@/components/shared/StatCard';
import RecentPracticesTable from '@/components/dashboard/RecentPracticesTable';
import QuickActions from '@/components/dashboard/QuickActions';

export default function Dashboard() {
  const { data: practices = [], isLoading } = useQuery({
    queryKey: ['practices'],
    queryFn: () => api.pratiche.list({ limit: 50, sort: '-created_date' }),
    initialData: [],
  });

  const reportCount = practices.filter(p => p.type === 'report').length;
  const jsonCount   = practices.filter(p => p.type === 'checklist_json').length;
  const wordCount   = practices.filter(p => p.type === 'checklist_word').length;
  const todayCount  = practices.filter(p => {
    if (!p.created_date) return false;
    return new Date(p.created_date).toDateString() === new Date().toDateString();
  }).length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">Panoramica attività e accesso rapido ai workflow</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Totale Report"   value={reportCount} icon={FileText} />
        <StatCard label="Checklist JSON"  value={jsonCount}   icon={ListChecks} />
        <StatCard label="Checklist Word"  value={wordCount}   icon={ClipboardCheck} />
        <StatCard label="Pratiche Oggi"   value={todayCount}  icon={Activity} />
      </div>

      <QuickActions />
      <RecentPracticesTable practices={practices} isLoading={isLoading} />
    </div>
  );
}
