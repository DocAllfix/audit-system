import React from 'react';
import { motion } from 'framer-motion';
import { Check, Loader2, AlertTriangle, RotateCcw } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

const statusConfig = {
  pending: { bg: 'bg-muted/40 border-dashed border-muted-foreground/20', icon: null, label: '?' },
  processing: { bg: 'bg-primary/10 border-primary/40', icon: Loader2, label: null, spin: true },
  success: { bg: 'bg-success/10 border-success/30', icon: Check, color: 'text-success' },
  error: { bg: 'bg-destructive/10 border-destructive/30', icon: AlertTriangle, color: 'text-destructive' },
  recovered: { bg: 'bg-warning/10 border-warning/30', icon: RotateCcw, color: 'text-warning' },
};

export default function BatchGrid({ batches = [] }) {
  return (
    <TooltipProvider>
      <div className="flex flex-wrap gap-2">
        {batches.map((batch, i) => {
          const cfg = statusConfig[batch.status] || statusConfig.pending;
          const Icon = cfg.icon;
          return (
            <Tooltip key={i}>
              <TooltipTrigger>
                <motion.div
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: i * 0.03 }}
                  className={`
                    w-14 h-14 rounded-lg border flex flex-col items-center justify-center text-xs font-mono transition-all duration-200
                    ${cfg.bg}
                  `}
                >
                  {Icon ? (
                    <Icon className={`w-4 h-4 ${cfg.color || 'text-primary'} ${cfg.spin ? 'animate-spin' : ''}`} />
                  ) : (
                    <span className="text-muted-foreground/40 font-bold">{i + 1}</span>
                  )}
                  {batch.duration && (
                    <span className="text-[10px] text-muted-foreground mt-0.5">{batch.duration}s</span>
                  )}
                </motion.div>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-xs">Batch {i + 1}: {batch.status}</p>
                {batch.error && <p className="text-xs text-destructive">{batch.error}</p>}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}