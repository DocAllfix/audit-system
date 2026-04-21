import React from 'react';
import { useLocation } from 'react-router-dom';
import { Bell, Sun, Moon, ChevronRight, LogOut, Trash2, CheckCircle2, AlertTriangle, Info, XCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { useTheme } from '@/lib/ThemeContext';
import { useWorkflowStore } from '@/store/workflowStore';
import { ScrollArea } from '@/components/ui/scroll-area';

const breadcrumbMap = {
  '/dashboard': 'Dashboard',
  '/workflow/report':   'Genera Report',
  '/workflow/produce':  'Produci Checklist',
  '/workflow/compile':  'Compila Checklist',
  '/pratiche': 'Storico Pratiche',
  '/admin': 'Pannello Admin',
  '/admin/errori': 'Log Errori',
  '/supporto': 'FAQ & Assistenza',
};

const notifIcon = {
  success: <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0 mt-0.5" />,
  error:   <XCircle     className="w-3.5 h-3.5 text-destructive shrink-0 mt-0.5" />,
  warning: <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0 mt-0.5" />,
  info:    <Info        className="w-3.5 h-3.5 text-primary shrink-0 mt-0.5" />,
};

function formatTime(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = Math.floor((now - d) / 1000);
    if (diff < 60)  return 'adesso';
    if (diff < 3600) return `${Math.floor(diff / 60)} min fa`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} h fa`;
    return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' });
  } catch { return ''; }
}

export default function Topbar({ user, onLogout, errorCount = 0 }) {
  const location = useLocation();
  const currentPage = breadcrumbMap[location.pathname] || 'Pagina';
  const initials = user?.full_name ? user.full_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2) : 'U';
  const { theme, toggle } = useTheme();
  const { notifications, unreadCount, markAllRead, clearNotifications } = useWorkflowStore();

  return (
    <header className="h-16 sticky top-0 z-50 bg-card/95 backdrop-blur-xl border-b border-border flex items-center justify-between px-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">AUDIT-OS</span>
        <ChevronRight className="w-3 h-3 text-muted-foreground/50" />
        <span className="font-medium text-foreground">{currentPage}</span>
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        {/* Theme toggle */}
        <Button variant="ghost" size="icon" onClick={toggle} className="text-muted-foreground hover:text-foreground" title={theme === 'dark' ? 'Passa a tema chiaro' : 'Passa a tema scuro'}>
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </Button>

        {/* Notifications — tutti gli utenti */}
        <DropdownMenu onOpenChange={(open) => { if (open && unreadCount > 0) markAllRead(); }}>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="relative text-muted-foreground hover:text-foreground">
              <Bell className="w-4 h-4" />
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-destructive text-[10px] font-bold text-white flex items-center justify-center">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-80 p-0">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b">
              <span className="text-xs font-semibold">Notifiche</span>
              <div className="flex items-center gap-1">
                {notifications.length > 0 && (
                  <Button variant="ghost" size="icon" className="h-6 w-6" title="Cancella tutto"
                    onClick={(e) => { e.stopPropagation(); clearNotifications(); }}>
                    <Trash2 className="w-3 h-3" />
                  </Button>
                )}
              </div>
            </div>
            {/* Lista notifiche */}
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs text-muted-foreground">
                Nessuna notifica
              </div>
            ) : (
              <ScrollArea className="max-h-80">
                {notifications.map((n) => (
                  <div key={n.id} className={`flex items-start gap-2.5 px-3 py-2.5 border-b last:border-0 ${!n.read ? 'bg-primary/5' : ''}`}>
                    {notifIcon[n.type] || notifIcon.info}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold leading-snug truncate">{n.title}</p>
                      {n.body && <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug line-clamp-2">{n.body}</p>}
                    </div>
                    <span className="text-[10px] text-muted-foreground shrink-0 mt-0.5">{formatTime(n.time)}</span>
                  </div>
                ))}
              </ScrollArea>
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* User menu */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="gap-2 px-2">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-primary/20 text-primary text-xs font-semibold">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <span className="text-sm font-medium hidden sm:inline">{user?.full_name || 'Utente'}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <div className="px-3 py-2">
              <p className="text-sm font-medium">{user?.full_name}</p>
              <p className="text-xs text-muted-foreground">{user?.email}</p>
              <Badge variant="outline" className="mt-1 text-[10px]">
                {user?.role || 'user'}
              </Badge>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onLogout} className="text-destructive focus:text-destructive">
              <LogOut className="w-4 h-4 mr-2" />
              Esci
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}