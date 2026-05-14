// @ts-nocheck
import React, { useState, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { downloadBase64File } from '@/api/apiClient';
import { useQueryClient } from '@tanstack/react-query';
import { useWorkflowStore } from '@/store/workflowStore';
import { useSSEProcess } from '@/hooks/useSSEProcess';
import {
  FileArchive, Rocket, Download, ArrowRight, CheckCircle2,
  AlertTriangle, BarChart3, FolderOpen, Loader2, Files, Building2,
  ChevronDown, ChevronUp,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import FileDropzone from '@/components/shared/FileDropzone';
import PipelineStages from '@/components/shared/PipelineStages';
import confetti from 'canvas-confetti';
import { toast } from 'sonner';
import { toastError } from '@/lib/toastError';
import JSZip from 'jszip';

const pipelineStages = [
  { id: 'classify', label: 'CLASSIFICA', description: 'Categorizza i file' },
  { id: 'extract',  label: 'ESTRAI',     description: 'Estrai il testo' },
  { id: 'analyze',  label: 'ANALIZZA',   description: 'Analisi AI documenti' },
];

/**
 * Determina la stage attiva leggendo il testo del messaggio dal server.
 * Più affidabile delle soglie numeriche perché rispecchia esattamente
 * cosa sta facendo il backend in quel momento.
 */
function resolveStage(pct, message) {
  const msg = (message || '').toLowerCase();
  if (
    msg.includes('analisi') || msg.includes('batch') ||
    msg.includes('generat') || msg.includes('word') ||
    msg.includes('structured') || msg.includes('evidenz') ||
    msg.includes('completat') || pct >= 68
  ) return 2;
  if (
    msg.includes('estraz') || msg.includes('ocr') ||
    msg.includes('testo') || msg.includes('caricam') ||
    msg.includes('pdf') || pct >= 8
  ) return 1;
  return 0;
}

/** Conta i file dentro un ZIP leggendo solo i metadati (senza decomprimere). */
async function peekZipContents(file) {
  try {
    const zip = await JSZip.loadAsync(file);
    const entries = Object.values(zip.files);
    const fileEntries = entries.filter(f => !f.dir);
    // Raggruppa per estensione
    const byExt = {};
    for (const f of fileEntries) {
      const ext = f.name.split('.').pop()?.toLowerCase() || '?';
      byExt[ext] = (byExt[ext] || 0) + 1;
    }
    return { count: fileEntries.length, byExt };
  } catch {
    return null;
  }
}

/** Converte una stringa base64 in un File object. */
function base64ToFile(base64, filename, mimeType) {
  const byteChars = atob(base64);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
  return new File([bytes], filename, { type: mimeType });
}

const WORD_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export default function GeneraReport() {
  const [file, setFile]                   = useState(null);
  const [zipInfo, setZipInfo]             = useState(null);  // { count, byExt }
  const [zipPeeking, setZipPeeking]       = useState(false);
  const [phase, setPhase]                 = useState('input');
  const [result, setResult]               = useState(null);
  const [folderZipping, setFolderZipping] = useState(false);
  const [zipProgress, setZipProgress]     = useState(0);
  const [companyName, setCompanyName]     = useState('');
  const [editingName, setEditingName]     = useState(false);
  const [nameConfirmed, setNameConfirmed] = useState(false);
  const [showUnprocessed, setShowUnprocessed] = useState(false);

  const queryClient  = useQueryClient();
  const { startSession, setTab1Status, setCompanyName: storeSetCompanyName, addNotification } = useWorkflowStore();
  const navigate     = useNavigate();
  const folderInputRef = useRef(null);
  const sse = useSSEProcess();

  const currentStage = resolveStage(sse.progress, sse.message);

  /* ── Selezione file ZIP ─────────────────────────────────────────────────── */
  const handleZipSelect = async (selectedFile) => {
    setFile(selectedFile);
    setZipInfo(null);
    setZipPeeking(true);
    const info = await peekZipContents(selectedFile);
    setZipInfo(info);
    setZipPeeking(false);
  };

  /* ── Selezione cartella → compressione client-side ──────────────────────── */
  const handleFolderSelect = async (e) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    setFolderZipping(true);
    setZipProgress(0);
    try {
      const zip = new JSZip();
      const files = Array.from(fileList).filter(f => !f.name.startsWith('.') && f.name !== 'Thumbs.db');
      for (let i = 0; i < files.length; i++) {
        setZipProgress(Math.round((i / files.length) * 80));
        const path = files[i].webkitRelativePath || files[i].name;
        zip.file(path, await files[i].arrayBuffer());
      }
      setZipProgress(90);
      const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
      setZipProgress(100);
      const folderName = files[0]?.webkitRelativePath?.split('/')[0] || 'cartella';
      const zipFile = new File([blob], `${folderName}.zip`, { type: 'application/zip' });
      await handleZipSelect(zipFile);
      toast.success(`Cartella compressa: ${zipFile.name} (${(zipFile.size / 1024 / 1024).toFixed(1)} MB)`);
    } catch (err) {
      toastError('Errore compressione cartella: ' + err.message);
    } finally {
      setFolderZipping(false);
      setZipProgress(0);
      if (folderInputRef.current) folderInputRef.current.value = '';
    }
  };

  /* ── Avvia elaborazione ─────────────────────────────────────────────────── */
  const handleProcess = async () => {
    if (!file) return;
    setPhase('processing');
    setTab1Status('processing');
    startSession({ filename: file.name });

    const form = new FormData();
    form.append('file', file);

    await sse.start('/api/v2/report/process?legacy_events=true', form, {
      onDone: (data) => {
        setResult(data);
        const detectedName = data.company_name || '';
        setCompanyName(detectedName);
        setNameConfirmed(false);
        setEditingName(false);
        setPhase('results');
        setTab1Status('completed', { filename: data.filename, companyName: detectedName });
        addNotification({ type: 'success', title: 'Report generato', body: `${detectedName ? detectedName + ' — ' : ''}${data.filename}` });
        queryClient.invalidateQueries({ queryKey: ['all-practices'] });
        queryClient.invalidateQueries({ queryKey: ['practices'] });
        confetti({ particleCount: 80, spread: 70, origin: { y: 0.6 }, colors: ['#14b8a6', '#22c55e'] });
        // FIX 14c: auto-download del docx appena la run e' completata, cosi'
        // l'utente NON deve cercare il bottone "Scarica" — il file scende
        // direttamente. Il bottone resta comunque per ri-scaricare in seguito.
        try {
          if (data.word_base64 && data.filename) {
            downloadBase64File(data.word_base64, data.filename, WORD_MIME);
          }
        } catch (e) {
          console.warn('Auto-download fallito:', e);
        }
      },
      onError: (err) => {
        setPhase('input');
        setTab1Status('error');
        addNotification({ type: 'error', title: 'Errore Tab 1', body: err.message });
        toastError(err.message || 'Errore durante l\'elaborazione');
      },
    });
  };

  /* ── Download Word ──────────────────────────────────────────────────────── */
  const handleDownload = () => {
    if (!result) return;
    downloadBase64File(result.word_base64, result.filename, WORD_MIME);
  };

  const handleConfirmName = () => {
    storeSetCompanyName(companyName);
    setNameConfirmed(true);
    setEditingName(false);
  };

  /* ── Vai a Tab 2 passando il report già prodotto ────────────────────────── */
  const handleGoToProduce = () => {
    if (!result?.word_base64) {
      navigate('/workflow/produce');
      return;
    }
    const reportFile = base64ToFile(result.word_base64, result.filename, WORD_MIME);
    navigate('/workflow/produce', { state: { reportFile, companyName } });
  };

  const stats = result?.stats || {};
  const logSummary = stats.log_summary || {};
  const isNarrative = stats.output_mode === 'narrative';

  /* ── Render ─────────────────────────────────────────────────────────────── */
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Genera Report</h1>
        <p className="text-sm text-muted-foreground mt-1">Carica uno ZIP con i documenti e genera il Report Word delle evidenze</p>
      </div>

      <AnimatePresence mode="wait">

        {/* ── INPUT ─────────────────────────────────────────────────────── */}
        {phase === 'input' && (
          <motion.div key="input" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">
            <Card className="glass">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <FileArchive className="w-4 h-4 text-primary" /> Carica Documenti
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <FileDropzone
                  accept=".zip"
                  title="Trascina il file ZIP oppure clicca per sfogliare"
                  description="Formati supportati: PDF, DOCX, DOC, XLSX, immagini · Limite 1 GB"
                  icon={FileArchive}
                  file={file}
                  onFileSelect={handleZipSelect}
                  onRemove={() => { setFile(null); setZipInfo(null); }}
                />

                {/* Info ZIP: dimensione + numero file */}
                {file && (
                  <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                    className="flex items-center gap-3 px-1 flex-wrap">
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                      <span className="font-mono">{file.name}</span>
                    </div>
                    <Badge variant="outline" className="text-[10px]">
                      {(file.size / 1024 / 1024).toFixed(1)} MB
                    </Badge>
                    {zipPeeking && (
                      <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                        <Loader2 className="w-3 h-3 animate-spin" /> Analisi contenuto…
                      </span>
                    )}
                    {zipInfo && (
                      <Badge variant="outline" className="text-[10px] gap-1">
                        <Files className="w-3 h-3" />
                        {zipInfo.count} file
                        {zipInfo.byExt && Object.keys(zipInfo.byExt).length > 0 && (
                          <span className="text-muted-foreground ml-1">
                            ({Object.entries(zipInfo.byExt)
                              .sort((a, b) => b[1] - a[1])
                              .slice(0, 3)
                              .map(([ext, n]) => `${n} ${ext.toUpperCase()}`)
                              .join(', ')})
                          </span>
                        )}
                      </Badge>
                    )}
                  </motion.div>
                )}

                {/* Pulsante cartella */}
                {!file && (
                  <>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 h-px bg-border" />
                      <span className="text-xs text-muted-foreground">oppure</span>
                      <div className="flex-1 h-px bg-border" />
                    </div>
                    <div>
                      <input ref={folderInputRef} type="file" webkitdirectory="" directory="" multiple className="hidden" onChange={handleFolderSelect} />
                      <Button variant="outline" className="w-full h-11 text-sm gap-2" disabled={folderZipping} onClick={() => folderInputRef.current?.click()}>
                        {folderZipping
                          ? <><Loader2 className="w-4 h-4 animate-spin" />Compressione… {zipProgress}%</>
                          : <><FolderOpen className="w-4 h-4 text-primary" />Seleziona Cartella (compressa automaticamente)</>}
                      </Button>
                      <p className="text-[10px] text-muted-foreground text-center mt-1">
                        La cartella viene convertita in ZIP nel browser prima dell'invio
                      </p>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            <Button
              onClick={handleProcess}
              disabled={!file || sse.isPending || folderZipping || zipPeeking}
              className="w-full h-12 brand-gradient text-white font-semibold text-sm hover:brightness-110 disabled:opacity-40"
            >
              <Rocket className="w-4 h-4 mr-2" /> Avvia Elaborazione
            </Button>
          </motion.div>
        )}

        {/* ── PROCESSING ────────────────────────────────────────────────── */}
        {phase === 'processing' && (
          <motion.div key="processing" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">
            <Card className="glass">
              <CardContent className="p-6">
                <PipelineStages
                  stages={pipelineStages}
                  currentStage={currentStage}
                  progress={sse.progress}
                  message={sse.message}
                />
                {/* Fix 10 — ETA + alive indicator */}
                <div className="mt-4 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block w-2 h-2 rounded-full ${
                        sse.isStalled ? 'bg-amber-400 animate-pulse' : 'bg-green-500 animate-pulse'
                      }`}
                      aria-label={sse.isStalled ? 'in attesa' : 'attivo'}
                    />
                    <span className="text-muted-foreground">
                      {sse.isStalled
                        ? 'Sistema attivo, in attesa di risposta dal modello…'
                        : 'In elaborazione live'}
                    </span>
                  </div>
                  {sse.etaText && (
                    <div className="text-muted-foreground">
                      Tempo stimato rimanente: <span className="font-medium text-foreground">{sse.etaText}</span>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
            <Card className="glass border-primary/20 bg-primary/5">
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground text-center">
                  ⏳ Elaborazione in corso — può richiedere alcuni minuti in base alla dimensione del file.
                  <br />Non chiudere questa scheda.
                </p>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* ── RESULTS ───────────────────────────────────────────────────── */}
        {phase === 'results' && result && (
          <motion.div key="results" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="space-y-4">

            {/* ── Stats modalità narrativa ─────────────────────────── */}
            {isNarrative && (
              <>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { label: 'Documenti analizzati', value: stats.documents_with_text ?? 0 },
                    { label: 'Paragrafi generati',   value: stats.n_paragraphs ?? 0 },
                    {
                      label: 'Legge 1 doc → 1 §',
                      value: stats.documents_with_text > 0
                        ? (stats.n_paragraphs >= stats.documents_with_text ? '✓ OK' : `⚠ ${stats.n_paragraphs}/${stats.documents_with_text}`)
                        : '—',
                    },
                  ].map(s => (
                    <Card key={s.label} className="glass">
                      <CardContent className="p-3 text-center">
                        <p className={`text-2xl font-bold ${s.label === 'Legge 1 doc → 1 §' && String(s.value).startsWith('⚠') ? 'text-amber-500' : ''}`}>{s.value}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
                <Card className="glass">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs font-semibold flex items-center gap-2">
                      <BarChart3 className="w-3.5 h-3.5 text-primary" /> Riepilogo Run Narrativa
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-3">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      {[
                        { label: 'File nello ZIP', value: stats.total_files_in_zip ?? 0 },
                        { label: 'Con testo',      value: stats.documents_with_text ?? 0 },
                        { label: 'Batch fallback', value: stats.n_fallback_batches ?? 0 },
                      ].map(s => (
                        <div key={s.label} className="text-center">
                          <p className={`text-lg font-bold ${s.label === 'Batch fallback' && s.value > 0 ? 'text-amber-500' : ''}`}>{s.value}</p>
                          <p className="text-xs text-muted-foreground">{s.label}</p>
                        </div>
                      ))}
                      {/* Non elaborati — cliccabile se > 0 */}
                      {(() => {
                        const n = stats.n_unprocessed_files ?? 0;
                        const list = stats.unprocessed_files ?? [];
                        return (
                          <div className="text-center">
                            {n > 0 ? (
                              <button
                                onClick={() => setShowUnprocessed(v => !v)}
                                className="w-full flex flex-col items-center gap-0.5 group"
                              >
                                <span className="text-lg font-bold text-amber-500 flex items-center gap-1">
                                  {n}
                                  {showUnprocessed ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                                </span>
                                <span className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
                                  Non elaborati
                                </span>
                              </button>
                            ) : (
                              <div>
                                <p className="text-lg font-bold">0</p>
                                <p className="text-xs text-muted-foreground">Non elaborati</p>
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                    {/* Lista file non elaborati espandibile */}
                    {showUnprocessed && (stats.unprocessed_files ?? []).length > 0 && (
                      <div className="rounded-md border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 p-3 space-y-1.5">
                        <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          File non elaborati — verificali nella tua cartella
                        </p>
                        <ul className="space-y-1">
                          {(stats.unprocessed_files ?? []).map((f, i) => {
                            const filename = typeof f === 'string' ? f : (f.filename ?? f);
                            const reason   = typeof f === 'object' ? (f.reason ?? '') : '';
                            const phase    = typeof f === 'object' ? (f.phase ?? '') : '';
                            return (
                              <li key={i} className="flex items-start gap-2 text-xs">
                                <span className="mt-0.5 shrink-0 w-1.5 h-1.5 rounded-full bg-amber-400" />
                                <span>
                                  <span className="font-mono font-medium text-foreground">{filename}</span>
                                  {reason && (
                                    <span className="text-muted-foreground ml-1.5">— {reason}</span>
                                  )}
                                </span>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}

            {/* ── Stats modalità strutturata (vecchio path) ────────────── */}
            {!isNarrative && (stats.paragraphs_generated || stats.total_paragraphs) && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: 'Paragrafi',         value: stats.paragraphs_generated ?? stats.total_paragraphs ?? 0 },
                  { label: 'Media parole',       value: Math.round(stats.avg_words ?? 0) },
                  { label: 'Verbi unici',        value: stats.unique_verbs ?? 0 },
                  { label: 'Violazioni privacy', value: stats.privacy_violations ?? 0 },
                ].map(s => (
                  <Card key={s.label} className="glass">
                    <CardContent className="p-3 text-center">
                      <p className="text-2xl font-bold">{s.value}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {!isNarrative && logSummary.files_in_zip && (
              <Card className="glass">
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-semibold flex items-center gap-2">
                    <BarChart3 className="w-3.5 h-3.5 text-primary" /> Diagnostica Copertura
                  </CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-3 gap-3 pt-0">
                  {[
                    { label: 'File ZIP',       value: logSummary.files_in_zip ?? 0 },
                    { label: 'Testo estratto', value: logSummary.text_extracted_ok ?? 0 },
                    { label: 'Copertura',      value: `${logSummary.text_extracted_ok > 0 ? Math.round(((stats.paragraphs_generated ?? 0) / logSummary.text_extracted_ok) * 100) : 0}%` },
                  ].map(s => (
                    <div key={s.label} className="text-center">
                      <p className="text-lg font-bold">{s.value}</p>
                      <p className="text-xs text-muted-foreground">{s.label}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {logSummary.batches_failed > 0 && (
              <Card className="glass border-destructive/20 bg-destructive/5">
                <CardContent className="p-4 flex items-start gap-3">
                  <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                  <p className="text-xs text-destructive">
                    {logSummary.batches_failed} batch non elaborati — segnalati nel report con "ELABORAZIONE FALLITA".
                  </p>
                </CardContent>
              </Card>
            )}

            {/* ── Conferma nome azienda ─────────────────────────────── */}
            <Card className={`glass ${nameConfirmed ? 'border-success/30 bg-success/5' : 'border-primary/30 bg-primary/5'}`}>
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center gap-2">
                  <Building2 className="w-4 h-4 text-primary shrink-0" />
                  <span className="text-xs font-semibold">Nome Azienda Rilevato</span>
                  {nameConfirmed && (
                    <Badge variant="outline" className="bg-success/10 text-success border-success/30 text-[10px] ml-auto">✓ confermato</Badge>
                  )}
                </div>
                {editingName ? (
                  <div className="flex items-center gap-2">
                    <Input
                      value={companyName}
                      onChange={e => setCompanyName(e.target.value)}
                      className="h-8 text-sm flex-1"
                      autoFocus
                      onKeyDown={e => e.key === 'Enter' && handleConfirmName()}
                    />
                    <Button size="sm" className="h-8 text-xs brand-gradient text-white shrink-0" onClick={handleConfirmName}>
                      Conferma ✓
                    </Button>
                    <Button size="sm" variant="ghost" className="h-8 text-xs shrink-0" onClick={() => setEditingName(false)}>
                      ✕
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm flex-1">{companyName || '—'}</span>
                    {!nameConfirmed ? (
                      <>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground" onClick={() => setEditingName(true)}>
                          ✏️ Modifica
                        </Button>
                        <Button size="sm" className="h-7 text-xs brand-gradient text-white" onClick={handleConfirmName}>
                          Conferma ✓
                        </Button>
                      </>
                    ) : (
                      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground" onClick={() => { setEditingName(true); setNameConfirmed(false); }}>
                        ✏️
                      </Button>
                    )}
                  </div>
                )}
                <p className="text-[10px] text-muted-foreground">Il nome verrà usato nelle tab successive.</p>
              </CardContent>
            </Card>

            <Card className="glass border-success/20">
              <CardContent className="p-5 space-y-3">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
                  <div>
                    <p className="font-semibold text-sm">Report generato con successo!</p>
                    <p className="text-xs text-muted-foreground font-mono mt-0.5">{result.filename}</p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <Button onClick={handleDownload} className="flex-1 h-11 brand-gradient text-white">
                    <Download className="w-4 h-4 mr-2" /> Scarica Report Word
                  </Button>
                  <Button variant="outline" className="flex-1 h-11" onClick={handleGoToProduce}>
                    Produci Checklist <ArrowRight className="w-4 h-4 ml-2" />
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Button variant="ghost" size="sm" className="w-full text-xs text-muted-foreground"
              onClick={() => { setPhase('input'); setFile(null); setZipInfo(null); setResult(null); setCompanyName(''); setNameConfirmed(false); sse.reset(); }}>
              ↩ Elabora un altro file
            </Button>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  );
}
