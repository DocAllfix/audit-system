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

import { useState, useCallback, useRef } from 'react';

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

function getToken() {
  return localStorage.getItem('audit-os-token');
}

export function useSSEProcess() {
  const [isPending, setIsPending] = useState(false);
  const [progress, setProgress]   = useState(0);
  const [message, setMessage]     = useState('');
  const [result, setResult]       = useState(null);
  const [error, setError]         = useState(null);
  const abortRef = useRef(null);

  const reset = useCallback(() => {
    setIsPending(false);
    setProgress(0);
    setMessage('');
    setResult(null);
    setError(null);
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

          if (event.done) {
            setResult(event);
            setProgress(100);
            setMessage('Completato!');
            setIsPending(false);
            if (onDone) onDone(event);
            return event;
          }

          // Evento di progresso
          const pct = event.pct !== undefined ? event.pct : 0;
          const msg = event.msg || event.message || '';
          setProgress(pct);
          setMessage(msg);
          if (onProgress) onProgress(pct, msg);
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') return; // cancellato intenzionalmente
      setError(err);
      setIsPending(false);
      if (onError) onError(err);
      throw err;
    }
  }, [reset]);

  const abort = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setIsPending(false);
  }, []);

  return { start, abort, reset, isPending, progress, message, result, error };
}
