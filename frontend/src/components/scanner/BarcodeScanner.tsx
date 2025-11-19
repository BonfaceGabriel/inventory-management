import { useState, useRef, useEffect } from 'react';
import { Scan, Keyboard, X, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { parseBarcode, sanitizeBarcodeInput, formatBarcodeDisplay, isValidBarcode } from '@/utils/barcodeParser';
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

  // Auto-focus on mount and after scan
  useEffect(() => {
    if (autoFocus && !disabled) {
      inputRef.current?.focus();
    }
  }, [autoFocus, disabled, scanning]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value);
    setError(null); // Clear error on input
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!inputValue.trim() || scanning || disabled) {
      return;
    }

    try {
      setScanning(true);
      setError(null);

      // Sanitize and parse barcode
      const sanitized = sanitizeBarcodeInput(inputValue);
      const parsed = parseBarcode(sanitized);

      // Validate
      if (!isValidBarcode(parsed)) {
        throw new Error('Invalid barcode format');
      }

      // Call onScan handler
      await onScan(parsed);

      // Clear input on success
      setInputValue('');

      // Re-focus for next scan
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to process barcode');
    } finally {
      setScanning(false);
    }
  };

  const handleClear = () => {
    setInputValue('');
    setError(null);
    inputRef.current?.focus();
  };

  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex items-center gap-2">
            <Scan className="h-5 w-5 text-blue-600 flex-shrink-0" />
            <div className="flex-1">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Barcode Scanner</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Scan product barcode or type manually
              </p>
            </div>
          </div>

          <div className="relative">
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
              <Keyboard className="h-4 w-4" />
            </div>
            <Input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={handleInputChange}
              placeholder={placeholder}
              disabled={disabled || scanning}
              className={`pl-10 pr-20 ${error ? 'border-red-500' : ''}`}
              autoComplete="off"
              spellCheck={false}
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
              {inputValue && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleClear}
                  className="h-7 w-7 p-0"
                  disabled={scanning}
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
              <Button
                type="submit"
                size="sm"
                disabled={!inputValue.trim() || disabled || scanning}
                className="h-7 px-2"
              >
                {scanning ? (
                  <span className="animate-spin">⏳</span>
                ) : (
                  <Check className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>

          {error && (
            <div className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
              <X className="h-4 w-4" />
              {error}
            </div>
          )}

          <div className="text-xs text-gray-500 dark:text-gray-400">
            <div className="font-medium mb-1">Supported formats:</div>
            <ul className="list-disc list-inside space-y-0.5">
              <li>Simple SKU: <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">AP004E</code></li>
              <li>With quantity: <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">AP004E*2</code> or <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">AP004Ex2</code></li>
            </ul>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
