import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { CaretDown } from '@phosphor-icons/react';
import { toast } from 'sonner';
import { api, getStatusLabel } from '@/services/api';
import type { Transaction, TransactionStatus } from '@/types/transaction.types';
import { cn } from '@/lib/utils';

interface StatusDropdownProps {
  transaction: Transaction;
  onUpdate?: () => void;
}

const STATUS_OPTIONS: TransactionStatus[] = ['NOT_PROCESSED', 'PROCESSING'];

const STATUS_DOTS: Record<string, string> = {
  NOT_PROCESSED: 'bg-gray-400 dark:bg-gray-500',
  PROCESSING: 'bg-blue-400 dark:bg-blue-400',
  PARTIALLY_FULFILLED: 'bg-amber-400 dark:bg-amber-400',
  FULFILLED: 'bg-emerald-400 dark:bg-emerald-400',
  COMBINED_FULFILLED: 'bg-violet-400 dark:bg-violet-400',
  CANCELLED: 'bg-red-400 dark:bg-red-400',
};

const MENU_WIDTH = 210;
const MENU_ESTIMATED_HEIGHT = 130;

export function StatusDropdown({ transaction, onUpdate }: StatusDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const dot = STATUS_DOTS[transaction.status] || STATUS_DOTS.NOT_PROCESSED;

  // Position the menu in viewport coordinates. The menu renders through a
  // portal to <body> because the table rows apply scale transforms on press,
  // which would otherwise stack later rows above the menu.
  const openMenu = () => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const openUpward = spaceBelow < MENU_ESTIMATED_HEIGHT + 16 && rect.top > spaceBelow;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - MENU_WIDTH - 8));
    setPosition(
      openUpward
        ? { left, bottom: window.innerHeight - rect.top + 6 }
        : { left, top: rect.bottom + 6 }
    );
    setIsOpen(true);
  };

  useEffect(() => {
    if (!isOpen) return;
    const close = () => setIsOpen(false);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    // Close on scroll/resize so the menu never drifts away from its anchor.
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const handleStatusChange = async (newStatus: TransactionStatus) => {
    if (newStatus === transaction.status) { setIsOpen(false); return; }
    setIsLoading(true);
    try {
      await api.patch(`/transactions/${transaction.id}/`, { status: newStatus });
      setIsOpen(false);
      toast.success(`Status updated to ${getStatusLabel(newStatus)}`, { description: `Transaction ${transaction.tx_id}` });
      onUpdate?.();
    } catch (err) {
      const detail = typeof err === 'object' && err !== null && 'response' in err
        ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
        : undefined;
      toast.error('Failed to update status', { description: detail || 'Unknown error' });
    } finally { setIsLoading(false); }
  };

  if (transaction.is_locked) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[13px] font-medium opacity-60 cursor-not-allowed">
        <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot)} />
        {getStatusLabel(transaction.status)}
      </div>
    );
  }

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (isLoading) return;
          if (isOpen) { setIsOpen(false); } else { openMenu(); }
        }}
        disabled={isLoading}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1 text-[13px] font-medium transition-all active:scale-95 rounded-lg hover:bg-[rgb(var(--color-muted))]/60',
          isLoading && 'opacity-50'
        )}
      >
        <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot)} />
        {getStatusLabel(transaction.status)}
        <CaretDown className={cn('h-3 w-3 transition-transform opacity-40', isOpen && 'rotate-180')} />
      </button>

      {isOpen && position && createPortal(
        <>
          {/* Full-screen shield: every tap outside the menu lands here and
              closes it instead of falling through to the rows below. */}
          <div
            className="fixed inset-0 z-[90]"
            onClick={() => !isLoading && setIsOpen(false)}
          />

          <div
            role="menu"
            className={cn(
              'fixed z-[91] min-w-[210px] bg-[rgb(var(--color-card))] border border-[rgb(var(--color-border))] shadow-lg overflow-hidden animate-fade-in',
            )}
            style={{
              left: position.left,
              ...(position.top !== undefined ? { top: position.top } : { bottom: position.bottom }),
            }}
          >
            {STATUS_OPTIONS.map((status) => {
              const isSelected = status === transaction.status;
              const d = STATUS_DOTS[status];
              return (
                <button
                  key={status}
                  type="button"
                  role="menuitem"
                  onClick={(e) => { e.stopPropagation(); handleStatusChange(status); }}
                  disabled={isLoading}
                  className={cn(
                    'w-full text-left px-4 py-3 text-[15px] transition-colors flex items-center gap-3 min-h-[48px]',
                    isSelected ? 'bg-[rgb(var(--color-muted))]' : 'hover:bg-[rgb(var(--color-muted))]/50 active:bg-[rgb(var(--color-muted))]'
                  )}
                >
                  <span className={cn('w-2 h-2 rounded-full shrink-0', d)} />
                  <span className={isSelected ? 'font-semibold' : ''}>
                    {getStatusLabel(status)}
                  </span>
                  {isSelected && <span className="ml-auto text-xs text-[rgb(var(--color-muted-foreground))]">✓</span>}
                </button>
              );
            })}
          </div>
        </>,
        document.body
      )}
    </div>
  );
}
