import { useState, useEffect } from 'react';
import { Clock, User, Phone, CreditCard, Hash, Calendar, TrendingUp, MessageSquare, FileText, Package, Search, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
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
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { formatCurrency, formatDate, getStatusColor, getStatusLabel } from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { StatusChangeDialog } from './StatusChangeDialog';
import BarcodeScanner from '@/components/scanner/BarcodeScanner';
import type { ParsedBarcode } from '@/utils/barcodeParser';
import {
  activateIssuance,
  scanBarcode,
  completeIssuance,
  cancelIssuance,
  getCurrentIssuance,
  getProducts,
  type CurrentIssuance,
  type Product,
} from '@/services/api';

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
  const [isFulfilling, setIsFulfilling] = useState(false);
  const [currentIssuance, setCurrentIssuance] = useState<CurrentIssuance | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [manualQuantity, setManualQuantity] = useState<string>('1');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isLocked = transaction?.is_locked || false;
  const canFulfill = transaction && !isLocked && ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED'].includes(transaction.status);

  // Load products when in fulfill mode
  useEffect(() => {
    if (isFulfilling && open && transaction) {
      loadProducts();
      checkCurrentIssuance();
    }
  }, [isFulfilling, open, transaction]);

  const loadProducts = async () => {
    try {
      const productsData = await getProducts({ is_active: true });
      const productsList = Array.isArray(productsData) ? productsData : (productsData as any).results || [];
      setProducts(productsList);
    } catch (err) {
      console.error('Error loading products:', err);
    }
  };

  const checkCurrentIssuance = async () => {
    if (!transaction) return;
    try {
      const issuance = await getCurrentIssuance();
      if (issuance && issuance.transaction_id === transaction.id) {
        setCurrentIssuance(issuance);
      }
    } catch (err) {
      console.error('Error checking issuance:', err);
    }
  };

  const handleStartFulfill = async () => {
    if (!transaction) return;
    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      await activateIssuance(transaction.id);
      await checkCurrentIssuance();
      setIsFulfilling(true);
      setSuccess('Fulfillment mode activated. Start scanning products.');
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to activate fulfillment';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleBarcodeScan = async (barcode: ParsedBarcode) => {
    if (!transaction || !currentIssuance) {
      setError('No active fulfillment session');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await scanBarcode(transaction.id, {
        sku: barcode.sku,
        prod_code: barcode.prod_code,
        quantity: barcode.quantity,
        scanned_by: 'User',
      });

      setSuccess(`Added ${result.quantity}x ${result.product_name}`);
      await checkCurrentIssuance();
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to scan product';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleManualProductAdd = async () => {
    if (!transaction || !currentIssuance || !selectedProduct) {
      setError('Please select a product first');
      return;
    }

    const quantity = parseInt(manualQuantity, 10);
    if (isNaN(quantity) || quantity <= 0) {
      setError('Please enter a valid quantity');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await scanBarcode(transaction.id, {
        sku: selectedProduct.sku,
        prod_code: selectedProduct.prod_code,
        quantity: quantity,
        scanned_by: 'User',
      });

      setSuccess(`Added ${result.quantity}x ${result.product_name}`);
      await checkCurrentIssuance();

      // Reset selection
      setSelectedProduct(null);
      setManualQuantity('1');
      setProductSearch('');
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to add product';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleComplete = async () => {
    if (!currentIssuance) return;

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      await completeIssuance(transaction.id, 'User');
      setSuccess('Order completed! Inventory updated.');
      setIsFulfilling(false);
      setCurrentIssuance(null);

      // Wait a bit for backend to update, then refresh and close
      setTimeout(() => {
        onUpdate?.();
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to complete order';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleCancelFulfill = async () => {
    if (!currentIssuance) {
      setIsFulfilling(false);
      return;
    }

    if (!confirm('Cancel fulfillment? All scanned items will be removed.')) {
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      await cancelIssuance(transaction.id, 'User cancelled');
      setSuccess('Fulfillment cancelled');
      setIsFulfilling(false);
      setCurrentIssuance(null);
      onUpdate?.();
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? Object.values(err.response.data.error).join(', ')
        : 'Failed to cancel';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const filteredProducts = products.filter((product) => {
    if (!productSearch) return true;
    const search = productSearch.toLowerCase();
    return (
      product.prod_name.toLowerCase().includes(search) ||
      product.sku?.toLowerCase().includes(search) ||
      product.prod_code?.toLowerCase().includes(search)
    );
  });

  if (!transaction) return null;

  // Calculate actual fulfilled amount from line items
  const actualFulfilledAmount = transaction.line_items?.reduce(
    (sum: number, item: any) => sum + parseFloat(item.line_total || '0'),
    0
  ) || 0;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader onClose={() => onOpenChange(false)}>
            <DialogTitle>{isFulfilling ? 'Fulfill Order' : 'Order Details'}</DialogTitle>
            <DialogDescription>
              {isFulfilling ? 'Scan products to fulfill order' : `View and manage order #${transaction.tx_id}`}
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            {/* Alerts */}
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {success && (
              <Alert className="mb-4 bg-green-50 border-green-200 text-green-800 dark:bg-green-900/20 dark:border-green-800 dark:text-green-200">
                <CheckCircle className="h-4 w-4" />
                <AlertDescription>{success}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-6">
              {/* Status Badge and Actions */}
              <div className="flex items-center justify-between">
                <Badge
                  style={{ backgroundColor: getStatusColor(transaction.status) }}
                  className="text-white px-4 py-2 text-sm"
                >
                  {getStatusLabel(transaction.status)}
                </Badge>
                <div className="flex gap-2">
                  {canFulfill && !isFulfilling && (
                    <Button
                      variant="default"
                      size="sm"
                      onClick={handleStartFulfill}
                      disabled={processing}
                      className="bg-blue-600 hover:bg-blue-700"
                    >
                      <Package className="mr-2 h-4 w-4" />
                      Fulfill Order
                    </Button>
                  )}
                  {!isLocked && !isFulfilling && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setShowStatusChange(true)}
                    >
                      Change Status
                    </Button>
                  )}
                </div>
              </div>

              {/* Fulfillment Mode */}
              {isFulfilling ? (
                <>
                  {/* Order Summary */}
                  <div className="grid grid-cols-3 gap-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
                    <div>
                      <Label className="text-sm text-gray-600 dark:text-gray-400">Transaction Amount</Label>
                      <p className="text-xl font-bold">{formatCurrency(transaction.amount)}</p>
                    </div>
                    <div>
                      <Label className="text-sm text-gray-600 dark:text-gray-400">Fulfilled</Label>
                      <p className="text-xl font-bold text-green-600">
                        {formatCurrency(currentIssuance?.amount_fulfilled || '0')}
                      </p>
                    </div>
                    <div>
                      <Label className="text-sm text-gray-600 dark:text-gray-400">Remaining</Label>
                      <p className="text-xl font-bold text-orange-600">
                        {formatCurrency(currentIssuance?.remaining_amount || transaction.amount)}
                      </p>
                    </div>
                  </div>

                  {/* Barcode Scanner */}
                  <div className="border-t pt-4">
                    <Label className="mb-2 block">Scan Product Barcode</Label>
                    <BarcodeScanner
                      onScan={handleBarcodeScan}
                      disabled={processing}
                      autoFocus
                      placeholder="Scan or enter SKU (e.g., AP004E or AP004E*2)..."
                    />
                  </div>

                  {/* Product Search/Filter */}
                  <div>
                    <Label className="mb-2 block">Or Search Products Manually</Label>
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                      <Input
                        placeholder="Search by name, SKU, or code..."
                        value={productSearch}
                        onChange={(e) => setProductSearch(e.target.value)}
                        className="pl-10"
                      />
                    </div>

                    {/* Selected Product */}
                    {selectedProduct && (
                      <div className="mt-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md">
                        <div className="flex items-center justify-between mb-2">
                          <div>
                            <div className="font-semibold">{selectedProduct.prod_name}</div>
                            <div className="text-sm text-gray-600 dark:text-gray-400">
                              {selectedProduct.sku} • Stock: {selectedProduct.quantity} • {formatCurrency(selectedProduct.current_price)}
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedProduct(null);
                              setManualQuantity('1');
                            }}
                          >
                            <XCircle className="h-4 w-4" />
                          </Button>
                        </div>
                        <div className="flex gap-2">
                          <div className="flex-1">
                            <Label className="text-xs mb-1 block">Quantity</Label>
                            <Input
                              type="number"
                              min="1"
                              max={selectedProduct.quantity}
                              value={manualQuantity}
                              onChange={(e) => setManualQuantity(e.target.value)}
                              className="w-full"
                            />
                          </div>
                          <div className="flex items-end">
                            <Button
                              onClick={handleManualProductAdd}
                              disabled={processing}
                              className="bg-green-600 hover:bg-green-700"
                            >
                              Add to Order
                            </Button>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Product Search Results */}
                    {productSearch && !selectedProduct && (
                      <div className="mt-2 max-h-60 overflow-y-auto border rounded-md">
                        {filteredProducts.length === 0 ? (
                          <div className="p-4 text-center text-sm text-gray-500">
                            No products found
                          </div>
                        ) : (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>SKU</TableHead>
                                <TableHead>Product</TableHead>
                                <TableHead className="text-right">Stock</TableHead>
                                <TableHead className="text-right">Price</TableHead>
                                <TableHead></TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {filteredProducts.slice(0, 10).map((product) => (
                                <TableRow key={product.id} className="text-sm">
                                  <TableCell className="font-mono">{product.sku}</TableCell>
                                  <TableCell>{product.prod_name}</TableCell>
                                  <TableCell className="text-right">
                                    <Badge variant={product.quantity > 0 ? 'outline' : 'destructive'}>
                                      {product.quantity}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="text-right">{formatCurrency(product.current_price)}</TableCell>
                                  <TableCell>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => setSelectedProduct(product)}
                                      disabled={product.quantity === 0}
                                    >
                                      Select
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Scanned Products */}
                  {currentIssuance && currentIssuance.line_items && currentIssuance.line_items.length > 0 && (
                    <div className="border-t pt-4">
                      <Label className="mb-2 block flex items-center gap-2">
                        <Package className="h-4 w-4" />
                        Scanned Products ({currentIssuance.line_items_count} items)
                      </Label>
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
                                    <div className="text-sm text-gray-500">{item.product_code}</div>
                                  </div>
                                </TableCell>
                                <TableCell className="text-right font-semibold">{item.quantity}</TableCell>
                                <TableCell className="text-right">{formatCurrency(item.unit_price)}</TableCell>
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
                    </div>
                  )}
                </>
              ) : (
                <>
                  {/* Fulfilled Items Section */}
                  {transaction.line_items && transaction.line_items.length > 0 && (
                    <div className="mb-6">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
                          <Package className="h-5 w-5 text-green-600" />
                          Fulfilled Items ({transaction.line_items.length})
                        </h3>
                      </div>
                      <div className="rounded-lg border-2 border-green-200 dark:border-green-800 overflow-hidden">
                        <Table>
                          <TableHeader className="bg-green-50 dark:bg-green-900/20">
                            <TableRow>
                              <TableHead className="font-semibold">Product</TableHead>
                              <TableHead className="text-right font-semibold">Qty</TableHead>
                              <TableHead className="text-right font-semibold">Unit Price</TableHead>
                              <TableHead className="text-right font-semibold">Total</TableHead>
                              <TableHead className="text-right font-semibold">Scanned At</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {transaction.line_items.map((item: any) => (
                              <TableRow key={item.id} className="hover:bg-green-50 dark:hover:bg-green-900/10">
                                <TableCell>
                                  <div>
                                    <div className="font-medium text-gray-900 dark:text-gray-100">
                                      {item.product_name}
                                    </div>
                                    <div className="text-sm text-gray-500 dark:text-gray-400">
                                      {item.product_code} • {item.sku}
                                    </div>
                                  </div>
                                </TableCell>
                                <TableCell className="text-right">
                                  <Badge variant="outline" className="font-semibold">
                                    {item.quantity}
                                  </Badge>
                                </TableCell>
                                <TableCell className="text-right font-medium">
                                  {formatCurrency(item.unit_price)}
                                </TableCell>
                                <TableCell className="text-right font-bold text-green-600 dark:text-green-400">
                                  {formatCurrency(item.line_total)}
                                </TableCell>
                                <TableCell className="text-right text-sm text-gray-600 dark:text-gray-400">
                                  {item.scanned_at ? formatDate(item.scanned_at) : 'N/A'}
                                </TableCell>
                              </TableRow>
                            ))}
                            <TableRow className="bg-green-100 dark:bg-green-900/30 font-bold border-t-2 border-green-300 dark:border-green-700">
                              <TableCell colSpan={3} className="text-right text-lg">
                                Total Fulfilled:
                              </TableCell>
                              <TableCell className="text-right text-xl text-green-600 dark:text-green-400">
                                {formatCurrency(actualFulfilledAmount)}
                              </TableCell>
                              <TableCell></TableCell>
                            </TableRow>
                          </TableBody>
                        </Table>
                      </div>

                      {/* Remaining Amount Notice */}
                      {actualFulfilledAmount < parseFloat(transaction.amount) && (
                        <div className="mt-3 p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-md">
                          <div className="flex items-center gap-2 text-orange-800 dark:text-orange-200">
                            <AlertCircle className="h-5 w-5" />
                            <span className="font-semibold">
                              Remaining: {formatCurrency(parseFloat(transaction.amount) - actualFulfilledAmount)} of {formatCurrency(transaction.amount)}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

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
                </>
              )}
            </div>
          </DialogBody>

          <DialogFooter>
            {isFulfilling ? (
              <div className="flex gap-2 w-full">
                <Button
                  variant="outline"
                  onClick={handleCancelFulfill}
                  disabled={processing}
                  className="flex-1 border-red-300 text-red-600 hover:bg-red-50"
                >
                  <XCircle className="mr-2 h-4 w-4" />
                  Cancel Fulfillment
                </Button>
                <Button
                  onClick={handleComplete}
                  disabled={processing || !currentIssuance || currentIssuance.line_items_count === 0}
                  className="flex-1 bg-green-600 hover:bg-green-700"
                >
                  <CheckCircle className="mr-2 h-4 w-4" />
                  Complete Order
                </Button>
              </div>
            ) : (
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            )}
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
