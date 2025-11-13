import { useState } from 'react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Select } from '@/components/ui/select';
import { api, getStatusColor, getStatusLabel } from '@/services/api';
import type { Transaction, TransactionStatus } from '@/types/transaction.types';

interface EditableStatusCellProps {
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

export function EditableStatusCell({ transaction, onUpdate }: EditableStatusCellProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStatusChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newStatus = e.target.value as TransactionStatus;

    if (newStatus === transaction.status) {
      setIsEditing(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await api.patch(`/transactions/${transaction.id}/`, { status: newStatus });
      setIsEditing(false);
      toast.success(`Status updated to ${getStatusLabel(newStatus)}`, {
        description: `Transaction ${transaction.tx_id}`
      });
      onUpdate?.();
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || 'Failed to update status';
      setError(errorMsg);
      toast.error('Failed to update status', {
        description: errorMsg
      });
      // Keep editing mode open on error
    } finally {
      setIsLoading(false);
    }
  };

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent row click from opening modal
    if (!transaction.is_locked && !isEditing) {
      setIsEditing(true);
    }
  };

  const handleBlur = () => {
    if (!isLoading) {
      setIsEditing(false);
      setError(null);
    }
  };

  if (isEditing) {
    return (
      <div className="space-y-1" onClick={(e) => e.stopPropagation()}>
        <Select
          value={transaction.status}
          onChange={handleStatusChange}
          onBlur={handleBlur}
          disabled={isLoading}
          autoFocus
          className="w-full min-w-[150px]"
        >
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {getStatusLabel(status)}
            </option>
          ))}
        </Select>
        {error && (
          <p className="text-xs text-red-500 dark:text-red-400">{error}</p>
        )}
      </div>
    );
  }

  return (
    <div
      onClick={handleClick}
      className={`inline-block ${
        !transaction.is_locked
          ? 'cursor-pointer hover:opacity-80 hover:ring-2 hover:ring-blue-500/50 rounded'
          : 'cursor-not-allowed opacity-75'
      }`}
      title={transaction.is_locked ? 'Locked - cannot change' : 'Click to edit status'}
    >
      <Badge
        style={{ backgroundColor: getStatusColor(transaction.status) }}
        className="text-white"
      >
        {getStatusLabel(transaction.status)}
      </Badge>
    </div>
  );
}
