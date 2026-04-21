// @ts-nocheck
import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useQueryClient } from '@tanstack/react-query';
import { useWorkflowStore } from '@/store/workflowStore';
import { useSSEProcess } from '@/hooks/useSSEProcess';
import { SUPPORTED_NORMS } from '@/lib/constants';
import { FileText, ListChecks, Download, ArrowRight, CheckCircle2, Building2, RotateCcw, Copy, ChevronDown } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Badge } from '@/components/ui/badge';
import FileDropzone from '@/components/shared/FileDropzone';
import PipelineStages from '@/components/shared/PipelineStages';
import ClauseMatrix from '@/components/checklist/ClauseMatrix';
import { toast } from 'sonner';
import { toastError } from '@/lib/toastError';

const norms = SUPPORTED_NORMS.map(n => ({
  value: n.id,
  label: `${n.id} — ${n.label}`,
  clauses: n.clauseCount,
  template: `Template${n.id.replace(/\s/g, '')}.${n.templateType}`,
  isExcel: n.isExcel,
}));

const stages = [
  { id: 'extract',  label: 'ESTRAI',  description: 'Estrazione testo dal report' },
  { id: 'generate', label: 'GENERA',  description: 'Generazione JSON clausole' },
  { id: 'validate', label: 'VALIDA',  description: 'Validazione struttura JSON' },
];

function pctToStage(pct) {
  if (pct < 15) return 0;
  if (pct < 85) return 1;
  return 2;
}

function clausolesToArray(clausole) {
  return Object.entries(clausole || {}).map(([id, text]) => ({ id, text: text || '' }));
}

export default function ProduciChecklist() {
  const [reportFile, setReportFile]     = useState(null);
  const [selectedNorm, setSelectedNorm] = useState('');
  const [phase, setPhase]               = useState('input');
  const [jsonResult, setJsonResult]     = useState(null);
  const [clauses, setClauses]           = useState([]);
  const [companyName, setCompanyName]   = useState('');
  const [editingName, setEditingName]   = useState(false);
  const [jsonOpen, setJsonOpen]         = useState(false);
  const queryClient  = useQueryClient();
  const { setTab2Status, setTab2Json, setCompanyName: storeSetCompanyName, addNotification } = useWorkflowStore();

  const sse        = useSSEProcess();
  const sseRecover = useSSEProcess();
  const location = useLocation();
  const normData = norms.find(n => n.value === selectedNorm);

  // Se arriviamo da Tab 1 con il report già prodotto, pre-carica il file
  useEffect(() => {
    if (location.state?.reportFile) {
      setReportFile(location.state.reportFile);
      if (location.state.companyName) setCompanyName(location.state.companyName);
      // Pulisce lo state dal history per evitare ricaricamenti su back/forward
      window.history.replaceState({}, '');
    }
  }, []);
  const currentStage = pctToStage(sse.progress);
  const incompleteCount = clauses.filter(c => (c.text?.trim().split(/\s+/).length || 0) < 100).length;

  const handleClauseUpdate = (clauseId, newText) => {
    setClauses(prev => prev.map(c => c.id === clauseId ? { ...c, text: newText } : c));
    setJsonResult(prev => prev ? { ...prev, clausole: { ...prev.clausole, [clauseId]: newText } } : prev);
  };

  const handleGenerate = async () => {
    if (!reportFile || !selectedNorm) return;
    setPhase('processing');
    setTab2Status('processing');

    const form = new FormData();
    form.append('file', reportFile);
    form.append('norm', selectedNorm);
    if (companyName) form.append('company_name', companyName);

    await sse.start('/api/checklist/produce', form, {
      onDone: (data) => {
        const json = data.json;
        setJsonResult(json);
        setClauses(clausolesToArray(json.clausole));
        const azienda = json.azienda || '';
        setCompanyName(azienda);
        storeSetCompanyName(azienda);
        setTab2Json(json);
        setTab2Status('completed', { filename: data.filename });
        addNotification({ type: 'success', title: 'Checklist JSON generata', body: `${azienda ? azienda + ' — ' : ''}${selectedNorm}` });
        queryClient.invalidateQueries({ queryKey: ['all-practices'] });
        setPhase('results');
      },
      onError: (err) => {
        setPhase('input');
        setTab2Status('error');
        addNotification({ type: 'error', title: 'Errore Tab 2', body: err.message });
        toastError(err.message || 'Errore durante la generazione del JSON');
      },
    });
  };

  const handleRecover = async () => {
    if (!reportFile || !jsonResult) return;
    const incompleteKeys = clauses
      .filter(c => (c.text?.trim().split(/\s+/).length || 0) < 100)
      .map(c => c.id);
    if (incompleteKeys.length === 0) { toast.success('Nessuna clausola da recuperare'); return; }

    const currentJson = {
      ...jsonResult,
      azienda: companyName,
      clausole: clauses.reduce((acc, c) => ({ ...acc, [c.id]: c.text }), {}),
    };

    const form = new FormData();
    form.append('file', reportFile);
    form.append('json_data', JSON.stringify(currentJson));
    form.append('incomplete_keys', JSON.stringify(incompleteKeys));
    form.append('norm', selectedNorm);

    await sseRecover.start('/api/checklist/recover', form, {
      onDone: (data) => {
        setJsonResult(data.json);
        setClauses(clausolesToArray(data.json.clausole));
        const stillMissing = data.still_missing || [];
        if (stillMissing.length > 0) {
          toast.warning(`Recovery parziale — ${stillMissing.length} clausole ancora incomplete`);
          addNotification({ type: 'warning', title: 'Recovery parziale', body: `${stillMissing.length} clausole ancora incomplete` });
        } else {
          toast.success('Tutte le clausole recuperate con successo!');
          addNotification({ type: 'success', title: 'Recovery completato', body: 'Tutte le clausole sono state recuperate' });
        }
        sseRecover.reset();
      },
      onError: (err) => {
        addNotification({ type: 'error', title: 'Errore Recovery', body: err.message });
        toastError(err.message || 'Errore durante il recupero clausole');
        sseRecover.reset();
      },
    });
  };

  const handleDownloadJson = () => {
    if (!jsonResult) return;
    const updatedJson = {
      ...jsonResult,
      azienda: companyName,
      clausole: clauses.reduce((acc, c) => ({ ...acc, [c.id]: c.text }), {}),
    };
    const blob = new Blob([JSON.stringify(updatedJson, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Checklist_${selectedNorm.replace(/\s/g, '')}_${companyName.replace(/\s/g, '_')}_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success('JSON scaricato');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Produci Checklist JSON</h1>
        <p className="text-sm text-muted-foreground mt-1">Carica il report Word e genera la checklist strutturata per norma ISO</p>
      </div>

      <AnimatePresence mode="wait">

        {/* ── INPUT ─────────────────────────────────────────────────────── */}
        {phase === 'input' && (
          <motion.div key="input" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">
            {/* Banner auto-caricamento da Tab 1 */}
            {reportFile && location.state?.reportFile && (
              <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}>
                <Card className="glass border-success/20 bg-success/5">
                  <CardContent className="p-3 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
                    <p className="text-xs text-success font-medium">
                      Report caricato automaticamente da Tab 1 — seleziona la norma e procedi
                    </p>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card className="glass">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <FileText className="w-4 h-4 text-primary" /> Report Word
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <FileDropzone
                    accept=".docx,.doc,.pdf"
                    title="Carica il report generato da Tab 1"
                    description="File Word o PDF del report audit"
                    icon={FileText}
                    file={reportFile}
                    onFileSelect={setReportFile}
                    onRemove={() => setReportFile(null)}
                  />
                </CardContent>
              </Card>
              <Card className="glass">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <ListChecks className="w-4 h-4 text-primary" /> Seleziona Norma ISO
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Select value={selectedNorm} onValueChange={setSelectedNorm}>
                    <SelectTrigger><SelectValue placeholder="Seleziona una norma..." /></SelectTrigger>
                    <SelectContent>
                      {norms.map(n => (
                        <SelectItem key={n.value} value={n.value}>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-bold text-primary">{n.value}</span>
                            <span className="text-muted-foreground text-xs">{SUPPORTED_NORMS.find(s => s.id === n.value)?.label}</span>
                            <Badge variant="outline" className="text-[10px]">{n.clauses}</Badge>
                            {n.isExcel && <Badge className="text-[10px] bg-warning/10 text-warning border-warning/30">XLSX</Badge>}
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {normData && (
                    <p className="text-xs text-muted-foreground">
                      📊 {normData.clauses} clausole da compilare · Template: <span className="font-mono">{normData.template}</span>
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>
            <Button
              onClick={handleGenerate}
              disabled={!reportFile || !selectedNorm || sse.isPending}
              className="w-full h-12 brand-gradient text-white font-semibold text-sm hover:brightness-110 disabled:opacity-40"
            >
              <ListChecks className="w-4 h-4 mr-2" /> Genera JSON Checklist
            </Button>
          </motion.div>
        )}

        {/* ── PROCESSING ────────────────────────────────────────────────── */}
        {phase === 'processing' && (
          <motion.div key="processing" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">
            <Card className="glass">
              <CardContent className="p-6">
                <PipelineStages
                  stages={stages}
                  currentStage={currentStage}
                  progress={sse.progress}
                  message={sse.message}
                />
              </CardContent>
            </Card>
            <Card className="glass border-primary/20 bg-primary/5">
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground text-center">
                  ⏳ Generazione clausole in corso — il processo analizza il report in 6 gruppi paralleli.
                  <br />Può richiedere 1–3 minuti. Non chiudere questa scheda.
                </p>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* ── RESULTS ───────────────────────────────────────────────────── */}
        {phase === 'results' && jsonResult && (
          <motion.div key="results" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">

            {/* Nome azienda editabile */}
            <Card className="glass">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <Building2 className="w-4 h-4 text-primary shrink-0" />
                  <span className="text-xs text-muted-foreground shrink-0">Nome Azienda:</span>
                  {editingName ? (
                    <div className="flex items-center gap-2 flex-1">
                      <Input value={companyName} onChange={e => setCompanyName(e.target.value)} className="h-8 text-sm" autoFocus />
                      <Button size="sm" className="h-8 text-xs brand-gradient text-white" onClick={() => setEditingName(false)}>✓</Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{companyName || '—'}</span>
                      <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-muted-foreground" onClick={() => setEditingName(true)}>✏️</Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Statistiche clausole */}
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Totale clausole', value: clauses.length },
                { label: 'Complete (≥100p)',  value: clauses.filter(c => (c.text?.trim().split(/\s+/).length || 0) >= 100).length },
                { label: 'Da rivedere',       value: incompleteCount },
              ].map(s => (
                <Card key={s.label} className="glass">
                  <CardContent className="p-3 text-center">
                    <p className="text-2xl font-bold">{s.value}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* Clause Matrix */}
            <Card className="glass">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold">
                  📊 Analisi Completezza Clausole · {selectedNorm}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ClauseMatrix clauses={clauses} onClauseUpdate={handleClauseUpdate} />
              </CardContent>
            </Card>

            {/* Recovery CTA */}
            {incompleteCount > 0 && (
              <Card className="glass border-warning/20 bg-warning/5">
                <CardContent className="p-4 space-y-3">
                  <p className="text-sm font-semibold">⚠️ {incompleteCount} clausole richiedono attenzione</p>
                  <p className="text-xs text-muted-foreground">
                    Usa "Recupera" per far rianalizzare al server le clausole troppo corte, oppure modificale manualmente nella matrice.
                  </p>
                  {sseRecover.isPending && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>{sseRecover.message || 'Recupero in corso…'}</span>
                        <span>{sseRecover.progress}%</span>
                      </div>
                      <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full bg-warning rounded-full transition-all duration-300"
                          style={{ width: `${sseRecover.progress}%` }}
                        />
                      </div>
                    </div>
                  )}
                  <Button
                    onClick={handleRecover}
                    disabled={sseRecover.isPending || !reportFile}
                    className="w-full h-9 text-xs brand-gradient text-white"
                  >
                    <RotateCcw className={`w-3.5 h-3.5 mr-2 ${sseRecover.isPending ? 'animate-spin' : ''}`} />
                    {sseRecover.isPending ? 'Recupero in corso…' : `Recupera ${incompleteCount} clausole`}
                  </Button>
                </CardContent>
              </Card>
            )}

            {/* JSON Preview collassabile */}
            <Collapsible open={jsonOpen} onOpenChange={setJsonOpen}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" className="w-full justify-between text-sm text-muted-foreground">
                  📋 Anteprima JSON
                  <ChevronDown className={`w-4 h-4 transition-transform ${jsonOpen ? 'rotate-180' : ''}`} />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="relative mt-2 p-4 rounded-lg bg-background/80 border max-h-[300px] overflow-auto">
                  <Button variant="ghost" size="icon" className="absolute top-2 right-2 h-7 w-7"
                    onClick={() => {
                      navigator.clipboard.writeText(JSON.stringify({
                        azienda: companyName, norma: selectedNorm,
                        clausole: clauses.reduce((a, c) => ({ ...a, [c.id]: c.text }), {}),
                      }, null, 2));
                      toast.success('JSON copiato negli appunti');
                    }}>
                    <Copy className="w-3.5 h-3.5" />
                  </Button>
                  <pre className="text-xs font-mono text-muted-foreground leading-relaxed">
                    {JSON.stringify({ azienda: companyName, norma: selectedNorm, clausole_count: clauses.length }, null, 2)}
                  </pre>
                </div>
              </CollapsibleContent>
            </Collapsible>

            {/* Download + procedi */}
            <div className="flex gap-3">
              <Button onClick={handleDownloadJson} className="flex-1 h-11 brand-gradient text-white">
                <Download className="w-4 h-4 mr-2" /> Scarica JSON
              </Button>
              <Link to="/workflow/compile" className="flex-1">
                <Button variant="outline" className="w-full h-11">
                  Compila Checklist <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </Link>
            </div>

            <Button variant="ghost" size="sm" className="w-full text-xs text-muted-foreground"
              onClick={() => { setPhase('input'); setReportFile(null); setJsonResult(null); setClauses([]); sse.reset(); }}>
              ↩ Elabora un altro report
            </Button>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  );
}
