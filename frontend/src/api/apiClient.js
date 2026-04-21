// @ts-nocheck
// ==============================================================================
// AUDIT-OS API CLIENT
// Fetch-based client per il backend Python (FastAPI).
// Base URL configurabile via VITE_API_BASE_URL (default: http://localhost:8000)
// ==============================================================================

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

function getToken() {
  return localStorage.getItem('audit-os-token');
}

async function request(method, path, body = undefined, extraHeaders = {}) {
  const token = getToken();
  const headers = { ...extraHeaders };

  if (!(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    localStorage.removeItem('audit-os-token');
    window.location.href = '/login';
    return;
  }

  if (res.status === 204) return null;

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    throw new Error(data?.detail || data?.message || `Errore ${res.status}`);
  }

  return data;
}

// ==============================================================================
// UTILITY: scarica un file ricevuto come base64 dall'API
// ==============================================================================
export function downloadBase64File(base64String, filename, mimeType) {
  const byteCharacters = atob(base64String);
  const byteNumbers = new Array(byteCharacters.length);
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i);
  }
  const blob = new Blob([new Uint8Array(byteNumbers)], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ==============================================================================
// AUTH
// ==============================================================================
const auth = {
  /** POST /api/auth/login → { token, user: { username, email, role, display_name } } */
  login: (username, password) =>
    request('POST', '/api/auth/login', { username, password }),

  /** GET /api/auth/me → { username, email, role, display_name } */
  me: () => request('GET', '/api/auth/me'),

  /** POST /api/auth/logout */
  logout: () => request('POST', '/api/auth/logout'),
};

// ==============================================================================
// PRATICHE
// ==============================================================================
const pratiche = {
  /**
   * GET /api/pratiche
   * Params: limit, sort
   * → [{ id, type, company_name, norm, status, processing_time_seconds,
   *       filename, file_size, created_date, created_by }]
   */
  list: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
    ).toString();
    return request('GET', `/api/pratiche${qs ? `?${qs}` : ''}`);
  },

  /** POST /api/pratiche → { ok: true } */
  create: (data) => request('POST', '/api/pratiche', data),
};

// ==============================================================================
// ADMIN — ERROR LOG
// ==============================================================================
const errors = {
  /**
   * GET /api/admin/errors
   * → [{ id, error_type, message, stack_trace, company_name, tab,
   *       auto_recovered, resolved, resolved_by, created_date, created_by }]
   */
  list: () => request('GET', '/api/admin/errors'),

  /**
   * GET /api/admin/errors?resolved=false
   * Per il badge count nella sidebar (solo non risolti).
   * Admin: restituisce array. Auditor: restituisce { count: N }.
   */
  listUnresolved: () => request('GET', '/api/admin/errors?resolved=false'),

  /** PATCH /api/admin/errors/{id} → { ok: true } */
  resolve: (id, resolvedBy) =>
    request('PATCH', `/api/admin/errors/${id}`, {
      resolved_by: resolvedBy,
    }),
};

// ==============================================================================
// ADMIN — STATISTICHE
// ==============================================================================
const admin = {
  /** GET /api/admin/stats → { total_practices, avg_time_seconds, success_rate, today_count } */
  stats: () => request('GET', '/api/admin/stats'),
};

// ==============================================================================
// WORKFLOW — TAB 1: GENERA REPORT
// ==============================================================================
const report = {
  /**
   * POST /api/report/process (multipart)
   * Body: FormData { file: ZIP }
   *
   * Response (sincrona, può richiedere minuti):
   * {
   *   filename: string,
   *   word_base64: string,   // file .docx in base64
   *   stats: { ... },
   *   company_name: string
   * }
   */
  process: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('POST', '/api/report/process', form);
  },
};

// ==============================================================================
// WORKFLOW — TAB 2 & 3: CHECKLIST
// ==============================================================================
const checklist = {
  /**
   * POST /api/checklist/produce (multipart)
   * Body: FormData { file: DOCX/PDF, norm: string, company_name?: string }
   *
   * Response (sincrona, può richiedere minuti):
   * {
   *   json: { norma, azienda, data_elaborazione, clausole: { ... } },
   *   filename: string
   * }
   */
  produce: (file, norm, companyName) => {
    const form = new FormData();
    form.append('file', file);
    form.append('norm', norm);
    if (companyName) form.append('company_name', companyName);
    return request('POST', '/api/checklist/produce', form);
  },

  /**
   * POST /api/checklist/compile
   * Body: { norma, azienda, clausole: { id: testo } }
   *
   * Response (sincrona, rapida):
   * {
   *   filename: string,
   *   file_base64: string,   // file .docx o .xlsx in base64
   *   mime_type: string,
   *   norm: string
   * }
   */
  compile: (jsonData) => request('POST', '/api/checklist/compile', jsonData),

  /**
   * POST /api/checklist/recover (multipart)
   * Body: FormData { file: DOCX/PDF, json_data: string, incomplete_keys: string, norm: string }
   *
   * Response:
   * {
   *   json: { norma, azienda, clausole: { ... } },
   *   still_missing: ["4.1", ...]
   * }
   */
  recover: (reportFile, currentJson, incompleteKeys, norm) => {
    const form = new FormData();
    form.append('file', reportFile);
    form.append('json_data', JSON.stringify(currentJson));
    form.append('incomplete_keys', JSON.stringify(incompleteKeys));
    form.append('norm', norm);
    return request('POST', '/api/checklist/recover', form);
  },
};

export const api = { auth, pratiche, errors, admin, report, checklist };
