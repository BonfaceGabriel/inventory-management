import { useState, useEffect, useCallback } from 'react';
import { Layers, TrendingUp, UserPlus, CheckCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Pagination } from '@/components/ui/pagination';
import { AdvancedFilters } from '@/components/transactions/AdvancedFilters';
import type { TransactionFilters } from '@/components/transactions/AdvancedFilters';
import { TransactionDetailModal } from '@/components/transactions/TransactionDetailModal';
import { StatusDropdown } from '@/components/transactions/StatusDropdown';
import { useTransactions } from '@/services/queries/transactions';
import { useDailyReport } from '@/services/queries/reports';
import { useWebSocketContext } from '@/contexts/WebSocketContext';
import { useAuth } from '@/contexts/AuthContext';
import { formatCurrency, formatDate, createCombinedOrder, getTransactionById, getTransactions, getGatewayColor, getGatewayLabel, getIssuerStats, type IssuerStats } from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';

export default function TransactionsPage() {
  const { hasProcessorAccess, hasIssuerAccess } = useAuth();
  const queryClient = useQueryClient();
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [page, setPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [filters, setFilters] = useState<TransactionFilters>({});

  // Issuer stats state
  const [issuerStats, setIssuerStats] = useState<IssuerStats | null>(null);

  // Combine orders state
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<number[]>([]);
  const [showCombineDialog, setShowCombineDialog] = useState(false);
  const [combineForm, setCombineForm] = useState({
    customer_name: '',
    customer_phone: '',
    notes: '',
  });
  const [isCombining, setIsCombining] = useState(false);

  const { data, isLoading, refetch } = useTransactions({
    ...filters,
    page,
    page_size: itemsPerPage,
  });
  // Only fetch daily report if user has processor access (Issuer users don't need this)
  const { data: report, refetch: refetchReport } = useDailyReport(undefined, hasProcessorAccess());

  const fetchIssuerStats = useCallback(async () => {
    if (!hasIssuerAccess() || hasProcessorAccess()) return;
    try {
      const stats = await getIssuerStats();
      setIssuerStats(stats);
    } catch {
      // silently ignore — stats are supplementary
    }
  }, []);
  const { onTransactionCreated, isConnected, error } = useWebSocketContext();

  const orders = data?.results || [];
  const totalItems = data?.count || 0;
  const totalPages = Math.ceil(totalItems / itemsPerPage);

  // Debug: Log WebSocket connection status
  useEffect(() => {
    console.log('🔍 WebSocket Status:', {
      isConnected,
      error
    });
  }, [isConnected, error]);

  // Fetch issuer stats on mount
  useEffect(() => {
    fetchIssuerStats();
  }, [fetchIssuerStats]);

  // Listen for new transactions from WebSocket
  useEffect(() => {
    const cleanup = onTransactionCreated((newTransaction) => {
      console.log('📱 New transaction on Transactions page:', newTransaction.tx_id);
      console.log('🔄 Calling refetch()...');

      // Auto-refresh the list to include new transaction
      refetch();
      // Only refresh the daily report for users who have access (Processor/Admin)
      // Calling refetchReport() for an Issuer bypasses the enabled:false guard and
      // triggers a 403 which the interceptor escalates to a full /unauthorized redirect
      if (hasProcessorAccess()) {
        refetchReport();
      }
      // Refresh issuer stats if applicable
      fetchIssuerStats();
    });

    return cleanup;
  }, [onTransactionCreated, refetch, refetchReport, fetchIssuerStats, hasProcessorAccess]);

  const handleClearFilters = () => {
    setFilters({});
    setPage(1);
  };

  const handleFiltersChange = (newFilters: TransactionFilters) => {
    setFilters(newFilters);
    setPage(1); // Reset to first page when filters change
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
  };

  const handleItemsPerPageChange = (newItemsPerPage: number) => {
    setItemsPerPage(newItemsPerPage);
    setPage(1); // Reset to first page when changing items per page
  };

  const handleRowClick = (transaction: Transaction) => {
    setSelectedTransaction(transaction);
    setShowDetail(true);
  };

  const handleUpdateSuccess = async () => {
    // Invalidate ALL transaction-related queries to force a fresh fetch
    await queryClient.invalidateQueries({ queryKey: ['transactions'] });
    await queryClient.invalidateQueries({ queryKey: ['transaction'] });
    await queryClient.invalidateQueries({ queryKey: ['combined-orders'] });

    // Refetch the current transactions list
    refetch();

    // Also refresh the currently selected transaction to show updated data
    if (selectedTransaction) {
      try {
        const updatedTransaction = await getTransactionById(selectedTransaction.id);
        console.log('[TransactionsPage] Refreshed transaction:', updatedTransaction);
        setSelectedTransaction(updatedTransaction);
      } catch (error) {
        console.error('Failed to refresh transaction details:', error);
      }
    }
  };

  // Handler for viewing parent transaction (combined order) from child transaction
  const handleViewParentTransaction = async (parentTransactionId: number | undefined, combinedOrderId?: string) => {
    console.log('handleViewParentTransaction called with:', { parentTransactionId, combinedOrderId });

    try {
      let parentTransaction;

      if (parentTransactionId) {
        // If we have parent_transaction_id, use it directly
        parentTransaction = await getTransactionById(parentTransactionId);
      } else if (combinedOrderId) {
        // Fallback: search for transaction by tx_id matching combined_order_id
        const response = await getTransactions({ search: combinedOrderId, page_size: 1 });
        const results = response.results || [];
        parentTransaction = results.find((t: Transaction) => t.tx_id === combinedOrderId);

        if (!parentTransaction) {
          toast.error(`Could not find combined order ${combinedOrderId}`);
          return;
        }
      } else {
        toast.error('No parent transaction information available');
        return;
      }

      console.log('Fetched parent transaction:', parentTransaction);
      setSelectedTransaction(parentTransaction);
    } catch (error) {
      console.error('Failed to fetch parent transaction:', error);
      toast.error('Failed to load combined order details');
    }
  };

  // Combine orders handlers
  const handleToggleSelection = (transactionId: number, transaction: Transaction) => {
    // Prevent selecting transactions that are already in a combined order
    if (transaction.is_in_combined_order) {
      toast.error('This transaction is already part of a combined order');
      return;
    }

    // Prevent selecting combined order parent transactions (CMB-xxx)
    if (transaction.tx_id?.startsWith('CMB-')) {
      toast.error('Combined order parents cannot be re-combined. Use "Add Transactions" from the order detail instead.');
      return;
    }

    // Allow NOT_PROCESSED and PARTIALLY_FULFILLED transactions to be selected
    const allowedStatuses = ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'];
    if (!allowedStatuses.includes(transaction.status)) {
      toast.error(`Cannot select ${transaction.status} transaction. Only NOT_PROCESSED or PARTIALLY_FULFILLED transactions can be combined.`);
      return;
    }

    setSelectedTransactionIds((prev) =>
      prev.includes(transactionId)
        ? prev.filter((id) => id !== transactionId)
        : [...prev, transactionId]
    );
  };

  const handleSelectAll = () => {
    // Only select NOT_PROCESSED and PARTIALLY_FULFILLED transactions that are NOT in combined orders
    // and are NOT combined order parent transactions (CMB-xxx)
    const allowedStatuses = ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'];
    const selectableOrders = orders.filter(
      tx => allowedStatuses.includes(tx.status) && !tx.is_in_combined_order && !tx.tx_id?.startsWith('CMB-')
    );

    if (selectedTransactionIds.length === selectableOrders.length && selectableOrders.length > 0) {
      setSelectedTransactionIds([]);
    } else {
      setSelectedTransactionIds(selectableOrders.map((tx) => tx.id));
      if (selectableOrders.length < orders.length) {
        const skipped = orders.length - selectableOrders.length;
        toast.info(`Selected ${selectableOrders.length} transactions. ${skipped} already combined or not eligible.`);
      }
    }
  };

  const handleCombineClick = () => {
    if (selectedTransactionIds.length < 2) {
      toast.error('Please select at least 2 transactions to combine');
      return;
    }
    setShowCombineDialog(true);
  };

  const handleCombineSubmit = async () => {
    const loadingToast = toast.loading('Creating combined order...');
    try {
      setIsCombining(true);
      const result = await createCombinedOrder({
        transaction_ids: selectedTransactionIds,
        customer_name: combineForm.customer_name,
        customer_phone: combineForm.customer_phone,
        notes: combineForm.notes,
        created_by: 'System',
      });

      toast.dismiss(loadingToast);
      toast.success(`Combined order created successfully! ${result.transaction_count} transactions combined.`);

      // Reset state
      setSelectedTransactionIds([]);
      setCombineForm({ customer_name: '', customer_phone: '', notes: '' });
      setShowCombineDialog(false);

      // Refresh transactions list
      refetch();
    } catch (error: any) {
      console.error('Failed to combine orders:', error);
      toast.dismiss(loadingToast);
      const errorMsg = error.response?.data?.error || 'Failed to create combined order';
      toast.error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg));
    } finally {
      setIsCombining(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Orders</h1>
          <p className="text-gray-600 dark:text-gray-400">Overview of today's transactions and complete order history</p>
        </div>
        <div className="flex gap-2">
          {selectedTransactionIds.length >= 2 && (
            <Button onClick={handleCombineClick} variant="default" size="sm" className="bg-blue-600 hover:bg-blue-700">
              <Layers className="mr-2 h-4 w-4" />
              Combine ({selectedTransactionIds.length})
            </Button>
          )}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-2">
        {hasProcessorAccess() ? (
          <>
            <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-blue-100 dark:border-blue-900 bg-gradient-to-br from-white to-blue-50 dark:from-slate-800 dark:to-blue-950">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-blue-900 dark:text-blue-100">Total Transactions</CardTitle>
                <TrendingUp className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">
                  {report?.summary.total_transactions || 0}
                </div>
                <p className="text-xs text-blue-600 dark:text-blue-400">Transactions today</p>
              </CardContent>
            </Card>

            <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-blue-100 dark:border-blue-900 bg-gradient-to-br from-white to-blue-50 dark:from-slate-800 dark:to-blue-950">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-blue-900 dark:text-blue-100">Total Amount</CardTitle>
                <TrendingUp className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">
                  {formatCurrency(report?.summary.total_amount || '0')}
                </div>
                <p className="text-xs text-blue-600 dark:text-blue-400">Revenue today</p>
              </CardContent>
            </Card>
          </>
        ) : (
          <>
            <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-green-100 dark:border-green-900 bg-gradient-to-br from-white to-green-50 dark:from-slate-800 dark:to-green-950">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-green-900 dark:text-green-100">Fulfilled Today</CardTitle>
                <CheckCircle className="h-4 w-4 text-green-600 dark:text-green-400" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-700 dark:text-green-300">
                  {issuerStats?.fulfilled_today ?? 0}
                </div>
                <p className="text-xs text-green-600 dark:text-green-400">Orders completed today</p>
              </CardContent>
            </Card>

            <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-green-100 dark:border-green-900 bg-gradient-to-br from-white to-green-50 dark:from-slate-800 dark:to-green-950">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-green-900 dark:text-green-100">Amount Fulfilled</CardTitle>
                <CheckCircle className="h-4 w-4 text-green-600 dark:text-green-400" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-700 dark:text-green-300">
                  {formatCurrency(issuerStats?.amount_fulfilled_today ?? '0')}
                </div>
                <p className="text-xs text-green-600 dark:text-green-400">Total value fulfilled today</p>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* Advanced Filters */}
      <AdvancedFilters
        filters={filters}
        onFiltersChange={handleFiltersChange}
        onClear={handleClearFilters}
      />

      {/* Orders Table */}
      <Card>
        <CardHeader>
          <CardTitle>Orders List</CardTitle>
          <CardDescription>
            {isLoading ? 'Loading...' : `${totalItems} total orders`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : orders.length === 0 ? (
            <p className="text-center text-sm text-gray-600 dark:text-gray-400 py-8">
              No orders found
            </p>
          ) : (
            <div className="space-y-4">
              <div className="rounded-md border border-gray-200 dark:border-gray-700">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">
                        <Checkbox
                          checked={
                            selectedTransactionIds.length > 0 &&
                            selectedTransactionIds.length === orders.filter(tx => ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) && !tx.is_in_combined_order).length &&
                            orders.filter(tx => ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) && !tx.is_in_combined_order).length > 0
                          }
                          onCheckedChange={handleSelectAll}
                          aria-label="Select all eligible transactions"
                        />
                      </TableHead>
                      <TableHead>TX ID</TableHead>
                      <TableHead>Amount</TableHead>
                      <TableHead>Fulfilled</TableHead>
                      <TableHead>Remaining</TableHead>
                      <TableHead>Sender</TableHead>
                      <TableHead>Phone</TableHead>
                      <TableHead>Gateway</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Time</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {orders.map((tx) => (
                      <TableRow
                        key={tx.id}
                        className="hover:bg-gray-50 dark:hover:bg-slate-700"
                      >
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={selectedTransactionIds.includes(tx.id)}
                            onCheckedChange={() => handleToggleSelection(tx.id, tx)}
                            disabled={!['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) || tx.is_in_combined_order || tx.tx_id?.startsWith('CMB-')}
                            aria-label={`Select transaction ${tx.tx_id}`}
                            className={!['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) || tx.is_in_combined_order || tx.tx_id?.startsWith('CMB-') ? 'opacity-30 cursor-not-allowed' : ''}
                          />
                        </TableCell>
                        <TableCell
                          className="font-medium cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          <div className="flex items-center gap-2">
                            {tx.tx_id}
                            {tx.is_registration && (
                              <span title="Registration" className="text-purple-600 dark:text-purple-400">
                                <UserPlus className="w-4 h-4" />
                              </span>
                            )}
                            {tx.is_in_combined_order && (
                              <span title="Combined Order" className="text-gray-500 dark:text-gray-400">
                                <Layers className="w-4 h-4" />
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell
                          className="font-bold cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {formatCurrency(tx.amount)}
                        </TableCell>
                        <TableCell
                          className="text-green-600 dark:text-green-400 font-semibold cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {formatCurrency(tx.amount_fulfilled || tx.amount_paid || '0')}
                        </TableCell>
                        <TableCell
                          className="font-semibold text-orange-600 dark:text-orange-400 cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {formatCurrency(tx.remaining_amount || '0')}
                        </TableCell>
                        <TableCell
                          className="cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {tx.sender_name}
                        </TableCell>
                        <TableCell
                          className="cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {tx.sender_phone}
                        </TableCell>
                        <TableCell
                          className="text-sm cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {tx.combined_order_info?.parent_transaction_id !== tx.id && (
                            <span
                              style={tx.gateway_type === 'MPESA_TILL' ? { color: '#10B981' } : undefined}
                            >
                              {getGatewayLabel(tx.gateway_type)}
                            </span>
                          )}
                        </TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <StatusDropdown transaction={tx} onUpdate={refetch} />
                        </TableCell>
                        <TableCell
                          className="cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {formatDate(tx.timestamp)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <Pagination
                  currentPage={page}
                  totalPages={totalPages}
                  totalItems={totalItems}
                  itemsPerPage={itemsPerPage}
                  onPageChange={handlePageChange}
                  onItemsPerPageChange={handleItemsPerPageChange}
                />
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Transaction Detail Modal */}
      <TransactionDetailModal
        transaction={selectedTransaction}
        open={showDetail}
        onOpenChange={setShowDetail}
        onUpdate={handleUpdateSuccess}
        onViewParentTransaction={handleViewParentTransaction}
      />

      {/* Combine Orders Dialog */}
      <Dialog open={showCombineDialog} onOpenChange={setShowCombineDialog}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Combine Selected Orders</DialogTitle>
            <DialogDescription>
              Create a combined order from {selectedTransactionIds.length} selected transactions.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Selected Transactions Summary */}
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <h3 className="font-semibold mb-2">Selected Transactions</h3>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {orders
                  .filter((tx) => selectedTransactionIds.includes(tx.id))
                  .map((tx) => (
                    <div key={tx.id} className="flex justify-between text-sm">
                      <span className="text-gray-700 dark:text-gray-300">{tx.tx_id}</span>
                      <span className="font-semibold">{formatCurrency(tx.amount)}</span>
                    </div>
                  ))}
              </div>
              <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 flex justify-between font-bold">
                <span>Total Amount:</span>
                <span>
                  {formatCurrency(
                    orders
                      .filter((tx) => selectedTransactionIds.includes(tx.id))
                      .reduce((sum, tx) => sum + parseFloat(tx.amount), 0)
                      .toFixed(2)
                  )}
                </span>
              </div>
            </div>

            {/* Customer Information (Optional) */}
            <div className="space-y-3">
              <div>
                <Label htmlFor="customer_name">Customer Name (Optional)</Label>
                <Input
                  id="customer_name"
                  value={combineForm.customer_name}
                  onChange={(e) =>
                    setCombineForm({ ...combineForm, customer_name: e.target.value })
                  }
                  placeholder="Enter customer name"
                />
              </div>

              <div>
                <Label htmlFor="customer_phone">Customer Phone (Optional)</Label>
                <Input
                  id="customer_phone"
                  value={combineForm.customer_phone}
                  onChange={(e) =>
                    setCombineForm({ ...combineForm, customer_phone: e.target.value })
                  }
                  placeholder="e.g., 0712345678"
                />
              </div>

              <div>
                <Label htmlFor="notes">Notes (Optional)</Label>
                <Textarea
                  id="notes"
                  value={combineForm.notes}
                  onChange={(e) =>
                    setCombineForm({ ...combineForm, notes: e.target.value })
                  }
                  placeholder="Add any notes about this combined order"
                  rows={3}
                />
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCombineDialog(false)}
              disabled={isCombining}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCombineSubmit}
              disabled={isCombining}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {isCombining ? 'Creating...' : 'Create Combined Order'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  );
}
