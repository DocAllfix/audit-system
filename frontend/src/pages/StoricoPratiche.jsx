// @ts-nocheck
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/apiClient';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import { format } from 'date-fns';
import { it } from 'date-fns/locale';
import { Search, FolderOpen, ChevronLeft, ChevronRight } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import StatusBadge from '@/components/shared/StatusBadge';
import EmptyState from '@/components/shared/EmptyState';
import ExportMenu from '@/components/shared/ExportMenu';
import { SUPPORTED_NORMS } from '@/lib/constants';

const PAGE_SIZE = 10;

function useUrlFilters() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);

  const typeFilter = params.get('tipo')  || 'all';
  const normFilter = params.get('norma') || 'all';
  const search     = params.get('q')     || '';
  const page       = parseInt(params.get('pag') || '0', 10);

  const setFilters = (updates) => {
    const next = new URLSearchParams(location.search);
    Object.entries(updates).forEach(([k, v]) => {
      if (!v || v === 'all' || v === '' || v === '0') next.delete(k);
      else next.set(k, v);
    });
    if (!('pag' in updates)) next.delete('pag');
    navigate({ search: next.toString() }, { replace: true });
  };

  return { typeFilter, normFilter, search, page, setFilters };
}

export default function StoricoPratiche() {
  const { typeFilter, normFilter, search, page, setFilters } = useUrlFilters();

  const { data: practices = [], isLoading } = useQuery({
    queryKey: ['all-practices'],
    queryFn: () => api.pratiche.list({ limit: 200, sort: '-created_date' }),
    initialData: [],
  });

  const filtered = practices.filter(p => {
    if (typeFilter !== 'all' && p.type !== typeFilter) return false;
    if (normFilter !== 'all' && p.norm !== normFilter) return false;
    if (search && !p.company_name?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const norms = [...new Set(practices.map(p => p.norm).filter(Boolean))];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Storico Pratiche</h1>
        <p className="text-sm text-muted-foreground mt-1">{filtered.length} pratiche trovate</p>
      </div>

      {/* Filtri */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Cerca per azienda..."
            value={search}
            onChange={e => setFilters({ q: e.target.value })}
            className="pl-9"
          />
        </div>
        <Select value={typeFilter} onValueChange={v => setFilters({ tipo: v })}>
          <SelectTrigger className="w-36"><SelectValue placeholder="Tipo" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tutti i tipi</SelectItem>
            <SelectItem value="report">Report</SelectItem>
            <SelectItem value="checklist_json">JSON</SelectItem>
            <SelectItem value="checklist_word">Checklist</SelectItem>
          </SelectContent>
        </Select>
        <Select value={normFilter} onValueChange={v => setFilters({ norma: v })}>
          <SelectTrigger className="w-36"><SelectValue placeholder="Norma" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tutte le norme</SelectItem>
            {norms.map(n => <SelectItem key={n} value={n}>{n}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button
          variant="ghost" size="sm" className="text-xs"
          onClick={() => setFilters({ tipo: 'all', norma: 'all', q: '', pag: '0' })}
        >
          Reset
        </Button>
        <div className="ml-auto">
          <ExportMenu mode="list" practices={filtered} />
        </div>
      </div>

      {/* Tabella */}
      {isLoading ? (
        <div className="space-y-3">
          {Array(5).fill(0).map((_, i) => <Skeleton key={i} className="h-12 w-full rounded-md" />)}
        </div>
      ) : paged.length === 0 ? (
        <EmptyState icon={FolderOpen} title="Nessuna pratica trovata" description="Modifica i filtri o crea una nuova pratica." />
      ) : (
        <>
          <div className="rounded-lg border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30 hover:bg-muted/30">
                  <TableHead className="text-xs">#</TableHead>
                  <TableHead className="text-xs">Tipo</TableHead>
                  <TableHead className="text-xs">Azienda</TableHead>
                  <TableHead className="text-xs">Norma</TableHead>
                  <TableHead className="text-xs">Data</TableHead>
                  <TableHead className="text-xs">Tempo</TableHead>
                  <TableHead className="text-xs">Azioni</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paged.map((p, i) => (
                  <motion.tr
                    key={p.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="border-b border-border/50 hover:bg-muted/20 transition-colors"
                  >
                    <TableCell className="text-xs text-muted-foreground font-mono">{page * PAGE_SIZE + i + 1}</TableCell>
                    <TableCell><StatusBadge type={p.type} /></TableCell>
                    <TableCell className="font-medium text-sm">{p.company_name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{p.norm || '—'}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {p.created_date ? format(new Date(p.created_date), 'dd/MM/yyyy HH:mm', { locale: it }) : '—'}
                    </TableCell>
                    <TableCell>
                      <span className={`font-mono text-xs ${
                        (p.processing_time_seconds || 0) < 60  ? 'text-success' :
                        (p.processing_time_seconds || 0) < 180 ? 'text-warning'  : 'text-destructive'
                      }`}>
                        {p.processing_time_seconds ? `${p.processing_time_seconds}s` : '—'}
                      </span>
                    </TableCell>
                    <TableCell>
                      <ExportMenu mode="single" practice={p} />
                    </TableCell>
                  </motion.tr>
                ))}
              </TableBody>
            </Table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button variant="ghost" size="icon" disabled={page === 0} onClick={() => setFilters({ pag: String(page - 1) })}>
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-sm text-muted-foreground">Pagina {page + 1} di {totalPages}</span>
              <Button variant="ghost" size="icon" disabled={page >= totalPages - 1} onClick={() => setFilters({ pag: String(page + 1) })}>
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
