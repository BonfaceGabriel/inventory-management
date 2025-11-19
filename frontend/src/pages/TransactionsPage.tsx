import { useState, useEffect } from 'react';
import { FileSpreadsheet, FileText } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Pagination } from '@/components/ui/pagination';
import { AdvancedFilters } from '@/components/transactions/AdvancedFilters';
import type { TransactionFilters } from '@/components/transactions/AdvancedFilters';
import { TransactionDetailModal } from '@/components/transactions/TransactionDetailModal';
import { StatusDropdown } from '@/components/transactions/StatusDropdown';
import { useTransactions } from '@/services/queries/transactions';
import { useWebSocketContext } from '@/contexts/WebSocketContext';
import { formatCurrency, formatDate, downloadTransactionsCSV, downloadTransactionsXLSX } from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { toast } from 'sonner';

export default function TransactionsPage() {
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [page, setPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [filters, setFilters] = useState<TransactionFilters>({});
  const [isExporting, setIsExporting] = useState(false);

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

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Orders</h1>
          <p className="text-gray-600 dark:text-gray-400">View and manage all M-Pesa orders</p>
        </div>
        <div className="flex gap-2">
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
                        onClick={() => handleRowClick(tx)}
                        className="cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700"
                      >
                        <TableCell className="font-medium">{tx.tx_id}</TableCell>
                        <TableCell className="font-bold">{formatCurrency(tx.amount)}</TableCell>
                        <TableCell className="text-green-600 dark:text-green-400 font-semibold">
                          {formatCurrency(tx.amount_fulfilled || tx.amount_paid || '0')}
                        </TableCell>
                        <TableCell className="font-semibold text-orange-600 dark:text-orange-400">
                          {formatCurrency(tx.remaining_amount || '0')}
                        </TableCell>
                        <TableCell>{tx.sender_name}</TableCell>
                        <TableCell>{tx.sender_phone}</TableCell>
                        <TableCell className="text-sm">
                          {tx.gateway_name || tx.gateway_type || 'N/A'}
                        </TableCell>
                        <TableCell>
                          <StatusDropdown transaction={tx} onUpdate={refetch} />
                        </TableCell>
                        <TableCell>{formatDate(tx.timestamp)}</TableCell>
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
    </div>
  );
}
