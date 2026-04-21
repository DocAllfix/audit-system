import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, FileText, ListChecks, ClipboardCheck,
  History, Shield, AlertTriangle, HelpCircle, ChevronLeft, ChevronRight
} from 'lucide-react';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

const navSections = [
  {
    label: 'Principale',
    items: [
      { path: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    ]
  },
  {
    label: 'Workflow',
    items: [
      { path: '/workflow/report',   icon: FileText,       label: 'Genera Report' },
      { path: '/workflow/produce',  icon: ListChecks,     label: 'Produci Checklist' },
      { path: '/workflow/compile',  icon: ClipboardCheck, label: 'Compila Checklist' },
    ]
  },
  {
    label: 'Pratiche',
    items: [
      { path: '/pratiche', icon: History, label: 'Storico Pratiche' },
    ]
  },
  {
    label: 'Admin',
    adminOnly: true,
    items: [
      { path: '/admin',        icon: Shield,        label: 'Pannello Admin' },
      { path: '/admin/errori', icon: AlertTriangle,  label: 'Log Errori', badgeKey: 'errors' },
    ]
  },
  {
    label: 'Supporto',
    items: [
      { path: '/supporto', icon: HelpCircle, label: 'FAQ & Assistenza' },
    ]
  }
];

export default function Sidebar({ collapsed, setCollapsed, userRole, errorCount = 0 }) {
  const location = useLocation();
  const isAdmin = userRole === 'admin';

  return (
    <TooltipProvider delayDuration={0}>
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 64 : 240 }}
        transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="relative h-full bg-sidebar border-r border-sidebar-border flex flex-col"
      >
        {/* Logo */}
        <div className="h-16 flex items-center px-4 gap-3 shrink-0">
          <div className="w-8 h-8 rounded-lg brand-gradient flex items-center justify-center shrink-0">
            <span className="text-white font-bold text-sm">A</span>
          </div>
          <AnimatePresence>
            {!collapsed && (
              <motion.span
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="font-mono font-bold text-primary whitespace-nowrap"
              >
                AUDIT-OS
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <Separator className="bg-sidebar-border" />

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
          {navSections.map((section) => {
            if (section.adminOnly && !isAdmin) return null;
            return (
              <div key={section.label}>
                <AnimatePresence>
                  {!collapsed && (
                    <motion.p
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60 px-3 mb-1"
                    >
                      {section.label}
                    </motion.p>
                  )}
                </AnimatePresence>
                <div className="space-y-0.5">
                  {section.items.map((item) => {
                    const isActive = item.matchPrefix
                      ? location.pathname.startsWith(item.matchPrefix)
                      : location.pathname === item.path;
                    const Icon = item.icon;
                    const hasBadge = item.badgeKey === 'errors' && errorCount > 0;

                    const navItem = (
                      <Link
                        key={item.path}
                        to={item.path}
                        className={`
                          relative flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-all duration-150
                          ${isActive
                            ? 'bg-primary/8 text-primary border-l-2 border-primary'
                            : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground border-l-2 border-transparent'
                          }
                        `}
                      >
                        <span className="relative shrink-0">
                          <Icon className="w-5 h-5" />
                          {hasBadge && (
                            <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-destructive" />
                          )}
                        </span>
                        <AnimatePresence>
                          {!collapsed && (
                            <motion.span
                              initial={{ opacity: 0 }}
                              animate={{ opacity: 1 }}
                              exit={{ opacity: 0 }}
                              className="whitespace-nowrap flex-1"
                            >
                              {item.label}
                            </motion.span>
                          )}
                        </AnimatePresence>
                        {hasBadge && !collapsed && (
                          <span className="ml-auto text-[10px] font-bold text-destructive shrink-0">
                            {errorCount}
                          </span>
                        )}
                      </Link>
                    );

                    if (collapsed) {
                      return (
                        <Tooltip key={item.path}>
                          <TooltipTrigger asChild>{navItem}</TooltipTrigger>
                          <TooltipContent side="right" className="font-inter">
                            {item.label}
                          </TooltipContent>
                        </Tooltip>
                      );
                    }
                    return navItem;
                  })}
                </div>
              </div>
            );
          })}
        </nav>


      </motion.aside>
    </TooltipProvider>
  );
}