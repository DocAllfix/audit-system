// @ts-nocheck
/**
 * useSSEProcess
 *
 * Hook per inviare una richiesta POST e ricevere progresso reale via SSE
 * (Server-Sent Events) in streaming.
 *
 * Il server risponde con una StreamingResponse dove ogni riga è:
 *   data: {"pct": 42, "msg": "Elaborazione batch 3/6..."}
 *   data: {"done": true, ...risultato...}
 *   data: {"error": "messaggio errore"}
 *
 * Usage:
 *   const { start, progress, message, result, error, isPending } = useSSEProcess();
 *   await start('/api/report/process', formData);
 */

import { useState, useCallback, useRef, useEffect } from 'react';

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

// Soglia di silenzio (sec) oltre la quale il pipeline e' considerato "stallato"
// e mostriamo un indicatore di attivita' indeterminata in UI.
const STALL_THRESHOLD_SEC = 5;

function getToken() {
  return localStorage.getItem('audit-os-token');
}

function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 60) return `~${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `~${m}m ${s}s`;
}

export function useSSEProcess() {
  const [isPending, setIsPending] = useState(false);
  const [progress, setProgress]   = useState(0);
  const [message, setMessage]     = useState('');
  const [result, setResult]       = useState(null);
  const [error, setError]         = useState(null);
  // Fix 10 — UX: ETA stimato e indicatore "stalled" (silenzio prolungato)
  const [eta, setEta]             = useState(null);
  const [isStalled, setIsStalled] = useState(false);

  const abortRef = useRef(null);
  const startTimeRef = useRef(null);
  const lastEventTimeRef = useRef(null);
  const stallTimerRef = useRef(null);

  const reset = useCallback(() => {
    setIsPending(false);
    setProgress(0);
    setMessage('');
    setResult(null);
    setError(null);
    setEta(null);
    setIsStalled(false);
    startTimeRef.current = null;
    lastEventTimeRef.current = null;
    if (stallTimerRef.current) {
      clearInterval(stallTimerRef.current);
      stallTimerRef.current = null;
    }
  }, []);

  /**
   * start(path, formData, { onProgress?, onDone?, onError? })
   * Invia POST e consuma lo stream SSE.
   * Ritorna la Promise che si risolve con il risultato finale.
   */
  const start = useCallback(async (path, body, { onProgress, onDone, onError } = {}) => {
    // Annulla eventuale richiesta precedente
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    reset();
    setIsPending(true);
    startTimeRef.current = Date.now();
    lastEventTimeRef.current = Date.now();

    // Avvia il watchdog locale per segnalare "stallo" se nessun evento per N sec
    stallTimerRef.current = setInterval(() => {
      const last = lastEventTimeRef.current;
      if (!last) return;
      const silentSec = (Date.now() - last) / 1000;
      setIsStalled(silentSec > STALL_THRESHOLD_SEC);
    }, 1000);

    try {
      const token = getToken();
      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(`${BASE_URL}${path}`, {
        method: 'POST',
        headers,
        body,
        signal: controller.signal,
      });

      if (response.status === 401) {
        localStorage.removeItem('audit-os-token');
        window.location.href = '/login';
        return;
      }

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || data?.message || `Errore ${response.status}`);
      }

      // Legge lo stream SSE riga per riga
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // ultima riga potenzialmente incompleta

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event;
          try { event = JSON.parse(raw); } catch { continue; }

          if (event.error) {
            const err = new Error(event.error);
            setError(err);
            setIsPending(false);
            if (onError) onError(err);
            return;
          }

          // FIX 14b: il backend V2 emette il done finale come
          // {type: "done_with_payload", done: true, ...}. Anche se
          // event.done venisse a mancare per qualche motivo, riconosciamo
          // l'evento dal type per evitare il reset a 0% della progress bar.
          const isDoneEvent = event.done === true
            || event.type === "done_with_payload";
          if (isDoneEvent) {
            setResult(event);
            setProgress(100);
            setMessage('Completato!');
            setIsPending(false);
            setEta(null);
            setIsStalled(false);
            if (onDone) onDone(event);
            return event;
          }

          // Evento di progresso. FIX 14b: progress MONOTONO non discendente.
          // Se l'evento non porta un pct numerico valido, NON resettiamo a 0
          // ma lasciamo il valore corrente (impedisce salti backward).
          const rawPct = event.pct;
          const pct = (typeof rawPct === 'number' && rawPct >= 0)
            ? Math.max(rawPct, 0)
            : null;
          const msg = event.msg || event.message || '';

          // Aggiorna timestamp alive (anche eventi senza pct contano come "vivo")
          const now = Date.now();
          lastEventTimeRef.current = now;
          setIsStalled(false);

          if (pct !== null) {
            // Solo salti monotonicamente crescenti per UX coerente
            setProgress(prev => Math.max(prev, pct));
            // ETA basato su pct effettivo, solo se progress > 5%
            if (pct > 5 && startTimeRef.current) {
              const elapsedSec = (now - startTimeRef.current) / 1000;
              const rate = pct / elapsedSec;
              const remainingPct = Math.max(0, 100 - pct);
              const remainingSec = rate > 0 ? remainingPct / rate : null;
              // Smoothing: media con ETA precedente per evitare oscillazioni
              setEta(prev => {
                if (prev === null || remainingSec === null) return remainingSec;
                return 0.7 * prev + 0.3 * remainingSec;
              });
            }
          }
          if (msg) setMessage(msg);

          if (onProgress) onProgress(pct ?? 0, msg);
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') return; // cancellato intenzionalmente
      setError(err);
      setIsPending(false);
      if (onError) onError(err);
      throw err;
    } finally {
      if (stallTimerRef.current) {
        clearInterval(stallTimerRef.current);
        stallTimerRef.current = null;
      }
    }
  }, [reset]);

  const abort = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setIsPending(false);
    if (stallTimerRef.current) {
      clearInterval(stallTimerRef.current);
      stallTimerRef.current = null;
    }
  }, []);

  // Cleanup su unmount
  useEffect(() => {
    return () => {
      if (stallTimerRef.current) clearInterval(stallTimerRef.current);
    };
  }, []);

  return {
    start, abort, reset,
    isPending, progress, message, result, error,
    eta, etaText: formatEta(eta), isStalled,
  };
}
