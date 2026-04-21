import React, { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useWorkflowStore } from '@/store/workflowStore';

export default function WorkflowLayout() {
  const navigate = useNavigate();
  const { session, resetSession } = useWorkflowStore();
  const [showResetDialog, setShowResetDialog] = useState(false);

  const activeSession = session.practiceId && (
    session.tab1.status !== 'idle' ||
    session.tab2.status !== 'idle' ||
    session.tab3.status !== 'idle'
  );

  const confirmReset = () => {
    resetSession();
    setShowResetDialog(false);
    navigate('/workflow/report');
  };

  return (
    <>
      <Outlet />

      {/* Reset confirmation dialog */}
      <AnimatePresence>
        {showResetDialog && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 backdrop-blur-sm p-4"
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="max-w-sm w-full rounded-xl border border-border bg-card p-6 shadow-xl space-y-4"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-warning/10">
                  <AlertTriangle className="w-5 h-5 text-warning" />
                </div>
                <div>
                  <p className="font-semibold text-sm">Avviare una nuova pratica?</p>
                  <p className="text-xs text-muted-foreground">I dati non salvati andranno persi.</p>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="ghost" size="sm" onClick={() => setShowResetDialog(false)}>
                  Annulla
                </Button>
                <Button size="sm" className="brand-gradient text-white" onClick={confirmReset}>
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Nuova pratica
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}