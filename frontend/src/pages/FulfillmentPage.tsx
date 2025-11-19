import { useState, useEffect } from 'react';
import { Package, AlertCircle, CheckCircle, XCircle, Loader2, ShoppingCart } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Alert, AlertDescription } from '@/components/ui/alert';
import BarcodeScanner from '@/components/scanner/BarcodeScanner';
import {
  getTransactions,
  activateIssuance,
  scanBarcode,
  completeIssuance,
  cancelIssuance,
  getCurrentIssuance,
  formatCurrency,
  type Transaction,
  type CurrentIssuance,
} from '@/services/api';
import type { ParsedBarcode } from '@/utils/barcodeParser';

export default function FulfillmentPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [currentIssuance, setCurrentIssuance] = useState<CurrentIssuance | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Load unfulfilled transactions and check for current issuance
  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Load current issuance if any
      const issuance = await getCurrentIssuance();
      setCurrentIssuance(issuance);

      // Load unfulfilled transactions (get all and filter client-side for now)
      const txData = await getTransactions({
        page_size: 100,
      });

      // Filter for unfulfilled transactions
      const unfulfilled = (txData.results || []).filter((tx: Transaction) =>
        tx.status === 'NOT_PROCESSED' ||
        tx.status === 'PROCESSING' ||
        tx.status === 'PARTIALLY_FULFILLED'
      );
      setTransactions(unfulfilled);
    } catch (err) {
      console.error('Error loading data:', err);
      setError('Failed to load transactions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Activate issuance for a transaction
  const handleActivateIssuance = async (transactionId: number) => {
    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      await activateIssuance(transactionId);
      setSuccess('Transaction activated for fulfillment');

      // Reload to get current issuance
      await loadData();
    } catch (err: any) {
      console.error('Error activating issuance:', err);
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to activate transaction';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  // Handle barcode scan
  const handleBarcodeScan = async (barcode: ParsedBarcode) => {
    if (!currentIssuance) {
      setError('No transaction is currently active');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await scanBarcode(currentIssuance.transaction_id, {
        sku: barcode.sku,
        prod_code: barcode.prod_code,
        quantity: barcode.quantity,
        scanned_by: 'User',
      });

      setSuccess(`Added ${result.quantity}x ${result.product_name}`);

      // Reload to update current issuance
      await loadData();
    } catch (err: any) {
      console.error('Error scanning barcode:', err);
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to scan product';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  // Complete issuance
  const handleCompleteIssuance = async () => {
    if (!currentIssuance) return;

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      await completeIssuance(currentIssuance.transaction_id, 'User');
      setSuccess('Transaction completed successfully! Inventory updated.');

      // Reload
      await loadData();
    } catch (err: any) {
      console.error('Error completing issuance:', err);
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to complete transaction';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  // Cancel issuance
  const handleCancelIssuance = async () => {
    if (!currentIssuance) return;

    if (!confirm('Are you sure you want to cancel this transaction? All scanned items will be removed.')) {
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      await cancelIssuance(currentIssuance.transaction_id, 'User cancelled');
      setSuccess('Transaction cancelled');

      // Reload
      await loadData();
    } catch (err: any) {
      console.error('Error cancelling issuance:', err);
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to cancel transaction';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
        <span className="ml-2 text-gray-600">Loading...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">
          Transaction Fulfillment
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          Scan products to fulfill customer transactions
        </p>
      </div>

      {/* Alerts */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {success && (
        <Alert className="bg-green-50 border-green-200 text-green-800 dark:bg-green-900/20 dark:border-green-800 dark:text-green-200">
          <CheckCircle className="h-4 w-4" />
          <AlertDescription>{success}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left Column: Current Transaction */}
        <div className="space-y-6">
          {currentIssuance ? (
            <>
              {/* Current Transaction Card */}
              <Card className="border-blue-200 dark:border-blue-800">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        <ShoppingCart className="h-5 w-5 text-blue-600" />
                        Active Transaction: {currentIssuance.tx_id}
                      </CardTitle>
                      <CardDescription>
                        {currentIssuance.line_items_count} items scanned
                      </CardDescription>
                    </div>
                    <Badge className="bg-blue-600">Active</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        Transaction Amount
                      </div>
                      <div className="text-2xl font-bold">
                        {formatCurrency(currentIssuance.amount)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        Amount Fulfilled
                      </div>
                      <div className="text-2xl font-bold text-green-600">
                        {formatCurrency(currentIssuance.amount_fulfilled)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        Remaining
                      </div>
                      <div className="text-lg font-semibold text-orange-600">
                        {formatCurrency(currentIssuance.remaining_amount)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">Status</div>
                      <Badge variant="outline">{currentIssuance.status}</Badge>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex gap-2 pt-4 border-t">
                    <Button
                      onClick={handleCompleteIssuance}
                      disabled={processing || currentIssuance.line_items_count === 0}
                      className="flex-1 bg-green-600 hover:bg-green-700"
                    >
                      <CheckCircle className="mr-2 h-4 w-4" />
                      Complete & Update Inventory
                    </Button>
                    <Button
                      onClick={handleCancelIssuance}
                      disabled={processing}
                      variant="outline"
                      className="border-red-300 text-red-600 hover:bg-red-50"
                    >
                      <XCircle className="mr-2 h-4 w-4" />
                      Cancel
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Barcode Scanner */}
              <BarcodeScanner
                onScan={handleBarcodeScan}
                disabled={processing}
                autoFocus
              />

              {/* Scanned Items */}
              {currentIssuance.line_items && currentIssuance.line_items.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Scanned Items</CardTitle>
                    <CardDescription>
                      {currentIssuance.line_items_count} items in cart
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="rounded-md border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Product</TableHead>
                            <TableHead className="text-right">Qty</TableHead>
                            <TableHead className="text-right">Price</TableHead>
                            <TableHead className="text-right">Total</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {currentIssuance.line_items.map((item) => (
                            <TableRow key={item.id}>
                              <TableCell>
                                <div>
                                  <div className="font-medium">{item.product_name}</div>
                                  <div className="text-sm text-gray-500">
                                    {item.product_code}
                                  </div>
                                </div>
                              </TableCell>
                              <TableCell className="text-right font-semibold">
                                {item.quantity}
                              </TableCell>
                              <TableCell className="text-right">
                                {formatCurrency(item.unit_price)}
                              </TableCell>
                              <TableCell className="text-right font-semibold">
                                {formatCurrency(item.line_total)}
                              </TableCell>
                            </TableRow>
                          ))}
                          <TableRow className="bg-gray-50 dark:bg-gray-800 font-semibold">
                            <TableCell colSpan={3}>Total</TableCell>
                            <TableCell className="text-right text-lg">
                              {formatCurrency(currentIssuance.amount_fulfilled)}
                            </TableCell>
                          </TableRow>
                        </TableBody>
                      </Table>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>No Active Transaction</CardTitle>
                <CardDescription>
                  Select a transaction from the list to start fulfillment
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-center py-8 text-gray-500">
                  <Package className="h-12 w-12 mx-auto mb-4 text-gray-400" />
                  <p>Activate a transaction to begin scanning products</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right Column: Available Transactions */}
        <div>
          <Card>
            <CardHeader>
              <CardTitle>Pending Transactions</CardTitle>
              <CardDescription>
                {transactions.length} transactions awaiting fulfillment
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {transactions.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <CheckCircle className="h-12 w-12 mx-auto mb-4 text-gray-400" />
                    <p>No pending transactions</p>
                  </div>
                ) : (
                  transactions.slice(0, 10).map((tx) => (
                    <div
                      key={tx.id}
                      className={`p-4 rounded-lg border ${
                        currentIssuance?.transaction_id === tx.id
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-gray-200 dark:border-gray-700 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div>
                          <div className="font-semibold">{tx.tx_id}</div>
                          <div className="text-sm text-gray-600 dark:text-gray-400">
                            {tx.sender_name} • {tx.sender_phone}
                          </div>
                        </div>
                        <Badge variant="outline">{tx.status}</Badge>
                      </div>
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-sm text-gray-600 dark:text-gray-400">
                            Amount:
                          </span>
                          <span className="ml-2 font-semibold">
                            {formatCurrency(tx.amount)}
                          </span>
                        </div>
                        {currentIssuance?.transaction_id === tx.id ? (
                          <Badge className="bg-blue-600">Active</Badge>
                        ) : (
                          <Button
                            size="sm"
                            onClick={() => handleActivateIssuance(tx.id)}
                            disabled={processing || !!currentIssuance}
                          >
                            Activate
                          </Button>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
