// @ts-nocheck
import { create } from 'zustand';

const INITIAL_SESSION = {
  practiceId: null,
  companyName: null,
  startedAt: null,
  tab1: { status: 'idle', reportFileUrl: null, reportFilename: null },
  tab2: { status: 'idle', norm: null, clauses: [], jsonData: null },
  tab3: { status: 'idle', filename: null },
};

const loadSession = () => {
  try {
    const raw = localStorage.getItem('audit-os-workflow');
    return raw ? JSON.parse(raw) : { ...INITIAL_SESSION };
  } catch {
    return { ...INITIAL_SESSION };
  }
};

const loadNotifications = () => {
  try {
    const raw = localStorage.getItem('audit-os-notifications');
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
};

const saveSession = (session) => {
  try { localStorage.setItem('audit-os-workflow', JSON.stringify(session)); } catch {}
};

const saveNotifications = (notifications) => {
  try { localStorage.setItem('audit-os-notifications', JSON.stringify(notifications.slice(0, 50))); } catch {}
};

export const useWorkflowStore = create((set, get) => ({
  session: loadSession(),

  // ── Notifiche ─────────────────────────────────────────────────────────────
  notifications: loadNotifications(),
  unreadCount: loadNotifications().filter(n => !n.read).length,

  addNotification: ({ type, title, body }) => set(s => {
    const notif = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2),
      type,   // 'success' | 'error' | 'warning' | 'info'
      title,
      body: body || '',
      time: new Date().toISOString(),
      read: false,
    };
    const notifications = [notif, ...s.notifications].slice(0, 50);
    saveNotifications(notifications);
    return { notifications, unreadCount: notifications.filter(n => !n.read).length };
  }),

  markAllRead: () => set(s => {
    const notifications = s.notifications.map(n => ({ ...n, read: true }));
    saveNotifications(notifications);
    return { notifications, unreadCount: 0 };
  }),

  clearNotifications: () => {
    saveNotifications([]);
    set({ notifications: [], unreadCount: 0 });
  },

  // ── Sessione workflow ──────────────────────────────────────────────────────
  setTab1Status: (status, extra = {}) =>
    set(s => {
      const session = { ...s.session, tab1: { ...s.session.tab1, status, ...extra } };
      saveSession(session);
      return { session };
    }),

  setTab2Status: (status, extra = {}) =>
    set(s => {
      const session = { ...s.session, tab2: { ...s.session.tab2, status, ...extra } };
      saveSession(session);
      return { session };
    }),

  setTab3Status: (status, extra = {}) =>
    set(s => {
      const session = { ...s.session, tab3: { ...s.session.tab3, status, ...extra } };
      saveSession(session);
      return { session };
    }),

  setTab2Json: (jsonData) =>
    set(s => {
      const session = { ...s.session, tab2: { ...s.session.tab2, jsonData } };
      saveSession(session);
      return { session };
    }),

  setCompanyName: (companyName) =>
    set(s => {
      const session = { ...s.session, companyName };
      saveSession(session);
      return { session };
    }),

  startSession: (extra = {}) => {
    const session = {
      ...INITIAL_SESSION,
      practiceId: Date.now().toString(36),
      startedAt: new Date().toISOString(),
      ...extra,
    };
    saveSession(session);
    set({ session });
  },

  resetSession: () => {
    const session = { ...INITIAL_SESSION };
    saveSession(session);
    set({ session });
  },

  hasActiveSession: () => {
    const { session } = get();
    return !!(
      session.practiceId &&
      (
        session.tab1.status === 'completed' ||
        session.tab2.status === 'completed' ||
        session.tab3.status === 'completed' ||
        session.tab1.status === 'processing' ||
        session.tab2.status === 'processing' ||
        session.tab3.status === 'processing'
      )
    );
  },
}));
