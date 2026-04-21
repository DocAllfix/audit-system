// @ts-nocheck
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/apiClient';
import { useAuth } from '@/lib/AuthContext';
import { motion } from 'framer-motion';
import { format } from 'date-fns';
import { it } from 'date-fns/locale';
import { AlertTriangle, CheckCircle2, Eye, Lock } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ScrollArea } from '@/components/ui/scroll-area';
import EmptyState from '@/components/shared/EmptyState';
import { toast } from 'sonner';

const errorTypeColors = {
  api_error:   'bg-destructive/10 text-destructive border-destructive/30',
  ocr_error:   'bg-warning/10 text-warning border-warning/30',
  timeout:     'bg-info/10 text-info border-info/30',
  parse_error: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
  file_error:  'bg-warning/10 text-warning border-warning/30',
  unknown:     'bg-muted text-muted-foreground border-border',
};

export default function AdminErrorLog() {
  const { user } = useAuth();
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedError, setSelectedError] = useState(null);
  const queryClient = useQueryClient();

  const { data: errors = [], isLoading } = useQuery({
    queryKey: ['error-logs'],
    queryFn: () => api.errors.list(),
    initialData: [],
    enabled: user?.role === 'admin',
  });

  const resolveMutation = useMutation({
    mutationFn: (errorId) => api.errors.resolve(errorId, user?.email),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['error-logs'] });
      queryClient.invalidateQueries({ queryKey: ['unresolved-errors-count'] });
      toast.success('Errore segnato come risolto');
      setSelectedError(null);
    },
    onError: (err) => toast.error(err.message || 'Errore durante la risoluzione'),
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

  const unresolvedCount = errors.filter(e => !e.resolved).length;
  const filtered = errors.filter(e => {
    if (statusFilter === 'unresolved') return !e.resolved;
    if (statusFilter === 'recovered')  return e.auto_recovered;
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <AlertTriangle className="w-6 h-6 text-warning" /> Log Errori
        </h1>
        <div className="flex items-center gap-3 mt-2">
          {unresolvedCount > 0 && (
            <Badge variant="destructive" className="text-xs">🔴 {unresolvedCount} non risolti</Badge>
          )}
          <span className="text-xs text-muted-foreground">Totale: {errors.length}</span>
        </div>
      </div>

      {/* Filtri */}
      <div className="flex gap-2">
        {[
          { value: 'all',        label: 'Tutti' },
          { value: 'unresolved', label: 'Non risolti' },
          { value: 'recovered',  label: 'Auto-recuperati' },
        ].map(f => (
          <Button
            key={f.value}
            size="sm"
            variant={statusFilter === f.value ? 'default' : 'outline'}
            className={`text-xs h-8 ${statusFilter === f.value ? 'brand-gradient text-white' : ''}`}
            onClick={() => setStatusFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={CheckCircle2} title="Tutto ok!" description="Nessun errore da mostrare." />
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead className="text-xs">Data</TableHead>
                <TableHead className="text-xs">Utente</TableHead>
                <TableHead className="text-xs">Tab</TableHead>
                <TableHead className="text-xs">Tipo</TableHead>
                <TableHead className="text-xs">Azienda</TableHead>
                <TableHead className="text-xs">Auto-rec</TableHead>
                <TableHead className="text-xs">Stato</TableHead>
                <TableHead className="text-xs">Azioni</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((err) => (
                <TableRow key={err.id} className="hover:bg-muted/20 transition-colors">
                  <TableCell className="text-xs text-muted-foreground">
                    {err.created_date ? format(new Date(err.created_date), 'dd/MM HH:mm', { locale: it }) : '—'}
                  </TableCell>
                  <TableCell className="text-xs">{err.created_by?.split('@')[0] || '—'}</TableCell>
                  <TableCell className="text-xs font-mono">{err.tab || '—'}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-[10px] ${errorTypeColors[err.error_type] || errorTypeColors.unknown}`}>
                      {err.error_type}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{err.company_name || '—'}</TableCell>
                  <TableCell className="text-xs">
                    {err.auto_recovered
                      ? <span className="text-success">✅ Sì</span>
                      : <span className="text-destructive">❌ No</span>
                    }
                  </TableCell>
                  <TableCell>
                    {err.resolved
                      ? <Badge variant="outline" className="bg-success/10 text-success border-success/30 text-[10px]">Risolto</Badge>
                      : <Badge variant="outline" className="bg-destructive/10 text-destructive border-destructive/30 text-[10px]">Aperto</Badge>
                    }
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setSelectedError(err)}>
                        <Eye className="w-3.5 h-3.5" />
                      </Button>
                      {!err.resolved && (
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-success"
                          onClick={() => resolveMutation.mutate(err.id)}
                          disabled={resolveMutation.isPending}
                        >
                          <CheckCircle2 className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Drawer dettaglio errore */}
      <Sheet open={!!selectedError} onOpenChange={(open) => !open && setSelectedError(null)}>
        <SheetContent className="w-[440px] sm:max-w-[440px]">
          <SheetHeader>
            <SheetTitle className="text-sm">Dettaglio Errore</SheetTitle>
          </SheetHeader>
          {selectedError && (
            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div><p className="text-muted-foreground">Utente</p><p className="font-medium">{selectedError.created_by || '—'}</p></div>
                <div><p className="text-muted-foreground">Tab</p><p className="font-medium font-mono">{selectedError.tab}</p></div>
                <div><p className="text-muted-foreground">Azienda</p><p className="font-medium">{selectedError.company_name || '—'}</p></div>
                <div>
                  <p className="text-muted-foreground">Tipo</p>
                  <Badge variant="outline" className={`text-[10px] ${errorTypeColors[selectedError.error_type] || ''}`}>
                    {selectedError.error_type}
                  </Badge>
                </div>
              </div>

              <div>
                <p className="text-xs text-muted-foreground mb-1">Messaggio</p>
                <p className="text-sm p-3 rounded-md bg-muted/30 border">{selectedError.message}</p>
              </div>

              {selectedError.stack_trace && (
                <Collapsible>
                  <CollapsibleTrigger className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                    ▶ Stack Trace
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <ScrollArea className="max-h-[200px] mt-2">
                      <pre className="text-[11px] font-mono p-3 rounded-md bg-background border text-muted-foreground leading-5">
                        {selectedError.stack_trace}
                      </pre>
                    </ScrollArea>
                  </CollapsibleContent>
                </Collapsible>
              )}

              {selectedError.auto_recovered && (
                <div className="p-3 rounded-md bg-success/5 border border-success/20">
                  <p className="text-xs text-success font-medium">✅ Auto-recuperato</p>
                </div>
              )}

              {!selectedError.resolved && (
                <Button
                  className="w-full brand-gradient text-white"
                  onClick={() => resolveMutation.mutate(selectedError.id)}
                  disabled={resolveMutation.isPending}
                >
                  <CheckCircle2 className="w-4 h-4 mr-2" /> Segna come Risolto
                </Button>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
