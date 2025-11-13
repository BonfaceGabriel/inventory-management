import { useState } from 'react';
import { Clock, User, Phone, CreditCard, Hash, Calendar, TrendingUp, MessageSquare, FileText } from 'lucide-react';
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
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { formatCurrency, formatDate, getStatusColor, getStatusLabel } from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { StatusChangeDialog } from './StatusChangeDialog';

interface TransactionDetailModalProps {
  transaction: Transaction | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate?: () => void;
}

export function TransactionDetailModal({
  transaction,
  open,
  onOpenChange,
  onUpdate,
}: TransactionDetailModalProps) {
  const [showStatusChange, setShowStatusChange] = useState(false);

  if (!transaction) return null;

  const isLocked = transaction.is_locked;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader onClose={() => onOpenChange(false)}>
            <DialogTitle>Order Details</DialogTitle>
            <DialogDescription>
              View and manage order #{transaction.tx_id}
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            <div className="space-y-6">
              {/* Status Badge */}
              <div className="flex items-center justify-between">
                <Badge
                  style={{ backgroundColor: getStatusColor(transaction.status) }}
                  className="text-white px-4 py-2 text-sm"
                >
                  {getStatusLabel(transaction.status)}
                </Badge>
                {!isLocked && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowStatusChange(true)}
                  >
                    Change Status
                  </Button>
                )}
              </div>

              {/* Transaction Info Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-4">
                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <Hash className="h-4 w-4" />
                      Transaction ID
                    </Label>
                    <p className="mt-1 font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {transaction.tx_id}
                    </p>
                  </div>

                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <User className="h-4 w-4" />
                      Sender Name
                    </Label>
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {transaction.sender_name || 'N/A'}
                    </p>
                  </div>

                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <Phone className="h-4 w-4" />
                      Phone Number
                    </Label>
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {transaction.sender_phone || 'N/A'}
                    </p>
                  </div>

                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <CreditCard className="h-4 w-4" />
                      Gateway
                    </Label>
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {transaction.gateway_name || transaction.gateway_type || 'N/A'}
                    </p>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <TrendingUp className="h-4 w-4" />
                      Amount
                    </Label>
                    <p className="mt-1 text-2xl font-bold text-orange-600 dark:text-orange-500">
                      {formatCurrency(transaction.amount)}
                    </p>
                  </div>

                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <Calendar className="h-4 w-4" />
                      Date & Time
                    </Label>
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {formatDate(transaction.timestamp)}
                    </p>
                  </div>

                  <div>
                    <Label className="text-gray-600 dark:text-gray-400">
                      Remaining Amount
                    </Label>
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {formatCurrency(transaction.remaining_amount || 0)}
                    </p>
                  </div>

                  <div>
                    <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                      <Clock className="h-4 w-4" />
                      Created
                    </Label>
                    <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">
                      {formatDate(transaction.created_at)}
                    </p>
                  </div>
                </div>
              </div>

              {/* Notes Section */}
              {transaction.notes && (
                <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mb-2">
                    <FileText className="h-4 w-4" />
                    Notes
                  </Label>
                  <p className="text-sm text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-slate-700 p-3 rounded">
                    {transaction.notes}
                  </p>
                </div>
              )}

              {/* Raw Messages */}
              {transaction.raw_messages && transaction.raw_messages.length > 0 && (
                <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mb-2">
                    <MessageSquare className="h-4 w-4" />
                    Original SMS Message{transaction.raw_messages.length > 1 ? 's' : ''}
                  </Label>
                  <div className="space-y-2">
                    {transaction.raw_messages.map((msg, idx) => (
                      <div
                        key={idx}
                        className="text-sm text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-slate-700 p-3 rounded font-mono"
                      >
                        {msg.raw_text}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Manual Payments */}
              {transaction.manual_payments && transaction.manual_payments.length > 0 && (
                <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                  <Label className="text-gray-600 dark:text-gray-400 mb-2">
                    Manual Payment Entries
                  </Label>
                  <div className="space-y-2">
                    {transaction.manual_payments.map((payment: any, idx: number) => (
                      <div
                        key={idx}
                        className="text-sm text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-slate-700 p-3 rounded"
                      >
                        <p>
                          <strong>Method:</strong> {payment.payment_method}
                        </p>
                        <p>
                          <strong>Reference:</strong> {payment.reference_number || 'N/A'}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </DialogBody>

          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Status Change Dialog */}
      <StatusChangeDialog
        transaction={transaction}
        open={showStatusChange}
        onOpenChange={setShowStatusChange}
        onSuccess={() => {
          onUpdate?.();
          setShowStatusChange(false);
        }}
      />
    </>
  );
}
