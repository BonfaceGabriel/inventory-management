import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, TrendingUp } from 'lucide-react';
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
import { TransactionDetailModal } from '@/components/transactions/TransactionDetailModal';
import { StatusDropdown } from '@/components/transactions/StatusDropdown';
import { useDailyReport } from '@/services/queries/reports';
import { useTransactions } from '@/services/queries/transactions';
import { useWebSocketContext } from '@/contexts/WebSocketContext';
import { formatCurrency, formatDate } from '@/services/api';
import type { Transaction } from '@/types/transaction.types';

export default function DashboardPage() {
  const [recentOrders, setRecentOrders] = useState<Transaction[]>([]);
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const { data: report, isLoading: reportLoading, refetch: refetchReport } = useDailyReport();
  const { data: ordersData, refetch: refetchOrders } = useTransactions({});
  const { onTransactionCreated } = useWebSocketContext();

  // Load initial orders from API (last 7 only)
  useEffect(() => {
    if (ordersData?.results) {
      setRecentOrders(ordersData.results.slice(0, 7));
    }
  }, [ordersData]);

  // Listen for new transactions from WebSocket
  useEffect(() => {
    const cleanup = onTransactionCreated((newTransaction) => {
      console.log('📱 New transaction on Dashboard:', newTransaction.tx_id);

      // Refetch orders to get latest from API
      refetchOrders();

      // Refetch the daily report to update summary cards
      refetchReport();
    });

    return cleanup;
  }, [onTransactionCreated, refetchOrders, refetchReport]);

  const handleRowClick = (transaction: Transaction) => {
    setSelectedTransaction(transaction);
    setShowDetail(true);
  };

  const handleUpdateSuccess = () => {
    refetchOrders();
    refetchReport();
  };

  if (reportLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h1>
          <p className="text-gray-600 dark:text-gray-400">Overview of today's transactions</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-32" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h1>
        <p className="text-gray-600 dark:text-gray-400">Overview of today's transactions</p>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-blue-100 dark:border-blue-900 bg-gradient-to-br from-white to-blue-50 dark:from-slate-800 dark:to-blue-950">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-blue-900 dark:text-blue-100">Total Transactions</CardTitle>
            <TrendingUp className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">{report?.summary.total_transactions || 0}</div>
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

        <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-blue-100 dark:border-blue-900 bg-gradient-to-br from-white to-blue-50 dark:from-slate-800 dark:to-blue-950">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-blue-900 dark:text-blue-100">To Parent</CardTitle>
            <TrendingUp className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">
              {formatCurrency(report?.summary.total_to_parent || '0')}
            </div>
            <p className="text-xs text-blue-600 dark:text-blue-400">Settlement amount</p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-blue-100 dark:border-blue-900 bg-gradient-to-br from-white to-blue-50 dark:from-slate-800 dark:to-blue-950">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-blue-900 dark:text-blue-100">To Shop</CardTitle>
            <TrendingUp className="h-4 w-4 text-blue-600 dark:text-blue-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">
              {formatCurrency(report?.summary.total_to_shop || '0')}
            </div>
            <p className="text-xs text-blue-600 dark:text-blue-400">Shop earnings</p>
          </CardContent>
        </Card>
      </div>

      {/* Recent Orders */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Recent Orders</CardTitle>
              <CardDescription>Latest orders received</CardDescription>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link to="/transactions">
                View All <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {recentOrders.length === 0 ? (
            <p className="text-center text-sm text-gray-600 dark:text-gray-400 py-8">
              No orders yet. Waiting for payments...
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>TX ID</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Sender</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Gateway</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentOrders.map((tx) => (
                  <TableRow
                    key={tx.id}
                    onClick={() => handleRowClick(tx)}
                    className="cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700"
                  >
                    <TableCell className="font-medium">{tx.tx_id}</TableCell>
                    <TableCell className="font-bold">{formatCurrency(tx.amount)}</TableCell>
                    <TableCell>{tx.sender_name}</TableCell>
                    <TableCell>{tx.sender_phone}</TableCell>
                    <TableCell className="text-sm">
                      {tx.gateway_name || tx.gateway_type || 'N/A'}
                    </TableCell>
                    <TableCell>
                      <StatusDropdown transaction={tx} onUpdate={handleUpdateSuccess} />
                    </TableCell>
                    <TableCell>{formatDate(tx.timestamp)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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
