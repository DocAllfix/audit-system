import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { HelpCircle, Clock, AlertCircle, FileText, ListChecks, Wifi, Zap, FolderOpen, ClipboardCheck } from 'lucide-react';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const faqs = [
  { q: 'Quanto tempo richiede l\'elaborazione?', a: 'L\'elaborazione dipende dal numero di documenti. In media: 30-90 secondi per uno ZIP di 20-50 file. ZIP più grandi possono richiedere fino a 3-5 minuti.' },
  { q: 'Perché alcune clausole sono vuote?', a: 'L\'AI potrebbe non trovare evidenza nel report per alcune clausole. Usa la funzione "Recupera Clausole Mancanti" oppure compila manualmente dal drawer di dettaglio.' },
  { q: 'Come correggo il nome azienda?', a: 'Nella tab "Produci Checklist", clicca sull\'icona di modifica accanto al nome azienda rilevato. La modifica si propaga al JSON e al filename.' },
  { q: 'Posso elaborare più pratiche insieme?', a: 'Attualmente il sistema elabora una pratica alla volta. Puoi avviare una nuova elaborazione non appena la precedente è completata.' },
  { q: 'Cosa fare se l\'API non risponde?', a: 'Verifica la connessione internet. Il sistema ha un recovery automatico con retry fino a 3 tentativi. Se il problema persiste, contatta il supporto.' },
  { q: 'Quali formati di documento sono supportati?', a: 'PDF, DOCX, DOC, XLSX, XLS, immagini (JPG, PNG, TIFF), email (.eml, .msg). I file vengono elaborati con OCR se necessario.' },
];

const problemButtons = [
  { icon: Clock, label: 'Lentezza', solution: 'Verifica il numero di file nello ZIP. Riduci a meno di 80 documenti per performance ottimali. Lo ZIP viene elaborato in batch paralleli.' },
  { icon: AlertCircle, label: 'Errore', solution: 'Controlla il log errori nell\'admin panel. Gli errori API vengono recuperati automaticamente. Se persiste, prova con un file più piccolo.' },
  { icon: FolderOpen, label: 'File non carica', solution: 'Assicurati che il file sia in formato ZIP valido e non superi i 500 MB. Verifica che lo ZIP non sia protetto da password.' },
  { icon: ClipboardCheck, label: 'Risultato incompleto', solution: 'Usa il recovery automatico nella tab 2. Se alcune clausole restano vuote, potrebbe mancare la documentazione nel report originale.' },
];

export default function Supporto() {
  const [activeProblem, setActiveProblem] = useState(null);

  return (
    <div className="space-y-8 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <HelpCircle className="w-6 h-6 text-primary" /> FAQ & Assistenza
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Risposte rapide e diagnostica guidata</p>
      </div>

      {/* FAQ */}
      <Card className="glass">
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Domande Frequenti</CardTitle>
        </CardHeader>
        <CardContent>
          <Accordion type="single" collapsible className="space-y-1">
            {faqs.map((faq, i) => (
              <AccordionItem key={i} value={`faq-${i}`} className="border-b border-border/50">
                <AccordionTrigger className="text-sm font-medium hover:no-underline py-3">
                  {faq.q}
                </AccordionTrigger>
                <AccordionContent className="text-sm text-muted-foreground leading-relaxed pb-3">
                  {faq.a}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </CardContent>
      </Card>

      {/* Diagnostics */}
      <Card className="glass">
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Diagnostica Guidata</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">Seleziona il problema:</p>
          <div className="flex flex-wrap gap-2">
            {problemButtons.map((pb) => {
              const Icon = pb.icon;
              return (
                <Button
                  key={pb.label}
                  variant={activeProblem === pb.label ? 'default' : 'outline'}
                  size="sm"
                  className={`text-xs gap-1.5 ${activeProblem === pb.label ? 'brand-gradient text-white' : ''}`}
                  onClick={() => setActiveProblem(activeProblem === pb.label ? null : pb.label)}
                >
                  <Icon className="w-3.5 h-3.5" /> {pb.label}
                </Button>
              );
            })}
          </div>
          {activeProblem && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="p-4 rounded-lg bg-muted/30 border">
              <p className="text-sm leading-relaxed">
                {problemButtons.find(pb => pb.label === activeProblem)?.solution}
              </p>
            </motion.div>
          )}
        </CardContent>
      </Card>

      {/* Contact */}
      <div className="text-center py-4">
        <p className="text-xs text-muted-foreground">📧 Supporto tecnico: <span className="font-mono text-foreground">admin@audit-os.it</span></p>
      </div>
    </div>
  );
}