// @ts-nocheck
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/apiClient';
import { useAuth } from '@/lib/AuthContext';
import { motion } from 'framer-motion';
import { Shield, Globe, Clock, CheckCircle2, Calendar, BarChart3, Lock } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Cell } from 'recharts';
import StatCard from '@/components/shared/StatCard';

const barColors = [
  'hsl(174, 58%, 40%)',
  'hsl(174, 58%, 50%)',
  'hsl(174, 58%, 35%)',
  'hsl(174, 58%, 45%)',
  'hsl(174, 58%, 30%)',
];

export default function AdminPanel() {
  const { user } = useAuth();

  const { data: practices = [] } = useQuery({
    queryKey: ['admin-practices'],
    queryFn: () => api.pratiche.list({ limit: 500, sort: '-created_date' }),
    initialData: [],
    enabled: user?.role === 'admin',
  });

  if (user && user.role !== 'admin') {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="p-4 rounded-2xl bg-muted/50 mb-4">
          <Lock className="w-12 h-12 text-muted-foreground/50" />
        </div>
        <h3 className="text-lg font-semibold">Accesso Riservato</h3>
        <p className="text-sm text-muted-foreground mt-1">Questa sezione è riservata agli amministratori.</p>
      </div>
    );
  }

  const totalPractices = practices.length;
  const avgTime = practices.length > 0
    ? Math.round(practices.reduce((sum, p) => sum + (p.processing_time_seconds || 0), 0) / practices.length)
    : 0;
  const successRate = practices.length > 0
    ? Math.round((practices.filter(p => p.status === 'completed').length / practices.length) * 100)
    : 0;
  const todayCount = practices.filter(p =>
    p.created_date && new Date(p.created_date).toDateString() === new Date().toDateString()
  ).length;

  const userBreakdown = {};
  practices.forEach(p => {
    const email = p.created_by || 'unknown';
    userBreakdown[email] = (userBreakdown[email] || 0) + 1;
  });
  const userChartData = Object.entries(userBreakdown)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8)
    .map(([email, count]) => ({ name: email.split('@')[0], count }));

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <Shield className="w-6 h-6 text-primary" /> Pannello Admin
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Statistiche globali e breakdown per utente</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Totale Sistema" value={totalPractices} icon={Globe} />
        <StatCard label="Tempo Medio"    value={avgTime}         suffix="s" icon={Clock} />
        <StatCard label="Tasso Successo" value={successRate}     suffix="%" icon={CheckCircle2} />
        <StatCard label="Oggi"           value={todayCount}      icon={Calendar} />
      </div>

      <Card className="glass">
        <CardHeader>
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-primary" /> Pratiche per Utente
          </CardTitle>
        </CardHeader>
        <CardContent>
          {userChartData.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">Nessun dato disponibile</p>
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={userChartData} layout="vertical" margin={{ left: 20, right: 20 }}>
                <XAxis type="number" stroke="hsl(215, 16%, 47%)" fontSize={11} />
                <YAxis type="category" dataKey="name" stroke="hsl(215, 16%, 47%)" fontSize={11} width={80} />
                <RechartsTooltip
                  contentStyle={{ background: 'hsl(230, 22%, 8%)', border: '1px solid hsl(230, 10%, 14%)', borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: 'hsl(210, 40%, 96%)' }}
                />
                <Bar dataKey="count" radius={[0, 6, 6, 0]}>
                  {userChartData.map((_, i) => (
                    <Cell key={i} fill={barColors[i % barColors.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
