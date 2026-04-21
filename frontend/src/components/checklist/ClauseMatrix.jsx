import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, CheckCircle2, AlertCircle, AlertTriangle, Minus } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';

const getStatus = (clause) => {
  if (!clause.text || clause.text.trim() === '') return { key: 'empty', label: 'Vuota', icon: AlertCircle, color: 'text-destructive', bg: 'bg-destructive/5 border-destructive/20' };
  const words = clause.text.trim().split(/\s+/).length;
  if (words >= 150) return { key: 'ok', label: 'OK', icon: CheckCircle2, color: 'text-success', bg: '' };
  if (words >= 100) return { key: 'short', label: 'Breve', icon: AlertTriangle, color: 'text-warning', bg: 'bg-warning/5 border-warning/20' };
  return { key: 'too_short', label: 'Corta', icon: AlertCircle, color: 'text-destructive', bg: 'bg-destructive/5 border-destructive/20' };
};

const filters = [
  { key: 'all', label: 'Tutte' },
  { key: 'ok', label: '✅ Complete' },
  { key: 'problematic', label: '🔴 Problematiche' },
  { key: 'short', label: '🟡 Brevi' },
];

export default function ClauseMatrix({ clauses, onClauseUpdate }) {
  const [activeFilter, setActiveFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedClause, setSelectedClause] = useState(null);
  const [editText, setEditText] = useState('');
  const [editing, setEditing] = useState(false);

  const filtered = clauses.filter(c => {
    const status = getStatus(c);
    if (activeFilter === 'ok' && status.key !== 'ok') return false;
    if (activeFilter === 'problematic' && status.key !== 'too_short' && status.key !== 'empty') return false;
    if (activeFilter === 'short' && status.key !== 'short') return false;
    if (search && !c.id.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const stats = {
    ok: clauses.filter(c => getStatus(c).key === 'ok').length,
    short: clauses.filter(c => getStatus(c).key === 'short').length,
    problem: clauses.filter(c => getStatus(c).key === 'too_short' || getStatus(c).key === 'empty').length,
    total: clauses.length,
  };
  const completeness = clauses.length > 0 ? Math.round((stats.ok / clauses.length) * 100) : 0;

  const openClause = (clause) => {
    setSelectedClause(clause);
    setEditText(clause.text || '');
    setEditing(false);
  };

  const saveEdit = () => {
    if (selectedClause && onClauseUpdate) {
      onClauseUpdate(selectedClause.id, editText);
    }
    setEditing(false);
  };

  return (
    <div className="space-y-4">
      {/* Stats header */}
      <div className="flex flex-wrap items-center gap-3 p-4 rounded-lg bg-muted/30 border border-border">
        <Badge variant="outline" className="bg-success/10 text-success border-success/30">{stats.ok}/{stats.total} ✅</Badge>
        <Badge variant="outline" className="bg-destructive/10 text-destructive border-destructive/30">{stats.problem}/{stats.total} 🔴</Badge>
        <Badge variant="outline" className="bg-warning/10 text-warning border-warning/30">{stats.short}/{stats.total} 🟡</Badge>
        <span className="text-sm font-semibold ml-auto">Completezza: {completeness}%</span>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {filters.map(f => (
          <Button
            key={f.key}
            variant={activeFilter === f.key ? 'default' : 'outline'}
            size="sm"
            className={`text-xs h-8 ${activeFilter === f.key ? 'brand-gradient text-white' : ''}`}
            onClick={() => setActiveFilter(f.key)}
          >
            {f.label}
          </Button>
        ))}
        <div className="relative ml-auto">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Cerca clausola..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="h-8 pl-8 text-xs w-48"
          />
        </div>
      </div>

      {/* Clause rows */}
      <div className="rounded-lg border border-border overflow-hidden">
        <div className="grid grid-cols-[140px_80px_70px_1fr] gap-0 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground bg-muted/30 px-4 py-2.5 border-b border-border">
          <span>Clausola ID</span>
          <span>Stato</span>
          <span>Parole</span>
          <span>Preview</span>
        </div>
        <ScrollArea className="max-h-[400px]">
          {filtered.map((clause, i) => {
            const status = getStatus(clause);
            const Icon = status.icon;
            const words = clause.text ? clause.text.trim().split(/\s+/).length : 0;
            const preview = clause.text ? clause.text.slice(0, 60) + (clause.text.length > 60 ? '...' : '') : '—';

            return (
              <motion.div
                key={clause.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.01 }}
                onClick={() => openClause(clause)}
                className={`grid grid-cols-[140px_80px_70px_1fr] gap-0 px-4 py-2.5 text-sm border-b border-border/50 cursor-pointer hover:bg-muted/20 transition-colors ${status.bg}`}
              >
                <span className="font-mono text-xs text-muted-foreground">{clause.id}</span>
                <div className="flex items-center gap-1.5">
                  <Icon className={`w-3.5 h-3.5 ${status.color}`} />
                  <span className={`text-xs font-medium ${status.color}`}>{status.label}</span>
                </div>
                <span className="font-mono text-xs">{words}</span>
                <span className="text-xs text-muted-foreground truncate">{preview}</span>
              </motion.div>
            );
          })}
        </ScrollArea>
      </div>

      {/* Detail drawer */}
      <Sheet open={!!selectedClause} onOpenChange={(open) => !open && setSelectedClause(null)}>
        <SheetContent className="w-[400px] sm:max-w-[400px]">
          <SheetHeader>
            <SheetTitle className="font-mono text-sm">{selectedClause?.id}</SheetTitle>
          </SheetHeader>
          <div className="mt-4 space-y-4">
            <div>
              <p className="text-xs text-muted-foreground mb-1">Parole: {editText.trim().split(/\s+/).filter(Boolean).length}</p>
              {editing ? (
                <div className="space-y-2">
                  <Textarea value={editText} onChange={e => setEditText(e.target.value)} rows={12} className="text-sm" />
                  <div className="flex gap-2">
                    <Button size="sm" className="brand-gradient text-white" onClick={saveEdit}>Salva</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditing(false)}>Annulla</Button>
                  </div>
                </div>
              ) : (
                <div>
                  <div className="p-3 rounded-md bg-muted/30 border text-sm leading-relaxed max-h-[300px] overflow-y-auto">
                    {selectedClause?.text || <span className="text-muted-foreground italic">Nessun contenuto</span>}
                  </div>
                  <Button size="sm" variant="outline" className="mt-2" onClick={() => setEditing(true)}>
                    ✏️ Modifica Manuale
                  </Button>
                </div>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}