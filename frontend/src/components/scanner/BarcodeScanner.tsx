import { useState, useRef, useEffect } from 'react';
import { Scan, X, Check } from '@phosphor-icons/react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { parseBarcode, sanitizeBarcodeInput, isValidBarcode } from '@/utils/barcodeParser';
import type { ParsedBarcode } from '@/utils/barcodeParser';

interface BarcodeScannerProps {
  onScan: (barcode: ParsedBarcode) => void | Promise<void>;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}

export default function BarcodeScanner({
  onScan,
  disabled = false,
  placeholder = 'Scan or enter barcode...',
  autoFocus = true,
}: BarcodeScannerProps) {
  const [inputValue, setInputValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus && !disabled) inputRef.current?.focus();
  }, [autoFocus, disabled, scanning]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || scanning || disabled) return;
    try {
      setScanning(true);
      setError(null);
      const sanitized = sanitizeBarcodeInput(inputValue);
      const parsed = parseBarcode(sanitized);
      if (!isValidBarcode(parsed)) throw new Error('Invalid barcode format');
      await onScan(parsed);
      setInputValue('');
      setTimeout(() => inputRef.current?.focus(), 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to process barcode');
    } finally { setScanning(false); }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="relative">
        <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[rgb(var(--color-muted-foreground))]">
          <Scan className="h-5 w-5" />
        </div>
        <Input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => { setInputValue(e.target.value); setError(null); }}
          placeholder={placeholder}
          disabled={disabled || scanning}
          className={cn('pl-11 pr-20 h-12 text-base', error && 'border-[rgb(var(--color-destructive))]')}
          autoComplete="off"
          spellCheck={false}
          autoFocus={autoFocus}
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
          {inputValue && (
            <button type="button" onClick={() => { setInputValue(''); setError(null); inputRef.current?.focus(); }}
              className="touch-target-sm flex items-center justify-center rounded-lg text-[rgb(var(--color-muted-foreground))] hover:bg-[rgb(var(--color-muted))] transition-colors"
              disabled={scanning}
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <button type="submit" disabled={!inputValue.trim() || disabled || scanning}
            className="touch-target-sm flex items-center justify-center rounded-lg bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] disabled:opacity-40 transition-all active:scale-95"
          >
            {scanning ? <span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" /> : <Check className="h-4 w-4" />}
          </button>
        </div>
      </div>
      {error && (
        <p className="text-sm text-[rgb(var(--color-destructive))] flex items-center gap-1">
          <X className="h-3.5 w-3.5" /> {error}
        </p>
      )}
      <div className="text-xs text-[rgb(var(--color-muted-foreground))] flex flex-wrap gap-x-4 gap-y-1">
        <span><code className="bg-[rgb(var(--color-muted))] px-1 rounded">893663002920</code> barcode</span>
        <span><code className="bg-[rgb(var(--color-muted))] px-1 rounded">AP004E</code> SKU</span>
        <span><code className="bg-[rgb(var(--color-muted))] px-1 rounded">SKU*2</code> with qty</span>
      </div>
    </form>
  );
}
