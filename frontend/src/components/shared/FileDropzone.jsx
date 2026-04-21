import React, { useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { Upload, Folder, X, FileArchive, File } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function FileDropzone({ accept, title, description, icon: IconProp, onFileSelect, file, onRemove }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);
  const Icon = IconProp || Upload;

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) onFileSelect(droppedFile);
  };

  const handleDragOver = (e) => { e.preventDefault(); setIsDragOver(true); };
  const handleDragLeave = () => setIsDragOver(false);

  const handleClick = () => inputRef.current?.click();
  const handleInputChange = (e) => {
    const f = e.target.files[0];
    if (f) onFileSelect(f);
  };

  const formatSize = (bytes) => {
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
    return (bytes / 1e3).toFixed(0) + ' KB';
  };

  if (file) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        className="rounded-lg border border-success/30 bg-success/5 p-4"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-md bg-success/10">
            <FileArchive className="w-5 h-5 text-success" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{file.name}</p>
            <p className="text-xs text-muted-foreground">{formatSize(file.size)}</p>
          </div>
          <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" onClick={onRemove}>
            <X className="w-4 h-4" />
          </Button>
        </div>
      </motion.div>
    );
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={handleClick}
      className={`
        relative rounded-lg border-2 border-dashed p-8 cursor-pointer transition-all duration-200 text-center
        ${isDragOver
          ? 'border-primary bg-primary/5 scale-[1.01]'
          : 'border-border hover:border-muted-foreground/30 hover:bg-muted/20'
        }
      `}
    >
      <input ref={inputRef} type="file" accept={accept} className="hidden" onChange={handleInputChange} />
      <div className="flex flex-col items-center gap-3">
        <div className={`p-3 rounded-xl transition-colors ${isDragOver ? 'bg-primary/10' : 'bg-muted/50'}`}>
          <Icon className={`w-7 h-7 ${isDragOver ? 'text-primary' : 'text-muted-foreground'}`} />
        </div>
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        </div>
      </div>
    </div>
  );
}