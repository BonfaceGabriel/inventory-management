import { useState } from 'react';
import { toast } from 'sonner';
import { AlertTriangle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { getStatusLabel } from '@/services/api';
import type { Transaction, TransactionStatus } from '@/types/transaction.types';
import { api } from '@/services/api';

interface StatusChangeDialogProps {
  transaction: Transaction;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

const STATUS_OPTIONS = [
  { value: 'NOT_PROCESSED', label: 'Not Processed' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'PARTIALLY_FULFILLED', label: 'Partially Fulfilled' },
  { value: 'FULFILLED', label: 'Fulfilled' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

export function StatusChangeDialog({
  transaction,
  open,
  onOpenChange,
  onSuccess,
}: StatusChangeDialogProps) {
  const [newStatus, setNewStatus] = useState(transaction.status);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (newStatus === transaction.status) {
      onOpenChange(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await api.patch(`/transactions/${transaction.id}/`, {
        status: newStatus,
      });
      toast.success(`Status updated to ${getStatusLabel(newStatus)}`, {
        description: `Order ${transaction.tx_id} has been updated`
      });
      onSuccess();
      onOpenChange(false);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || err.response?.data?.status?.[0] || 'Failed to update status';
      setError(errorMsg);
      toast.error('Failed to update status', {
        description: errorMsg
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader onClose={() => onOpenChange(false)}>
          <DialogTitle>Change Order Status</DialogTitle>
          <DialogDescription>
            Update the status of order #{transaction.tx_id}
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="current_status">Current Status</Label>
              <div className="mt-1 p-3 bg-gray-50 dark:bg-slate-700 rounded text-gray-900 dark:text-gray-100 font-semibold">
                {getStatusLabel(transaction.status)}
              </div>
            </div>

            <div>
              <Label htmlFor="new_status">New Status</Label>
              <Select
                id="new_status"
                value={newStatus}
                onChange={(e) => setNewStatus(e.target.value as TransactionStatus)}
                disabled={isLoading}
                className="mt-1"
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>

            {error && (
              <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded">
                <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              </div>
            )}

            <div className="flex items-start gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded">
              <AlertTriangle className="h-5 w-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
              <div className="text-sm text-blue-600 dark:text-blue-400">
                <p className="font-semibold mb-1">Status Change Rules:</p>
                <ul className="list-disc list-inside space-y-1 text-xs">
                  <li>Not Processed → Processing, Cancelled</li>
                  <li>Processing → Partially Fulfilled, Fulfilled, Cancelled</li>
                  <li>Partially Fulfilled → Fulfilled, Cancelled</li>
                  <li>Fulfilled and Cancelled orders cannot be changed</li>
                </ul>
              </div>
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading || newStatus === transaction.status}
          >
            {isLoading ? 'Updating...' : 'Update Status'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
