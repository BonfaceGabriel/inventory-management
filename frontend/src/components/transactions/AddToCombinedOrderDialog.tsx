import { useState, useEffect } from 'react';
import { MagnifyingGlass, StackSimple, Plus, WarningCircle, CheckCircle, Calendar, ArrowsCounterClockwise } from '@phosphor-icons/react';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
import { formatCurrency, formatDate, getStatusColor, getTransactions, addTransactionsToCombinedOrder } from '@/services/api';

interface AddToCombinedOrderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  combinedOrderId: string;
  combinedOrderStatus?: string;
  onSuccess?: (updatedOrderData?: any) => void;
}

interface Transaction {
  id: number;
  tx_id: string;
  sender_name: string;
  amount: string;
  status: string;
  timestamp: string;
  is_registration: boolean;
  is_in_combined_order?: boolean;
}

export function AddToCombinedOrderDialog({
  open,
  onOpenChange,
  combinedOrderId,
  onSuccess,
}: AddToCombinedOrderDialogProps) {
  const [availableTransactions, setAvailableTransactions] = useState<Transaction[]>([]);
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Load available transactions when dialog opens or filters change
  useEffect(() => {
    if (open) {
      loadAvailableTransactions();
    }
  }, [open, startDate, endDate, searchQuery]);

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setSelectedTransactionIds([]);
      setSearchQuery('');
      setError(null);
      setSuccess(null);
      // Default to last 30 days if no date set
      if (!startDate && !endDate) {
        const thirtyDaysAgo = new Date();
        thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
        setStartDate(thirtyDaysAgo.toISOString().split('T')[0]);
        setEndDate(new Date().toISOString().split('T')[0]);
      }
    }
  }, [open]);

  const loadAvailableTransactions = async () => {
    setLoading(true);
    setError(null);

    try {
      const params: any = {
        page_size: 500,
      };

      // When the user is searching for a specific TX, skip date filters so
      // results aren't silently dropped because they fall outside the date window.
      if (searchQuery) {
        params.search = searchQuery;
      } else {
        if (startDate) {
          params.min_date = `${startDate}T00:00:00`;
        }
        if (endDate) {
          params.max_date = `${endDate}T23:59:59`;
        }
      }

      const data = await getTransactions(params);

      const transactions = Array.isArray(data) ? data : data.results || [];

      // Filter to NOT_PROCESSED and PARTIALLY_FULFILLED transactions that aren't already in combined orders.
      // Also exclude combined order parent transactions (tx_id starts with "CMB-") — those
      // represent existing combined orders and must be extended via "Add Transactions", not re-combined.
      const eligible = transactions.filter((t: any) =>
        !t.is_in_combined_order &&
        ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(t.status) &&
        !t.tx_id?.startsWith('CMB-')
      );

      setAvailableTransactions(eligible);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || err.message || 'Failed to load available transactions';
      setError(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg));
    } finally {
      setLoading(false);
    }
  };

  const handleToggleTransaction = (transactionId: number) => {
    setSelectedTransactionIds(prev => {
      if (prev.includes(transactionId)) {
        return prev.filter(id => id !== transactionId);
      } else {
        return [...prev, transactionId];
      }
    });
  };

  const handleAddTransactions = async () => {
    if (selectedTransactionIds.length === 0) {
      setError('Please select at least one transaction');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await addTransactionsToCombinedOrder(
        combinedOrderId,
        selectedTransactionIds
      );

      console.log('[AddToCombinedOrderDialog] Add transactions SUCCESS, result:', result);
      console.log('[AddToCombinedOrderDialog] Combined order data from response:', result.combined_order);

      setSuccess(
        `Successfully added ${result.added_count} transaction(s). New total: KES ${result.new_total_amount}`
      );

      // Pass the updated data directly to parent instead of relying on refetch
      console.log('[AddToCombinedOrderDialog] Calling onSuccess callback with updated data...');
      onSuccess?.(result.combined_order);

      // Wait a bit then close dialog so user sees success message
      setTimeout(() => {
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (Array.isArray(err.response.data.error)
            ? err.response.data.error.join(', ')
            : typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to add transactions';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  // Search is now server-side; use the full eligible list directly
  const filteredTransactions = availableTransactions;

  const selectedTotal = availableTransactions
    .filter(t => selectedTransactionIds.includes(t.id))
    .reduce((sum, t) => sum + parseFloat(t.amount), 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <StackSimple className="h-5 w-5 text-[rgb(var(--color-secondary))]" />
            Add Transactions to Combined Order
          </DialogTitle>
          <DialogDescription>
            Select NOT_PROCESSED or PARTIALLY_FULFILLED transactions to add to Combined Order {combinedOrderId}.
            Use the date range filter to find historical transactions.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          {/* Alerts */}
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

          {/* Info Alert */}
          <Alert className="mb-4 bg-[rgb(var(--color-primary))]/[0.1] border-[rgb(var(--color-primary))]/[0.3] dark:bg-blue-900/20 dark:border-blue-800">
            <WarningCircle className="h-4 w-4 text-[rgb(var(--color-primary))]" />
            <AlertDescription className="text-[rgb(var(--color-primary))] dark:text-blue-200">
              <strong>Requirements:</strong>
              <ul className="list-disc ml-5 mt-1 space-y-1 text-sm">
                <li>Transactions must be NOT_PROCESSED or PARTIALLY_FULFILLED</li>
                <li>Cannot be in another combined order</li>
                <li>Cannot be a combined order parent transaction</li>
                <li>Cannot be time-locked</li>
                <li>No active stock-taking session</li>
              </ul>
            </AlertDescription>
          </Alert>

          {/* Date Range Filter */}
          <div className="mb-4 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <Label className="mb-2 block flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              Date Range Filter
            </Label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-gray-600 dark:text-gray-400 mb-1 block">
                  Start Date
                </Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full"
                />
              </div>
              <div>
                <Label className="text-xs text-gray-600 dark:text-gray-400 mb-1 block">
                  End Date
                </Label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full"
                />
              </div>
            </div>
            <div className="mt-2 flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  const today = new Date().toISOString().split('T')[0];
                  setStartDate(today);
                  setEndDate(today);
                }}
                className="text-xs"
              >
                Today
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  const sevenDaysAgo = new Date();
                  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
                  setStartDate(sevenDaysAgo.toISOString().split('T')[0]);
                  setEndDate(new Date().toISOString().split('T')[0]);
                }}
                className="text-xs"
              >
                Last 7 Days
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  const thirtyDaysAgo = new Date();
                  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
                  setStartDate(thirtyDaysAgo.toISOString().split('T')[0]);
                  setEndDate(new Date().toISOString().split('T')[0]);
                }}
                className="text-xs"
              >
                Last 30 Days
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setStartDate('');
                  setEndDate('');
                }}
                className="text-xs"
              >
                <ArrowsCounterClockwise className="h-3 w-3 mr-1" />
                Clear
              </Button>
            </div>
          </div>

          {/* Search */}
          <div className="mb-4">
            <Label className="mb-2 block">Search Transactions</Label>
            <div className="relative">
              <MagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <Input
                placeholder="Search by TX ID, sender name, or amount..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>

          {/* Selected Summary */}
          {selectedTransactionIds.length > 0 && (
            <div className="mb-4 p-3 bg-[rgb(var(--color-secondary))]/[0.1] border border-[rgb(var(--color-secondary))]/[0.2] rounded-md">
              <div className="flex items-center justify-between">
                <div className="text-sm text-[rgb(var(--color-muted-foreground))]">
                  <strong>{selectedTransactionIds.length}</strong> transaction(s) selected
                </div>
                <div className="text-lg font-bold text-[rgb(var(--color-secondary))]">
                  Total: {formatCurrency(selectedTotal)}
                </div>
              </div>
            </div>
          )}

          {/* Transactions Table */}
          {loading ? (
            <div className="text-center py-8 text-gray-500">
              Loading available transactions...
            </div>
          ) : filteredTransactions.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              {searchQuery
                ? 'No transactions found matching your search'
                : 'No eligible transactions available'}
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden">
              <Table>
                <TableHeader className="bg-gray-50 dark:bg-gray-800">
                  <TableRow>
                    <TableHead className="w-12">Select</TableHead>
                    <TableHead>Transaction ID</TableHead>
                    <TableHead>Sender</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredTransactions.map((transaction) => (
                    <TableRow
                      key={transaction.id}
                      className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 ${
                        selectedTransactionIds.includes(transaction.id)
                          ? 'bg-[rgb(var(--color-primary))]/[0.08]'
                          : ''
                      }`}
                      onClick={() => handleToggleTransaction(transaction.id)}
                    >
                      <TableCell>
                        <Checkbox
                          checked={selectedTransactionIds.includes(transaction.id)}
                          onCheckedChange={() => handleToggleTransaction(transaction.id)}
                        />
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {transaction.tx_id}
                        {transaction.is_registration && (
                          <Badge className="ml-2 bg-[rgb(var(--color-primary))] text-white text-xs">
                            Registration
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="font-medium">
                        {transaction.sender_name || 'N/A'}
                      </TableCell>
                      <TableCell className="text-right font-bold text-[rgb(var(--color-primary))] dark:text-orange-400">
                        {formatCurrency(transaction.amount)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          style={{ backgroundColor: getStatusColor(transaction.status) }}
                          className="text-white text-xs"
                        >
                          {transaction.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                        {formatDate(transaction.timestamp)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <div className="flex gap-2 w-full">
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={processing}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={handleAddTransactions}
              disabled={processing || selectedTransactionIds.length === 0}
              className="flex-1 bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]"
            >
              <Plus className="mr-2 h-4 w-4" />
              {processing
                ? 'Adding...'
                : `Add ${selectedTransactionIds.length} Transaction${selectedTransactionIds.length !== 1 ? 's' : ''}`}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
