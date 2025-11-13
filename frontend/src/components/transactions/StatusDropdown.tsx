import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { api, getStatusColor, getStatusLabel } from '@/services/api';
import type { Transaction, TransactionStatus } from '@/types/transaction.types';

interface StatusDropdownProps {
  transaction: Transaction;
  onUpdate?: () => void;
}

const STATUS_OPTIONS: TransactionStatus[] = [
  'NOT_PROCESSED',
  'PROCESSING',
  'PARTIALLY_FULFILLED',
  'FULFILLED',
  'CANCELLED',
];

export function StatusDropdown({ transaction, onUpdate }: StatusDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleStatusChange = async (newStatus: TransactionStatus) => {
    if (newStatus === transaction.status) {
      setIsOpen(false);
      return;
    }

    setIsLoading(true);

    try {
      await api.patch(`/transactions/${transaction.id}/`, { status: newStatus });
      setIsOpen(false);
      toast.success(`Status updated to ${getStatusLabel(newStatus)}`, {
        description: `Transaction ${transaction.tx_id}`
      });
      onUpdate?.();
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || 'Failed to update status';
      toast.error('Failed to update status', {
        description: errorMsg
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent row click from opening modal
    if (!transaction.is_locked && !isLoading) {
      setIsOpen(!isOpen);
    }
  };

  const handleOptionClick = (e: React.MouseEvent, status: TransactionStatus) => {
    e.stopPropagation();
    handleStatusChange(status);
  };

  const handleBlur = () => {
    // Delay to allow click events to fire first
    setTimeout(() => {
      if (!isLoading) {
        setIsOpen(false);
      }
    }, 200);
  };

  if (transaction.is_locked) {
    return (
      <div
        className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-white text-sm font-medium cursor-not-allowed opacity-75"
        style={{ backgroundColor: getStatusColor(transaction.status) }}
        title="Locked - cannot change"
      >
        {getStatusLabel(transaction.status)}
      </div>
    );
  }

  return (
    <div className="relative inline-block" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={handleToggle}
        onBlur={handleBlur}
        disabled={isLoading}
        className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-white text-sm font-medium transition-all hover:opacity-90 hover:shadow-md ${
          isLoading ? 'opacity-50 cursor-wait' : 'cursor-pointer'
        }`}
        style={{ backgroundColor: getStatusColor(transaction.status) }}
        title="Click to change status"
      >
        {getStatusLabel(transaction.status)}
        <ChevronDown className={`h-3 w-3 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute z-50 mt-1 min-w-[180px] bg-white dark:bg-slate-800 rounded-md shadow-lg border border-gray-200 dark:border-slate-600 overflow-hidden">
          {STATUS_OPTIONS.map((status) => {
            const isSelected = status === transaction.status;
            const color = getStatusColor(status);

            return (
              <button
                key={status}
                type="button"
                onClick={(e) => handleOptionClick(e, status)}
                disabled={isLoading}
                className={`w-full text-left px-3 py-2 text-sm transition-colors flex items-center gap-2 ${
                  isSelected
                    ? 'bg-gray-100 dark:bg-slate-700 font-medium'
                    : 'hover:bg-gray-50 dark:hover:bg-slate-700'
                } ${isLoading ? 'opacity-50 cursor-wait' : 'cursor-pointer'}`}
              >
                <span
                  className="inline-block w-3 h-3 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className={isSelected ? 'font-semibold' : ''}>
                  {getStatusLabel(status)}
                </span>
                {isSelected && (
                  <span className="ml-auto text-xs text-gray-500 dark:text-gray-400">✓</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
