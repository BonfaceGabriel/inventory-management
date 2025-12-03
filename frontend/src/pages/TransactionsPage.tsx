import { useState, useEffect } from 'react';
import { FileSpreadsheet, FileText, Layers } from 'lucide-react';
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
import { useWebSocketContext } from '@/contexts/WebSocketContext';
import { formatCurrency, formatDate, downloadTransactionsCSV, downloadTransactionsXLSX, createCombinedOrder } from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { toast } from 'sonner';

export default function TransactionsPage() {
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [page, setPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [filters, setFilters] = useState<TransactionFilters>({});
  const [isExporting, setIsExporting] = useState(false);

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

  // Listen for new transactions from WebSocket
  useEffect(() => {
    const cleanup = onTransactionCreated((newTransaction) => {
      console.log('📱 New transaction on Transactions page:', newTransaction.tx_id);
      console.log('🔄 Calling refetch()...');

      // Auto-refresh the list to include new transaction
      refetch();
    });

    return cleanup;
  }, [onTransactionCreated, refetch]);

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

  const handleUpdateSuccess = () => {
    refetch();
  };

  const handleExportCSV = async () => {
    try {
      setIsExporting(true);
      // Use filters to export filtered data
      const exportParams: any = {};
      if (filters.min_date || filters.max_date) {
        if (filters.min_date && filters.max_date) {
          exportParams.start_date = filters.min_date;
          exportParams.end_date = filters.max_date;
        } else if (filters.min_date) {
          exportParams.date = filters.min_date;
        }
      }
      await downloadTransactionsCSV(exportParams);
      toast.success('CSV export downloaded successfully');
    } catch (error) {
      console.error('CSV export error:', error);
      toast.error('Failed to download CSV export');
    } finally {
      setIsExporting(false);
    }
  };

  const handleExportXLSX = async () => {
    try {
      setIsExporting(true);
      // Use filters to export filtered data
      const exportParams: any = {};
      if (filters.min_date || filters.max_date) {
        if (filters.min_date && filters.max_date) {
          exportParams.start_date = filters.min_date;
          exportParams.end_date = filters.max_date;
        } else if (filters.min_date) {
          exportParams.date = filters.min_date;
        }
      }
      await downloadTransactionsXLSX(exportParams);
      toast.success('Excel export downloaded successfully');
    } catch (error) {
      console.error('XLSX export error:', error);
      toast.error('Failed to download Excel export');
    } finally {
      setIsExporting(false);
    }
  };

  // Combine orders handlers
  const handleToggleSelection = (transactionId: number, transaction: Transaction) => {
    // Only allow NOT_PROCESSED transactions to be selected
    if (transaction.status !== 'NOT_PROCESSED') {
      toast.error(`Cannot select ${transaction.status} transaction. Only NOT_PROCESSED transactions can be combined.`);
      return;
    }

    setSelectedTransactionIds((prev) =>
      prev.includes(transactionId)
        ? prev.filter((id) => id !== transactionId)
        : [...prev, transactionId]
    );
  };

  const handleSelectAll = () => {
    // Only select NOT_PROCESSED transactions
    const notProcessedOrders = orders.filter(tx => tx.status === 'NOT_PROCESSED');

    if (selectedTransactionIds.length === notProcessedOrders.length && notProcessedOrders.length > 0) {
      setSelectedTransactionIds([]);
    } else {
      setSelectedTransactionIds(notProcessedOrders.map((tx) => tx.id));
      if (notProcessedOrders.length < orders.length) {
        toast.info(`Only ${notProcessedOrders.length} NOT_PROCESSED transactions selected. Other statuses cannot be combined.`);
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
        created_by: 'System', // TODO: Get from auth context
      });

      toast.dismiss(loadingToast);
      toast.success(`Combined order ${result.combined_order_id} created successfully!`);

      // Reset state
      setSelectedTransactionIds([]);
      setCombineForm({ customer_name: '', customer_phone: '', notes: '' });
      setShowCombineDialog(false);

      // Refresh transactions list
      refetch();
    } catch (error: any) {
      console.error('Failed to combine orders:', error);
      toast.dismiss(loadingToast);
      toast.error(error.response?.data?.error || 'Failed to create combined order');
    } finally {
      setIsCombining(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Orders</h1>
          <p className="text-gray-600 dark:text-gray-400">View and manage all M-Pesa orders</p>
        </div>
        <div className="flex gap-2">
          {selectedTransactionIds.length >= 2 && (
            <Button onClick={handleCombineClick} variant="default" size="sm" className="bg-blue-600 hover:bg-blue-700">
              <Layers className="mr-2 h-4 w-4" />
              Combine Selected ({selectedTransactionIds.length})
            </Button>
          )}
          <Button onClick={handleExportCSV} disabled={isExporting} variant="outline" size="sm">
            <FileText className="mr-2 h-4 w-4" />
            Export CSV
          </Button>
          <Button onClick={handleExportXLSX} disabled={isExporting} variant="outline" size="sm">
            <FileSpreadsheet className="mr-2 h-4 w-4" />
            Export Excel
          </Button>
        </div>
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
                            selectedTransactionIds.length === orders.filter(tx => tx.status === 'NOT_PROCESSED').length &&
                            orders.filter(tx => tx.status === 'NOT_PROCESSED').length > 0
                          }
                          onCheckedChange={handleSelectAll}
                          aria-label="Select all NOT_PROCESSED transactions"
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
                            disabled={tx.status !== 'NOT_PROCESSED'}
                            aria-label={`Select transaction ${tx.tx_id}`}
                            className={tx.status !== 'NOT_PROCESSED' ? 'opacity-30 cursor-not-allowed' : ''}
                          />
                        </TableCell>
                        <TableCell
                          className="font-medium cursor-pointer"
                          onClick={() => handleRowClick(tx)}
                        >
                          {tx.tx_id}
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
                          {tx.gateway_name || tx.gateway_type || 'N/A'}
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
      />

      {/* Combine Orders Dialog */}
      <Dialog open={showCombineDialog} onOpenChange={setShowCombineDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-2xl font-bold">Combine Selected Transactions</DialogTitle>
            <DialogDescription className="text-base">
              You are combining {selectedTransactionIds.length} transactions into a single combined order for easier fulfillment.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-6">
            {/* Selected Transactions Summary */}
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4">
              <p className="font-semibold text-sm text-gray-700 dark:text-gray-300 mb-3">
                Selected Transactions ({selectedTransactionIds.length})
              </p>
              <div className="flex flex-wrap gap-2">
                {orders
                  .filter(tx => selectedTransactionIds.includes(tx.id))
                  .map(tx => (
                    <div
                      key={tx.id}
                      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200 text-sm"
                    >
                      <span className="font-mono font-semibold">{tx.tx_id}</span>
                      <span className="text-xs opacity-75">•</span>
                      <span className="font-semibold">{formatCurrency(tx.amount)}</span>
                    </div>
                  ))}
              </div>
              <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-600">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Total Amount:</span>
                  <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
                    {formatCurrency(
                      orders
                        .filter(tx => selectedTransactionIds.includes(tx.id))
                        .reduce((sum, tx) => sum + parseFloat(tx.amount), 0)
                    )}
                  </span>
                </div>
              </div>
            </div>

            {/* Customer Information */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Customer Information</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="customer_name" className="text-sm font-medium">
                    Customer Name <span className="text-gray-400 font-normal">(Optional)</span>
                  </Label>
                  <Input
                    id="customer_name"
                    placeholder="Enter customer name"
                    value={combineForm.customer_name}
                    onChange={(e) => setCombineForm({ ...combineForm, customer_name: e.target.value })}
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="customer_phone" className="text-sm font-medium">
                    Customer Phone <span className="text-gray-400 font-normal">(Optional)</span>
                  </Label>
                  <Input
                    id="customer_phone"
                    placeholder="e.g., 0712345678"
                    value={combineForm.customer_phone}
                    onChange={(e) => setCombineForm({ ...combineForm, customer_phone: e.target.value })}
                    className="h-10"
                  />
                </div>
              </div>
            </div>

            {/* Notes */}
            <div className="space-y-2">
              <Label htmlFor="notes" className="text-sm font-medium">
                Notes <span className="text-gray-400 font-normal">(Optional)</span>
              </Label>
              <Textarea
                id="notes"
                placeholder="Add any notes about this combined order..."
                value={combineForm.notes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setCombineForm({ ...combineForm, notes: e.target.value })}
                rows={3}
                className="resize-none"
              />
            </div>
          </div>

          <DialogFooter className="gap-3">
            <Button
              variant="outline"
              onClick={() => setShowCombineDialog(false)}
              disabled={isCombining}
              className="min-w-[100px]"
            >
              Cancel
            </Button>
            <Button
              onClick={handleCombineSubmit}
              disabled={isCombining}
              className="min-w-[180px] bg-blue-600 hover:bg-blue-700"
            >
              {isCombining ? 'Creating...' : 'Create Combined Order'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
