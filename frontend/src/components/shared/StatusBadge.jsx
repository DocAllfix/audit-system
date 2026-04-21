import React from 'react';
import { Badge } from '@/components/ui/badge';

const variants = {
  report: { label: 'Report', className: 'bg-primary/10 text-primary border-primary/30' },
  checklist_json: { label: 'JSON', className: 'bg-info/10 text-info border-info/30' },
  checklist_word: { label: 'Checklist', className: 'bg-purple-500/10 text-purple-400 border-purple-500/30' },
  completed: { label: 'Completato', className: 'bg-success/10 text-success border-success/30' },
  processing: { label: 'In corso', className: 'bg-warning/10 text-warning border-warning/30' },
  error: { label: 'Errore', className: 'bg-destructive/10 text-destructive border-destructive/30' },
  pending: { label: 'In attesa', className: 'bg-muted text-muted-foreground border-border' },
};

export default function StatusBadge({ type, label: customLabel }) {
  const v = variants[type] || variants.pending;
  return (
    <Badge variant="outline" className={`text-[11px] font-medium ${v.className}`}>
      {customLabel || v.label}
    </Badge>
  );
}