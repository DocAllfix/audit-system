import { useLocation } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function PageNotFound() {
  const location = useLocation();
  const pageName = location.pathname.substring(1);

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div className="text-center space-y-6 max-w-md">
        <div className="p-4 rounded-2xl bg-muted/50 mx-auto w-fit">
          <Compass className="w-12 h-12 text-muted-foreground/50" />
        </div>
        <div>
          <h1 className="text-6xl font-bold text-muted-foreground/30">404</h1>
          <h2 className="text-xl font-semibold mt-2">Pagina non trovata</h2>
          <p className="text-sm text-muted-foreground mt-2">
            La pagina <span className="font-mono text-foreground">"{pageName}"</span> non esiste.
          </p>
        </div>
        <Button onClick={() => window.location.href = '/'} className="brand-gradient text-white">
          Torna alla Dashboard
        </Button>
      </div>
    </div>
  );
}