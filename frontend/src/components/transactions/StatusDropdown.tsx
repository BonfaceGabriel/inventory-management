import { useState, useRef, useEffect } from 'react';
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

export function StatusDropdown({ transaction, onUpdate }: StatusDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const dot = STATUS_DOTS[transaction.status] || STATUS_DOTS.NOT_PROCESSED;

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setIsOpen(false);
    };
    if (isOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleStatusChange = async (newStatus: TransactionStatus) => {
    if (newStatus === transaction.status) { setIsOpen(false); return; }
    setIsLoading(true);
    try {
      await api.patch(`/transactions/${transaction.id}/`, { status: newStatus });
      setIsOpen(false);
      toast.success(`Status updated to ${getStatusLabel(newStatus)}`, { description: `Transaction ${transaction.tx_id}` });
      onUpdate?.();
    } catch (err: any) {
      toast.error('Failed to update status', { description: err.response?.data?.error || 'Unknown error' });
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
        onClick={(e) => { e.stopPropagation(); if (!isLoading) setIsOpen(!isOpen); }}
        disabled={isLoading}
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1 text-[13px] font-medium transition-all active:scale-95',
          isLoading && 'opacity-50'
        )}
      >
        <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot)} />
        {getStatusLabel(transaction.status)}
        <CaretDown className={cn('h-3 w-3 transition-transform opacity-40', isOpen && 'rotate-180')} />
      </button>

      {isOpen && (
        <div className="absolute z-50 mt-1.5 min-w-[170px] rounded-xl bg-[rgb(var(--color-card))] border border-[rgb(var(--color-border))] shadow-lg overflow-hidden animate-fade-in">
          {STATUS_OPTIONS.map((status) => {
            const isSelected = status === transaction.status;
            const d = STATUS_DOTS[status];
            return (
              <button
                key={status}
                type="button"
                onClick={(e) => { e.stopPropagation(); handleStatusChange(status); }}
                disabled={isLoading}
                className={cn(
                  'w-full text-left px-3.5 py-2.5 text-sm transition-colors flex items-center gap-2.5',
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
      )}
    </div>
  );
}
