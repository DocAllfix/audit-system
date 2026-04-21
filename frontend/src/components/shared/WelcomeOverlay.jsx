import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { FileArchive, ListChecks, ClipboardCheck, ArrowRight, X } from 'lucide-react';

const STORAGE_KEY = 'audit-os-welcome-count';
const MAX_SHOWS = 3;

const steps = [
  { icon: FileArchive,    num: '①', text: 'Carica uno ZIP di documenti aziendali',       color: 'text-primary' },
  { icon: ListChecks,     num: '②', text: 'Genera il Report di Evidenze con analisi AI',  color: 'text-success' },
  { icon: ClipboardCheck, num: '③', text: 'Compila automaticamente la checklist ISO',     color: 'text-info'    },
];

export default function WelcomeOverlay({ user }) {
  const [visible, setVisible] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const count = parseInt(localStorage.getItem(STORAGE_KEY) || '0', 10);
    if (count < MAX_SHOWS) {
      localStorage.setItem(STORAGE_KEY, String(count + 1));
      setVisible(true);
    }
  }, []);

  const firstName = user?.full_name
    ? user.full_name.trim().split(' ')[0]
    : (user?.username || null);

  const dismiss = () => setVisible(false);

  const start = () => {
    dismiss();
    navigate('/workflow/report');
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.94, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.94, y: 20 }}
            transition={{ type: 'spring', stiffness: 300, damping: 25 }}
            className="relative max-w-md w-full rounded-2xl border border-border bg-card card-glow p-8"
          >
            <button
              onClick={dismiss}
              className="absolute top-4 right-4 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            {/* Logo + Title */}
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-xl brand-gradient flex items-center justify-center shrink-0">
                <span className="text-white font-bold font-mono">A</span>
              </div>
              <div>
                <h2 className="text-lg font-bold tracking-tight leading-tight">
                  {firstName ? `Ciao ${firstName}, benvenuto` : 'Benvenuto'} in AUDIT-OS! 👋
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">Sistema automatizzato per audit documentale</p>
              </div>
            </div>

            <p className="text-sm text-muted-foreground mt-5 mb-4">In 3 passi semplici:</p>

            <div className="space-y-3 mb-7">
              {steps.map(({ icon: Icon, num, text, color }, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.15 + i * 0.08 }}
                  className="flex items-center gap-3"
                >
                  <div className={`w-8 h-8 rounded-lg bg-muted/50 flex items-center justify-center shrink-0 text-sm font-bold ${color}`}>
                    {num}
                  </div>
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Icon className={`w-4 h-4 shrink-0 ${color}`} />
                    <span className="text-sm">{text}</span>
                  </div>
                </motion.div>
              ))}
            </div>

            <div className="flex flex-col gap-2">
              <Button onClick={start} className="w-full brand-gradient text-white font-semibold h-11">
                <ArrowRight className="w-4 h-4 mr-2" />
                Inizia dalla Tab "Genera Report"
              </Button>
              <Button onClick={dismiss} variant="ghost" className="w-full text-muted-foreground text-sm h-9">
                Salta — mostrami l'app
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
