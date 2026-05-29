import { useState } from 'react';
import { CheckCircle, XCircle, WarningCircle, Package } from '@phosphor-icons/react';
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
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { issueRegistrationKit } from '@/services/api';

interface IssueRegistrationKitDialogProps {
  transaction: any | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function IssueRegistrationKitDialog({
  transaction,
  open,
  onOpenChange,
  onSuccess,
}: IssueRegistrationKitDialogProps) {
  const [quantity, setQuantity] = useState<string>('1');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleIssue = async () => {
    if (!transaction) return;

    const qty = parseInt(quantity, 10);
    if (isNaN(qty) || qty < 1) {
      setError('Please enter a valid quantity (minimum: 1)');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await issueRegistrationKit(transaction.id, qty);
      setSuccess(result.message || `Successfully issued ${qty}x Registration Kit(s)`);

      // Wait a bit, then close and refresh
      setTimeout(() => {
        onSuccess?.();
        onOpenChange(false);
        setQuantity('1'); // Reset
      }, 1500);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to issue registration kit';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleCancel = () => {
    setQuantity('1');
    setError(null);
    setSuccess(null);
    onOpenChange(false);
  };

  if (!transaction) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="h-5 w-5 text-[rgb(var(--color-secondary))]" />
            Issue Registration Kit
          </DialogTitle>
          <DialogDescription>
            How many registration kits would you like to issue for this transaction?
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          {error && (
            <Alert variant="destructive" className="mb-4">
              <WarningCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {success && (
            <Alert className="mb-4 bg-[rgb(var(--color-secondary))]/[0.1] border-[rgb(var(--color-secondary))]/[0.3] text-[rgb(var(--color-secondary))] dark:bg-green-900/20 dark:border-green-800 dark:text-green-200">
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>{success}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-4">
            <Alert className="bg-[rgb(var(--color-secondary))]/[0.1] border-[rgb(var(--color-secondary))]/[0.2]">
              <Package className="h-4 w-4 text-[rgb(var(--color-secondary))]" />
              <AlertDescription className="text-[rgb(var(--color-muted-foreground))]">
                <p className="font-semibold mb-1">Registration Kit Issuance</p>
                <ul className="text-sm list-disc ml-5 space-y-1">
                  <li>Deducts KES 2,900.00 per kit from transaction amount</li>
                  <li>Remaining amount available for product fulfillment</li>
                  <li>Transaction status will remain PROCESSING (not FULFILLED)</li>
                </ul>
              </AlertDescription>
            </Alert>

            <div>
              <Label htmlFor="kit-quantity" className="mb-2 block">
                Quantity *
              </Label>
              <Input
                id="kit-quantity"
                type="number"
                min="1"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="Enter quantity (e.g., 1, 2, 3...)"
                className="w-full"
                autoFocus
                disabled={processing || !!success}
              />
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Enter the number of registration kits to issue
              </p>
            </div>

            <div className="p-3 bg-gray-50 dark:bg-slate-700 rounded-md">
              <div className="text-sm text-gray-600 dark:text-gray-400 mb-1">
                Transaction Amount
              </div>
              <div className="text-lg font-bold">
                KES {parseFloat(transaction.amount).toLocaleString()}
              </div>
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          <div className="flex gap-2 w-full">
            <Button
              variant="outline"
              onClick={handleCancel}
              disabled={processing}
              className="flex-1"
            >
              <XCircle className="mr-2 h-4 w-4" />
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={handleIssue}
              disabled={processing || !!success}
              className="flex-1 bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]"
            >
              {processing ? (
                'Issuing...'
              ) : (
                <>
                  <CheckCircle className="mr-2 h-4 w-4" />
                  Issue {quantity} Kit{parseInt(quantity) > 1 ? 's' : ''}
                </>
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
