import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Clock, User, Phone, CreditCard, Hash, Calendar, TrendingUp, MessageSquare, FileText, Package, Search, CheckCircle, XCircle, AlertCircle, Scan, Layers, Undo2, UserPlus } from 'lucide-react';
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
import CombinedOrderDetailsView from './CombinedOrderDetailsView';
import type { ParsedBarcode } from '@/utils/barcodeParser';
import {
  scanBarcode,
  completeIssuance,
  cancelIssuance,
  getCurrentIssuance,
  getProducts,
  cancelFulfilledTransaction,
  cancelRegistrationOrder,
  deleteTransaction,
  markTransactionAsRegistration,
  revertToProcessing,
  type CurrentIssuance,
  type Product,
} from '@/services/api';
import { useAuth } from '@/contexts/AuthContext';
import { Textarea } from '@/components/ui/textarea';
import { AddToCombinedOrderDialog } from './AddToCombinedOrderDialog';
import { IssueRegistrationKitDialog } from './IssueRegistrationKitDialog';

interface TransactionDetailModalProps {
  transaction: Transaction | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate?: () => void;
  onViewParentTransaction?: (parentTransactionId: number | undefined, combinedOrderId?: string) => void;
}

export function TransactionDetailModal({
  transaction,
  open,
  onOpenChange,
  onUpdate,
  onViewParentTransaction,
}: TransactionDetailModalProps) {
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const [showStatusChange, setShowStatusChange] = useState(false);
  const [isFulfilling, setIsFulfilling] = useState(false);
  const [showCombinedOrder, setShowCombinedOrder] = useState(false);
  const [currentIssuance, setCurrentIssuance] = useState<CurrentIssuance | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [manualQuantity, setManualQuantity] = useState<string>('1');
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [isMarkingRegistration, setIsMarkingRegistration] = useState(false);
  const [showRevertDialog, setShowRevertDialog] = useState(false);
  const [revertReason, setRevertReason] = useState('');
  const [showAddTransactionsDialog, setShowAddTransactionsDialog] = useState(false);
  const [showIssueKitDialog, setShowIssueKitDialog] = useState(false);
  const [showCancelRegistrationDialog, setShowCancelRegistrationDialog] = useState(false);
  const [cancelRegistrationReason, setCancelRegistrationReason] = useState('');
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteReason, setDeleteReason] = useState('');

  // Clear messages when transaction changes or modal opens/closes
  useEffect(() => {
    // Always clear messages when transaction changes or modal state changes
    setError(null);
    setSuccess(null);
    if (open) {
      setDeleteReason('');
      setCancelReason('');
      setCancelRegistrationReason('');
      setRevertReason('');
    }
  }, [transaction?.id, open]);

  const isLocked = transaction?.is_locked || false;
  const canFulfill = transaction && !isLocked && ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED'].includes(transaction.status);
  const isFulfilled = transaction?.status === 'FULFILLED';
  const isAdmin = hasRole('ADMIN');
  const hasProcessorAccess = hasRole('ADMIN') || hasRole('PROCESSOR');
  const canMarkAsRegistration = hasProcessorAccess && transaction && !transaction.is_registration && ['NOT_PROCESSED', 'PROCESSING'].includes(transaction.status);

  // Helper to get display values for combined orders
  // For combined order parents (tx_id starts with CMB-), use combined_order_info values
  const getDisplayAmount = () => {
    if (transaction?.tx_id?.startsWith('CMB-') && transaction.combined_order_info) {
      return transaction.combined_order_info.total_amount;
    }
    return transaction?.amount || '0';
  };

  const getDisplayAmountFulfilled = () => {
    if (transaction?.tx_id?.startsWith('CMB-') && transaction.combined_order_info) {
      return transaction.combined_order_info.amount_fulfilled;
    }
    return transaction?.amount_fulfilled || '0';
  };

  const getDisplayRemainingAmount = () => {
    if (transaction?.tx_id?.startsWith('CMB-') && transaction.combined_order_info) {
      return transaction.combined_order_info.remaining_amount;
    }
    return transaction?.remaining_amount || '0';
  };

  const handleOpenScanner = () => {
    if (!transaction) return;

    // For registration transactions WITHOUT kit issued yet, show kit dialog
    if (transaction.is_registration && !transaction.registration_kit_issued) {
      setShowIssueKitDialog(true);
    } else {
      // For regular transactions OR registration with kit already issued, navigate to scanner
      onOpenChange(false); // Close modal
      navigate(`/transactions/${transaction.id}/scan`);
    }
  };

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

  // Removed - fulfillment now happens on scanning page
  // const handleStartFulfill = async () => {
  //   if (!transaction) return;
  //   try {
  //     setProcessing(true);
  //     setError(null);
  //     setSuccess(null);
  //     await activateIssuance(transaction.id);
  //     await checkCurrentIssuance();
  //     setIsFulfilling(true);
  //     setSuccess('Fulfillment mode activated. Start scanning products.');
  //   } catch (err: any) {
  //     const errorMsg = err.response?.data?.error
  //       ? Object.values(err.response.data.error).join(', ')
  //       : 'Failed to activate fulfillment';
  //     setError(errorMsg);
  //   } finally {
  //     setProcessing(false);
  //   }
  // };

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
    if (!transaction || !currentIssuance) return;

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
    if (!transaction || !currentIssuance) {
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

  const handleCancelFulfilledOrder = async () => {
    if (!transaction || !cancelReason.trim()) {
      setError('Please provide a reason for cancellation');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await cancelFulfilledTransaction(transaction.id, cancelReason);
      setSuccess(result.message || 'Order cancelled successfully. Transaction reset to NOT_PROCESSED.');
      setShowCancelDialog(false);
      setCancelReason('');

      // Wait a bit for backend to update, then refresh and close
      setTimeout(() => {
        onUpdate?.();
        onOpenChange(false);
      }, 2000);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to cancel fulfilled order';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleCancelRegistrationOrder = async () => {
    if (!transaction || !cancelRegistrationReason.trim()) {
      setError('Please provide a reason for cancellation');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await cancelRegistrationOrder(transaction.id, cancelRegistrationReason);
      setSuccess(result.message || 'Registration order cancelled successfully. Kit and products returned to inventory.');
      setShowCancelRegistrationDialog(false);
      setCancelRegistrationReason('');

      // Wait a bit for backend to update, then refresh and close
      setTimeout(() => {
        onUpdate?.();
        onOpenChange(false);
      }, 2000);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to cancel registration order';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleDeleteTransaction = async () => {
    if (!transaction || !deleteReason.trim()) {
      setError('Please provide a reason for deletion');
      return;
    }

    if (!confirm('⚠️ WARNING: This will PERMANENTLY delete this transaction. This action cannot be undone! Are you absolutely sure?')) {
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await deleteTransaction(transaction.id, deleteReason);
      setSuccess(result.message || 'Transaction permanently deleted.');
      setShowDeleteDialog(false);
      setDeleteReason('');

      // Wait a bit for user to see success, then close and refresh
      setTimeout(() => {
        setSuccess(null);  // Clear success message before closing to avoid persistence
        onUpdate?.();
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to delete transaction';
      setError(errorMsg);
    } finally {
      setProcessing(false);
    }
  };

  const handleMarkAsRegistration = async () => {
    if (!transaction) return;

    if (!confirm('Mark this transaction as a registration? Registration transactions automatically issue one Registration Kit during fulfillment (no scanning required).')) {
      return;
    }

    try {
      setIsMarkingRegistration(true);
      setError(null);
      setSuccess(null);

      const result = await markTransactionAsRegistration(transaction.id);
      setSuccess(result.message || 'Transaction marked as registration');

      // Refresh to show updated transaction
      setTimeout(() => {
        onUpdate?.();
      }, 1000);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to mark as registration';
      setError(errorMsg);
    } finally {
      setIsMarkingRegistration(false);
    }
  };

  const handleRevertToProcessing = async () => {
    if (!transaction || !revertReason.trim()) {
      setError('Please provide a reason for reverting');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await revertToProcessing(transaction.id, revertReason);
      setSuccess(result.message || 'Transaction reverted to PROCESSING');
      setShowRevertDialog(false);
      setRevertReason('');

      // Wait a bit for backend to update, then refresh and close
      setTimeout(() => {
        onUpdate?.();
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error
        ? (typeof err.response.data.error === 'object'
            ? Object.values(err.response.data.error).join(', ')
            : err.response.data.error)
        : 'Failed to revert transaction';
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

  // Calculate actual fulfilled amount from line items + registration kit
  const lineItemsTotal = transaction.line_items?.reduce(
    (sum: number, item: any) => sum + parseFloat(item.line_total || '0'),
    0
  ) || 0;
  const registrationKitAmount = transaction.is_registration && transaction.registration_kit_issued
    ? parseFloat(transaction.registration_kit_amount_deducted || '0')
    : 0;
  const actualFulfilledAmount = lineItemsTotal + registrationKitAmount;

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
              {/* Combined Order View */}
              {showCombinedOrder && transaction.combined_order_info ? (
                <CombinedOrderDetailsView
                  combinedOrderId={transaction.combined_order_info.combined_order_id}
                  onClose={() => setShowCombinedOrder(false)}
                  onUpdate={() => {
                    setShowCombinedOrder(false);
                    onUpdate?.();
                  }}
                />
              ) : (
                <>
                  {/* Status Badge and Actions */}
                  <div className="flex items-center justify-between">
                    <div className="flex gap-2 items-center">
                      <Badge
                        style={{ backgroundColor: getStatusColor(transaction.status) }}
                        className="text-white px-4 py-2 text-sm"
                      >
                        {getStatusLabel(transaction.status)}
                      </Badge>
                      {transaction.is_registration && (
                        <Badge className="bg-purple-600 text-white px-3 py-1 text-sm">
                          <UserPlus className="w-3 h-3 mr-1" />
                          Registration
                        </Badge>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {transaction.is_in_combined_order && transaction.combined_order_info ? (
                        <>
                          {/* For combined order child transactions, show "View Order" button */}
                          <Button
                            variant="default"
                            size="sm"
                            onClick={() => {
                              const parentId = transaction.combined_order_info?.parent_transaction_id;
                              const combinedOrderId = transaction.combined_order_info?.combined_order_id;
                              console.log('View Order clicked:', { parentId, combinedOrderId, hasCallback: !!onViewParentTransaction, combinedOrderInfo: transaction.combined_order_info });

                              // First, try to use the callback if provided (for navigation to parent transaction)
                              if (onViewParentTransaction) {
                                onViewParentTransaction(parentId, combinedOrderId);
                              } else {
                                // If no callback, show combined order details inline
                                console.log('No callback, showing combined order view inline');
                                setShowCombinedOrder(true);
                              }
                            }}
                            className="bg-purple-600 hover:bg-purple-700"
                          >
                            <Layers className="mr-2 h-4 w-4" />
                            View Order
                          </Button>
                        </>
                      ) : canFulfill ? (
                        // For all transactions (including combined order parents), show "Fulfill Order" or "Issue Registration Kit" button
                        <Button
                          variant="default"
                          size="sm"
                          onClick={handleOpenScanner}
                          className="bg-green-600 hover:bg-green-700"
                        >
                          <Scan className="mr-2 h-4 w-4" />
                          {transaction.is_registration && !transaction.registration_kit_issued ? 'Issue Registration Kit' : 'Fulfill Order'}
                        </Button>
                      ) : null}
                      {/* For combined order parents, show Add Transactions button instead of Change Status */}
                      {transaction.tx_id?.startsWith('CMB-') ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowAddTransactionsDialog(true)}
                          className="border-purple-300 text-purple-600 hover:bg-purple-50"
                        >
                          <Layers className="mr-2 h-4 w-4" />
                          Add Transactions
                        </Button>
                      ) : !isLocked && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowStatusChange(true)}
                        >
                          Change Status
                        </Button>
                      )}
                      {canMarkAsRegistration && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleMarkAsRegistration}
                          disabled={isMarkingRegistration}
                          className="border-purple-300 text-purple-600 hover:bg-purple-50"
                        >
                          <UserPlus className="mr-2 h-4 w-4" />
                          Mark as Registration
                        </Button>
                      )}
                      {transaction.status === 'PARTIALLY_FULFILLED' && !transaction.is_in_combined_order && hasProcessorAccess && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowRevertDialog(true)}
                          className="border-orange-300 text-orange-600 hover:bg-orange-50"
                        >
                          <Undo2 className="mr-2 h-4 w-4" />
                          Revert to Processing
                        </Button>
                      )}
                      {isFulfilled && isAdmin && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => setShowCancelDialog(true)}
                          className="bg-red-600 hover:bg-red-700"
                        >
                          <Undo2 className="mr-2 h-4 w-4" />
                          Cancel Order
                        </Button>
                      )}
                      {transaction.is_registration && transaction.registration_kit_issued && isAdmin && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => setShowCancelRegistrationDialog(true)}
                          className="bg-orange-600 hover:bg-orange-700"
                        >
                          <Undo2 className="mr-2 h-4 w-4" />
                          Cancel Registration
                        </Button>
                      )}
                      {transaction.status === 'NOT_PROCESSED' && isAdmin && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => setShowDeleteDialog(true)}
                          className="bg-red-800 hover:bg-red-900"
                        >
                          <XCircle className="mr-2 h-4 w-4" />
                          Delete Transaction
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Registration Transaction Info Card */}
                  {transaction.is_registration && (
                    <Alert className="bg-purple-50 border-purple-200 dark:bg-purple-900/20 dark:border-purple-800">
                      <UserPlus className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                      <AlertDescription>
                        <div>
                          <p className="font-semibold text-purple-900 dark:text-purple-100">
                            Registration Transaction - Special Handling
                          </p>
                          <p className="text-sm text-purple-700 dark:text-purple-300 mt-1">
                            This transaction will automatically issue <strong>one Registration Kit</strong> when completed.
                          </p>
                          <ul className="text-xs text-purple-600 dark:text-purple-400 mt-2 list-disc ml-5 space-y-1">
                            <li>No barcode scanning required</li>
                            <li>Registration Kit will be issued automatically</li>
                            <li>Inventory will be updated when order is completed</li>
                          </ul>
                        </div>
                      </AlertDescription>
                    </Alert>
                  )}

                  {/* Combined Order Info Card - Only for child transactions */}
                  {transaction.is_in_combined_order && transaction.combined_order_info && (
                    <Alert className="bg-purple-50 border-purple-200 dark:bg-purple-900/20 dark:border-purple-800">
                      <Layers className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                      <AlertDescription>
                        <div>
                          <p className="font-semibold text-purple-900 dark:text-purple-100">
                            Part of Combined Order {transaction.combined_order_info.combined_order_id}
                          </p>
                          <p className="text-sm text-purple-700 dark:text-purple-300 mt-1">
                            {transaction.combined_order_info.transaction_count} transactions combined |
                            Total: KES {transaction.combined_order_info.total_amount} |
                            Fulfilled: KES {transaction.combined_order_info.amount_fulfilled}
                          </p>
                          <p className="text-xs text-purple-600 dark:text-purple-400 mt-2">
                            Click "View Order" above to view details, add more transactions, and fulfill this combined order
                          </p>
                        </div>
                      </AlertDescription>
                    </Alert>
                  )}

                  {/* Fulfillment Mode */}
              {isFulfilling ? (
                <>
                  {/* Order Summary */}
                  <div className="grid grid-cols-3 gap-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
                    <div>
                      <Label className="text-sm text-gray-600 dark:text-gray-400">Transaction Amount</Label>
                      <p className="text-xl font-bold">{formatCurrency(getDisplayAmount())}</p>
                    </div>
                    <div>
                      <Label className="text-sm text-gray-600 dark:text-gray-400">Fulfilled</Label>
                      <p className="text-xl font-bold text-green-600">
                        {formatCurrency(currentIssuance?.amount_fulfilled || getDisplayAmountFulfilled())}
                      </p>
                    </div>
                    <div>
                      <Label className="text-sm text-gray-600 dark:text-gray-400">Remaining</Label>
                      <p className="text-xl font-bold text-orange-600">
                        {formatCurrency(currentIssuance?.remaining_amount || getDisplayRemainingAmount())}
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
                  {((transaction.line_items && transaction.line_items.length > 0) || (transaction.is_registration && transaction.registration_kit_issued)) && (
                    <div className="mb-6">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
                          <Package className="h-5 w-5 text-green-600" />
                          Fulfilled Items ({transaction.line_items?.length || 0}{transaction.is_registration && transaction.registration_kit_issued ? ' + Kit' : ''})
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
                            {/* Show Registration Kit as first item if issued */}
                            {transaction.is_registration && transaction.registration_kit_issued && (
                              <TableRow className="bg-blue-50 dark:bg-blue-900/20">
                                <TableCell>
                                  <div>
                                    <div className="font-medium text-gray-900 dark:text-gray-100 flex items-center gap-2">
                                      <Badge variant="outline" className="bg-blue-100 dark:bg-blue-900 border-blue-300 dark:border-blue-700">
                                        Registration Kit
                                      </Badge>
                                    </div>
                                    <div className="text-sm text-gray-500 dark:text-gray-400">
                                      Issued registration kit
                                    </div>
                                  </div>
                                </TableCell>
                                <TableCell className="text-right">
                                  <Badge variant="outline" className="font-semibold">
                                    {transaction.registration_kit_quantity || 1}
                                  </Badge>
                                </TableCell>
                                <TableCell className="text-right font-medium">
                                  {formatCurrency(parseFloat(transaction.registration_kit_amount_deducted || '0') / (transaction.registration_kit_quantity || 1))}
                                </TableCell>
                                <TableCell className="text-right font-bold text-blue-600 dark:text-blue-400">
                                  {formatCurrency(parseFloat(transaction.registration_kit_amount_deducted || '0'))}
                                </TableCell>
                                <TableCell className="text-right text-sm text-gray-600 dark:text-gray-400">
                                  Issued
                                </TableCell>
                              </TableRow>
                            )}

                            {/* Show scanned products */}
                            {transaction.line_items?.map((item: any) => (
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
                      {actualFulfilledAmount < parseFloat(getDisplayAmount()) && (
                        <div className="mt-3 p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-md">
                          <div className="flex items-center gap-2 text-orange-800 dark:text-orange-200">
                            <AlertCircle className="h-5 w-5" />
                            <div>
                              <div className="font-semibold">
                                Remaining for Products: {formatCurrency(parseFloat(getDisplayAmount()) - actualFulfilledAmount)} of {formatCurrency(getDisplayAmount())}
                              </div>
                              {transaction.is_registration && transaction.registration_kit_issued && (
                                <div className="text-sm mt-1">
                                  (Registration Kit {formatCurrency(registrationKitAmount)} +
                                  Products {formatCurrency(lineItemsTotal)})
                                </div>
                              )}
                            </div>
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
                      {formatCurrency(getDisplayAmount())}
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
                      {formatCurrency(getDisplayRemainingAmount())}
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

              {/* Activity Log */}
              {transaction.activity_log && transaction.activity_log.length > 0 && (
                <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mb-3">
                    <Clock className="h-4 w-4" />
                    Activity Log
                  </Label>
                  <div className="space-y-2">
                    {transaction.activity_log.map((entry, idx) => (
                      <div key={idx} className="flex gap-3 text-sm p-3 bg-gray-50 dark:bg-slate-700 rounded">
                        <div className="font-mono text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
                          {formatDate(entry.timestamp)}
                        </div>
                        <div className="flex-1">
                          <div className="font-semibold text-gray-900 dark:text-gray-100">{entry.action}</div>
                          <div className="text-gray-600 dark:text-gray-300">
                            by <span className="font-medium">{entry.user}</span> ({entry.role})
                          </div>
                          <div className="text-gray-500 dark:text-gray-400 text-xs mt-1">{entry.details}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
                </>
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

      {/* Cancel Fulfilled Order Dialog */}
      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Cancel Fulfilled Order</DialogTitle>
            <DialogDescription>
              This will cancel the order and return all products to inventory.
              The transaction will be reset to NOT_PROCESSED and can be fulfilled again.
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-4">
              <Alert className="bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800">
                <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
                <AlertDescription className="text-yellow-800 dark:text-yellow-200">
                  <strong>Warning:</strong> This action will:
                  <ul className="list-disc ml-5 mt-2 space-y-1">
                    <li>Return all fulfilled products to inventory</li>
                    <li>Reset transaction status to NOT_PROCESSED</li>
                    <li>Allow the order to be fulfilled again</li>
                    <li>Record the cancellation in transaction notes</li>
                  </ul>
                </AlertDescription>
              </Alert>

              <div>
                <Label htmlFor="cancel-reason" className="mb-2 block">
                  Reason for Cancellation *
                </Label>
                <Textarea
                  id="cancel-reason"
                  placeholder="Enter reason (e.g., Customer refund, Wrong items issued, etc.)"
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  This reason will be recorded in the transaction notes for audit purposes.
                </p>
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setShowCancelDialog(false);
                  setCancelReason('');
                  setError(null);
                }}
                disabled={processing}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleCancelFulfilledOrder}
                disabled={processing || !cancelReason.trim()}
                className="flex-1 bg-red-600 hover:bg-red-700"
              >
                {processing ? 'Processing...' : 'Confirm Cancellation'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel Registration Order Dialog */}
      <Dialog open={showCancelRegistrationDialog} onOpenChange={setShowCancelRegistrationDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Cancel Registration Order</DialogTitle>
            <DialogDescription>
              This will cancel the registration order and return both the registration kit and all fulfilled products to inventory.
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-4">
              <Alert className="bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800">
                <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
                <AlertDescription className="text-yellow-800 dark:text-yellow-200">
                  <strong>Warning:</strong> This action will:
                  <ul className="list-disc ml-5 mt-2 space-y-1">
                    <li>Return registration kit(s) to inventory</li>
                    <li>Return all fulfilled products to inventory</li>
                    <li>Reset transaction status to NOT_PROCESSED</li>
                    <li>Clear registration kit issuance</li>
                    <li>Record the cancellation in transaction notes</li>
                  </ul>
                </AlertDescription>
              </Alert>

              <div>
                <Label htmlFor="cancel-reg-reason" className="mb-2 block">
                  Reason for Cancellation *
                </Label>
                <Textarea
                  id="cancel-reg-reason"
                  placeholder="Enter reason (e.g., Customer refund, Registration error, etc.)"
                  value={cancelRegistrationReason}
                  onChange={(e) => setCancelRegistrationReason(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  This reason will be recorded in the transaction notes for audit purposes.
                </p>
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setShowCancelRegistrationDialog(false);
                  setCancelRegistrationReason('');
                  setError(null);
                }}
                disabled={processing}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleCancelRegistrationOrder}
                disabled={processing || !cancelRegistrationReason.trim()}
                className="flex-1 bg-orange-600 hover:bg-orange-700"
              >
                {processing ? 'Processing...' : 'Confirm Cancellation'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Transaction Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>⚠️ Delete Transaction</DialogTitle>
            <DialogDescription>
              This will PERMANENTLY delete this transaction from the system. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-4">
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <strong>DANGER:</strong> This action is irreversible!
                  <ul className="list-disc ml-5 mt-2 space-y-1">
                    <li>Transaction will be permanently removed</li>
                    <li>Cannot be recovered after deletion</li>
                    <li>Only use for duplicate/test transactions</li>
                    <li>For real transactions, use cancellation instead</li>
                  </ul>
                </AlertDescription>
              </Alert>

              <div>
                <Label htmlFor="delete-reason" className="mb-2 block">
                  Reason for Deletion *
                </Label>
                <Textarea
                  id="delete-reason"
                  placeholder="Enter reason (e.g., Duplicate transaction, Test data, etc.)"
                  value={deleteReason}
                  onChange={(e) => setDeleteReason(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  This deletion will be logged for audit purposes.
                </p>
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setShowDeleteDialog(false);
                  setDeleteReason('');
                  setError(null);
                }}
                disabled={processing}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleDeleteTransaction}
                disabled={processing || !deleteReason.trim()}
                className="flex-1 bg-red-800 hover:bg-red-900"
              >
                {processing ? 'Deleting...' : 'Permanently Delete'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Revert to Processing Dialog */}
      <Dialog open={showRevertDialog} onOpenChange={setShowRevertDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Revert to Processing</DialogTitle>
            <DialogDescription>
              Revert this partially fulfilled transaction back to processing status to add more items.
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-4">
              <Alert className="bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800">
                <AlertCircle className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                <AlertDescription className="text-blue-800 dark:text-blue-200">
                  <strong>This action will:</strong>
                  <ul className="list-disc ml-5 mt-2 space-y-1">
                    <li>Change transaction status back to PROCESSING</li>
                    <li>Allow you to scan additional products</li>
                    <li>Keep existing line items intact</li>
                    <li>Record the revert action in transaction notes</li>
                  </ul>
                </AlertDescription>
              </Alert>

              <div>
                <Label htmlFor="revert-reason" className="mb-2 block">
                  Reason for Reverting *
                </Label>
                <Textarea
                  id="revert-reason"
                  placeholder="Enter reason (e.g., Need to add more items, Customer requested changes, etc.)"
                  value={revertReason}
                  onChange={(e) => setRevertReason(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  This reason will be recorded in the transaction notes for audit purposes.
                </p>
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setShowRevertDialog(false);
                  setRevertReason('');
                  setError(null);
                }}
                disabled={processing}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="default"
                onClick={handleRevertToProcessing}
                disabled={processing || !revertReason.trim()}
                className="flex-1 bg-orange-600 hover:bg-orange-700"
              >
                {processing ? 'Processing...' : 'Confirm Revert'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Transactions to Combined Order Dialog */}
      {transaction && (transaction.is_in_combined_order && transaction.combined_order_info || transaction.tx_id?.startsWith('CMB-')) && (
        <AddToCombinedOrderDialog
          open={showAddTransactionsDialog}
          onOpenChange={setShowAddTransactionsDialog}
          combinedOrderId={transaction.combined_order_info?.combined_order_id || transaction.tx_id}
          combinedOrderStatus={transaction.combined_order_info?.status || transaction.status || 'PENDING'}
          onSuccess={async (updatedOrderData) => {
            console.log('[TransactionDetailModal] AddToCombinedOrderDialog onSuccess called with:', updatedOrderData);
            setSuccess('Transactions added to combined order successfully');
            setShowAddTransactionsDialog(false);

            // Trigger parent refresh which will refetch and update selectedTransaction
            console.log('[TransactionDetailModal] Calling onUpdate to refresh parent transaction...');
            await onUpdate?.();
            console.log('[TransactionDetailModal] onUpdate completed');
          }}
        />
      )}

      {/* Issue Registration Kit Dialog */}
      <IssueRegistrationKitDialog
        transaction={transaction}
        open={showIssueKitDialog}
        onOpenChange={setShowIssueKitDialog}
        onSuccess={() => {
          setSuccess('Registration kit issued successfully');
          onUpdate?.();
          setShowIssueKitDialog(false);
        }}
      />
    </>
  );
}
