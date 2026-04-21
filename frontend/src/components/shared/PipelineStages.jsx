// @ts-nocheck
import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, Loader2 } from 'lucide-react';

/**
 * PipelineStages — mostra le fasi della pipeline con progresso reale.
 *
 * Props:
 *   stages       [{ id, label, description }]
 *   currentStage number  — indice fase attiva (0-based)
 *   progress     number  — percentuale 0-100 (opzionale, per barra interna)
 *   message      string  — messaggio live dal server (opzionale)
 */
export default function PipelineStages({ stages, currentStage, progress, message }) {
  return (
    <div className="space-y-5">
      {/* Fasi */}
      <div className="flex items-center gap-2 justify-center py-2">
        {stages.map((stage, i) => {
          const isDone   = i < currentStage;
          const isActive = i === currentStage;
          const isPending = i > currentStage;

          return (
            <React.Fragment key={stage.id}>
              <div className="flex flex-col items-center gap-2">
                <div className={`
                  relative w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-300
                  ${isDone   ? 'bg-success text-white' : ''}
                  ${isActive ? 'bg-primary text-white pulse-ring' : ''}
                  ${isPending ? 'border-2 border-muted-foreground/20 text-muted-foreground/40' : ''}
                `}>
                  {isDone
                    ? <Check className="w-5 h-5" />
                    : isActive
                      ? <Loader2 className="w-5 h-5 animate-spin" />
                      : i + 1}
                </div>
                <div className="text-center">
                  <p className={`text-xs font-semibold ${isActive ? 'text-primary' : isDone ? 'text-success' : 'text-muted-foreground'}`}>
                    {stage.label}
                  </p>
                  <p className="text-[11px] text-muted-foreground/60">{stage.description}</p>
                </div>
              </div>
              {i < stages.length - 1 && (
                <div className={`flex-1 h-0.5 min-w-[40px] max-w-[80px] transition-colors duration-500 ${isDone ? 'bg-success' : 'bg-muted-foreground/20'}`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Barra di progresso reale */}
      {progress !== undefined && (
        <div className="space-y-1.5">
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <motion.div
              className="h-full rounded-full bg-primary"
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
              transition={{ duration: 0.4, ease: 'easeOut' }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span className="truncate max-w-[85%]">{message || 'Elaborazione in corso…'}</span>
            <span className="font-mono shrink-0">{Math.round(progress)}%</span>
          </div>
        </div>
      )}

      {/* Messaggio live senza barra (quando progress non è fornito) */}
      {progress === undefined && message && (
        <AnimatePresence mode="wait">
          <motion.p
            key={message}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="text-xs text-center text-muted-foreground px-4"
          >
            {message}
          </motion.p>
        </AnimatePresence>
      )}
    </div>
  );
}
