// @ts-nocheck
import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api, downloadBase64File } from '@/api/apiClient';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useWorkflowStore } from '@/store/workflowStore';
import { SUPPORTED_NORMS } from '@/lib/constants';
import { Upload, FileText, CheckCircle2, AlertTriangle, Download, ClipboardCheck, FileSpreadsheet } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import FileDropzone from '@/components/shared/FileDropzone';
import PipelineStages from '@/components/shared/PipelineStages';
import confetti from 'canvas-confetti';
import { toast } from 'sonner';
import { toastError } from '@/lib/toastError';

const stages = [
  { id: 'parse',  label: 'ANALIZZA', description: 'Parsing JSON clausole' },
  { id: 'fill',   label: 'COMPILA',  description: 'Compilazione template' },
  { id: 'export', label: 'ESPORTA',  description: 'Generazione documento' },
];

const normOptions = SUPPORTED_NORMS.map(n => ({
  value: n.id,
  label: `${n.id} — ${n.label}`,
  isExcel: n.isExcel,
}));

export default function CompilaChecklist() {
  const [jsonFile, setJsonFile] = useState(null);
  const [jsonData, setJsonData] = useState(null);
  const [selectedNorm, setSelectedNorm] = useState('');
  const [phase, setPhase] = useState('input');   // 'input' | 'processing' | 'results'
  const [currentStage, setCurrentStage] = useState(0);
  const [result, setResult] = useState(null);
  const [autoLoaded, setAutoLoaded] = useState(false);
  const queryClient = useQueryClient();
  const { setTab3Status, session } = useWorkflowStore();

  // Auto-load JSON dalla Tab 2 se disponibile
  useEffect(() => {
    const stored = session?.tab2?.jsonData;
    if (stored && !jsonData) {
      setJsonData(stored);
      if (stored.norma) setSelectedNorm(stored.norma);
      setAutoLoaded(true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleJsonSelect = async (file) => {
    setJsonFile(file);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      setJsonData(parsed);
      // Pre-seleziona la norma rilevata dal JSON
      if (parsed.norma) setSelectedNorm(parsed.norma);
    } catch {
      toast.error('File JSON non valido');
      setJsonFile(null);
    }
  };

  const effectiveNorm = selectedNorm || jsonData?.norma || '';
  const isExcel = effectiveNorm?.includes('27001');
  const templateName = effectiveNorm
    ? `Template${effectiveNorm.replace(/\s/g, '')}.${isExcel ? 'xlsx' : 'docx'}`
    : '';

  const compileMutation = useMutation({
    mutationFn: async () => {
      setPhase('processing');
      setCurrentStage(0);

      // Anima fasi mentre il server compila
      const timer = setInterval(() => {
        setCurrentStage(prev => Math.min(prev + 1, stages.length - 1));
      }, 800);

      try {
        const data = await api.checklist.compile({ ...jsonData, norma: effectiveNorm });
        clearInterval(timer);
        setCurrentStage(stages.length - 1);
        return data;
      } catch (e) {
        clearInterval(timer);
        throw e;
      }
    },
    onSuccess: (data) => {
      // Calcola statistiche dal JSON locale per la UI
      const totalClauses  = jsonData?.clausole ? Object.keys(jsonData.clausole).length : 0;
      const compiledCount = jsonData?.clausole
        ? Object.values(jsonData.clausole).filter(v => v && v.trim().length > 0).length
        : 0;
      const placeholders = totalClauses - compiledCount;

      setResult({ ...data, compiledCount, placeholders, totalClauses });
      setPhase('results');
      setTab3Status('completed', { filename: data.filename });
      queryClient.invalidateQueries({ queryKey: ['all-practices'] });
      confetti({ particleCount: 50, spread: 60, origin: { y: 0.6 }, colors: ['#14b8a6', '#22c55e'] });
    },
    onError: (err) => {
      setPhase('input');
      setTab3Status('error');
      toastError(err.message || 'Errore durante la compilazione');
    },
  });

  const handleDownload = () => {
    if (!result) return;
    downloadBase64File(result.file_base64, result.filename, result.mime_type);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Compila Checklist</h1>
        <p className="text-sm text-muted-foreground mt-1">Genera il documento Word/Excel compilato dal JSON checklist</p>
      </div>

      <AnimatePresence mode="wait">

        {/* ── INPUT ─────────────────────────────────────────────────────── */}
        {phase === 'input' && (
          <motion.div key="input" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">
            <Card className="glass">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Upload className="w-4 h-4 text-primary" /> Carica JSON Checklist
                </CardTitle>
              </CardHeader>
              <CardContent>
                <FileDropzone
                  accept=".json"
                  title="Trascina il file JSON checklist"
                  description="Generato dalla tab Produci Checklist"
                  icon={FileText}
                  file={jsonFile}
                  onFileSelect={handleJsonSelect}
                  onRemove={() => { setJsonFile(null); setJsonData(null); }}
                />
              </CardContent>
            </Card>

            {jsonData && (
              <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
                {autoLoaded && (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/10 border border-primary/20 text-xs text-primary">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    JSON caricato automaticamente dalla Tab 2 — puoi procedere direttamente
                  </div>
                )}
                <Card className="glass border-success/20">
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-success" />
                      <span className="text-sm font-semibold">JSON Rilevato</span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
                      <div><p className="text-muted-foreground">Azienda</p><p className="font-semibold">{jsonData.azienda || '—'}</p></div>
                      <div>
                        <p className="text-muted-foreground">Clausole</p>
                        <p className="font-semibold">{jsonData.clausole ? Object.keys(jsonData.clausole).length : 0}</p>
                      </div>
                      <div><p className="text-muted-foreground">Template</p><p className="font-semibold font-mono text-xs">{templateName || '—'}</p></div>
                    </div>
                    {isExcel && (
                      <div className="flex items-center gap-2 p-2 rounded-md bg-warning/10 border border-warning/20">
                        <FileSpreadsheet className="w-4 h-4 text-warning" />
                        <span className="text-xs text-warning">ISO 27001 usa un template Excel (.xlsx)</span>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Norma — rilevata automaticamente, con possibilità di override */}
                <Card className="glass">
                  <CardContent className="p-4 space-y-2">
                    <div className="flex items-center gap-2 mb-2">
                      <ClipboardCheck className="w-4 h-4 text-primary" />
                      <span className="text-sm font-semibold">Norma di Riferimento</span>
                      {selectedNorm === jsonData.norma && (
                        <Badge variant="outline" className="bg-success/10 text-success border-success/30 text-[10px] ml-auto">auto-rilevata</Badge>
                      )}
                      {selectedNorm !== jsonData.norma && (
                        <Badge variant="outline" className="bg-warning/10 text-warning border-warning/30 text-[10px] ml-auto">modificata</Badge>
                      )}
                    </div>
                    <Select value={selectedNorm} onValueChange={setSelectedNorm}>
                      <SelectTrigger className="h-9 text-sm">
                        <SelectValue placeholder="Seleziona norma..." />
                      </SelectTrigger>
                      <SelectContent>
                        {normOptions.map(n => (
                          <SelectItem key={n.value} value={n.value}>
                            <span className="font-mono font-semibold text-primary mr-2">{n.value}</span>
                            {n.isExcel && <Badge className="text-[10px] bg-warning/10 text-warning border-warning/30 ml-1">XLSX</Badge>}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            <Button
              onClick={() => compileMutation.mutate()}
              disabled={!jsonData || !effectiveNorm || compileMutation.isPending}
              className="w-full h-12 brand-gradient text-white font-semibold text-sm hover:brightness-110 disabled:opacity-40"
            >
              <ClipboardCheck className="w-4 h-4 mr-2" /> Genera Checklist Compilata
            </Button>
          </motion.div>
        )}

        {/* ── PROCESSING ────────────────────────────────────────────────── */}
        {phase === 'processing' && (
          <motion.div key="processing" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            <Card className="glass">
              <CardContent className="p-6">
                <PipelineStages stages={stages} currentStage={currentStage} />
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* ── RESULTS ───────────────────────────────────────────────────── */}
        {phase === 'results' && result && (
          <motion.div key="results" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <Card className="glass">
                <CardContent className="p-4 text-center">
                  <CheckCircle2 className="w-5 h-5 text-success mx-auto mb-1" />
                  <p className="text-2xl font-bold">{result.compiledCount}</p>
                  <p className="text-xs text-muted-foreground">Requisiti compilati</p>
                </CardContent>
              </Card>
              <Card className="glass">
                <CardContent className="p-4 text-center">
                  <AlertTriangle className="w-5 h-5 text-warning mx-auto mb-1" />
                  <p className="text-2xl font-bold">{result.placeholders}</p>
                  <p className="text-xs text-muted-foreground">Non sostituiti</p>
                </CardContent>
              </Card>
              <Card className="glass">
                <CardContent className="p-4 text-center">
                  <FileText className="w-5 h-5 text-primary mx-auto mb-1" />
                  <p className="text-2xl font-bold">{result.totalClauses}</p>
                  <p className="text-xs text-muted-foreground">Clausole totali</p>
                </CardContent>
              </Card>
            </div>

            {result.placeholders > 0 && (
              <Card className="glass border-warning/20 bg-warning/5">
                <CardContent className="p-4">
                  <p className="text-sm font-semibold flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-warning" />
                    {result.placeholders} placeholder non sostituiti
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Questi campi nel template non hanno trovato un valore corrispondente nel JSON.
                  </p>
                </CardContent>
              </Card>
            )}

            <Card className="glass border-success/20">
              <CardContent className="p-5">
                <div className="flex items-center gap-3 mb-4">
                  <CheckCircle2 className="w-5 h-5 text-success" />
                  <div>
                    <p className="font-semibold text-sm">Checklist compilata con successo!</p>
                    <p className="text-xs text-muted-foreground font-mono">{result.filename}</p>
                  </div>
                </div>
                <Button onClick={handleDownload} className="w-full h-11 brand-gradient text-white">
                  <Download className="w-4 h-4 mr-2" />
                  Scarica Checklist {isExcel ? 'Excel' : 'Word'}
                </Button>
              </CardContent>
            </Card>

            <Button
              variant="ghost" size="sm"
              className="w-full text-xs text-muted-foreground"
              onClick={() => { setPhase('input'); setJsonFile(null); setJsonData(null); setResult(null); }}
            >
              ↩ Compila un altro JSON
            </Button>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  );
}
