import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChatText as MessageSquare, FileText, Clock, WarningCircle as AlertCircle, ArrowsCounterClockwise as RotateCcw, SpinnerGap as Loader2, XCircle } from '@phosphor-icons/react';
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
import CombinedOrderDetailsView from './CombinedOrderDetailsView';
import {
  completeIssuance,
  cancelIssuance,
  getCurrentIssuance,
  getProducts,
  cancelFulfilledTransaction,
  cancelRegistrationOrder,
  deleteTransaction,
  markTransactionAsRegistration,
  markCombinedOrderAsRegistration,
  unmarkTransactionAsRegistration,
  revertToNotProcessed,
  issueRegistrationFromPartial,
  revertCombinedOrder,
  type CurrentIssuance,
  type Product,
} from '@/services/api';
import { useAuth } from '@/contexts/AuthContext';
import { Textarea } from '@/components/ui/textarea';
import { AddToCombinedOrderDialog } from './AddToCombinedOrderDialog';
import { IssueRegistrationKitDialog } from './IssueRegistrationKitDialog';
import { toast } from 'sonner';
import { extractApiError } from '@/lib/error-utils';

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
  const [productSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [isMarkingRegistration, setIsMarkingRegistration] = useState(false);
  const [isUnmarkingRegistration, setIsUnmarkingRegistration] = useState(false);
  const [showAddTransactionsDialog, setShowAddTransactionsDialog] = useState(false);
  const [showIssueKitDialog, setShowIssueKitDialog] = useState(false);
  const [showCancelRegistrationDialog, setShowCancelRegistrationDialog] = useState(false);
  const [cancelRegistrationReason, setCancelRegistrationReason] = useState('');
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteReason, setDeleteReason] = useState('');

  // New states for F1/F2 fixes
  const [showRevertNotProcessedDialog, setShowRevertNotProcessedDialog] = useState(false);
  const [revertNotProcessedReason, setRevertNotProcessedReason] = useState('');
  const [isIssuingRegistrationFromPartial, setIsIssuingRegistrationFromPartial] = useState(false);

  // Revert Combined Order states
  const [showRevertCombinedOrderDialog, setShowRevertCombinedOrderDialog] = useState(false);
  const [revertCombinedOrderReason, setRevertCombinedOrderReason] = useState('');

  // Clear messages when transaction changes or modal opens/closes
  useEffect(() => {
    // Always clear messages when transaction changes or modal state changes
    setError(null);
    setSuccess(null);
    if (open) {
      setDeleteReason('');
      setCancelReason('');
      setCancelRegistrationReason('');
      setCancelRegistrationReason('');
      setRevertNotProcessedReason('');
    }
  }, [transaction?.id, open]);

  const isLocked = transaction?.is_locked || false;
  const canFulfill = transaction && !isLocked && ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED'].includes(transaction.status);
  const isFulfilled = transaction?.status === 'FULFILLED';
  const isAdmin = hasRole('ADMIN');
  const hasProcessorAccess = hasRole('ADMIN') || hasRole('PROCESSOR');
  const isCombinedOrderParent = transaction?.tx_id?.startsWith('CMB-');
  const isMerchandiseTransaction =
    transaction?.gateway_type === 'MERCH' ||
    transaction?.gateway_name?.toLowerCase().includes('merchandise');
  // For combined orders: allow marking as registration when partially fulfilled
  // For regular transactions: exclude partially fulfilled (use "Issue Reg (Partial)" instead)
  const canMarkAsRegistration = hasProcessorAccess && transaction && !transaction.is_registration && (
    isCombinedOrderParent
      ? ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED'].includes(transaction.status)
      : ['NOT_PROCESSED', 'PROCESSING'].includes(transaction.status)
  );

  // Helper to get display values for combined orders
  // For combined order parents (tx_id starts with CMB-), use combined_order_info values
  const getDisplayAmount = () => {
    if (transaction?.tx_id?.startsWith('CMB-') && transaction.combined_order_info) {
      return transaction.combined_order_info.total_amount;
    }
    return transaction?.amount || '0';
  };

  const getDisplayRemainingAmount = () => {
    if (transaction?.tx_id?.startsWith('CMB-') && transaction.combined_order_info) {
      return transaction.combined_order_info.remaining_amount;
    }
    return transaction?.remaining_amount || '0';
  };

  const handleOpenScanner = () => {
    if (!transaction) return;

    if (isMerchandiseTransaction) {
      onOpenChange(false);
      navigate(`/transactions/${transaction.id}/merchandise-fulfill`);
      return;
    }

    // For registration transactions WITHOUT kit issued yet, show kit dialog
    if (transaction.is_registration && !transaction.registration_kit_issued) {
      setShowIssueKitDialog(true);
    } else {
      // Close modal first
      onOpenChange(false);
      
      // Both regular and combined orders now use the same polymorphic ScanningPage
      if (transaction.tx_id?.startsWith('CMB-')) {
        // Route to unified scanning page using the tx_id (which is the combined_order_id)
        navigate(`/transactions/${transaction.tx_id}/scan`);
      } else {
        // For regular transactions, navigate to regular scanner
        navigate(`/transactions/${transaction.id}/scan`);
      }
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
      setError(extractApiError(err, 'Failed to complete order'));
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
      setError(extractApiError(err, 'Failed to cancel'));
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
      setError(extractApiError(err, 'Failed to cancel fulfilled order'));
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
      setError(extractApiError(err, 'Failed to cancel registration order'));
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
      setError(extractApiError(err, 'Failed to delete transaction'));
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

      // For combined orders (TX_ID starts with CMB-), use the combined order API
      let result;
      if (transaction.tx_id?.startsWith('CMB-')) {
        result = await markCombinedOrderAsRegistration(transaction.tx_id);
      } else {
        result = await markTransactionAsRegistration(transaction.id);
      }

      setSuccess(result.message || 'Transaction marked as registration');

      // Refresh to show updated transaction
      setTimeout(() => {
        onUpdate?.();
      }, 1000);
    } catch (err: any) {
      setError(extractApiError(err, 'Failed to mark as registration'));
    } finally {
      setIsMarkingRegistration(false);
    }
  };

  const handleUnmarkRegistration = async () => {
    if (!transaction) return;

    if (!confirm('Remove the registration flag from this transaction? It will be reset to NOT_PROCESSED. Only do this if no kit has been issued yet.')) {
      return;
    }

    try {
      setIsUnmarkingRegistration(true);
      setError(null);
      setSuccess(null);

      const result = await unmarkTransactionAsRegistration(transaction.id);
      setSuccess(result.message || 'Registration flag removed. Transaction reset to NOT_PROCESSED.');

      setTimeout(() => {
        onUpdate?.();
      }, 1000);
    } catch (err: any) {
      setError(extractApiError(err, 'Failed to unmark registration'));
    } finally {
      setIsUnmarkingRegistration(false);
    }
  };

  const handleRevertToNotProcessed = async () => {
    if (!transaction || !revertNotProcessedReason.trim()) {
      setError('Please provide a reason for reverting');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setSuccess(null);

      const result = await revertToNotProcessed(transaction.id, revertNotProcessedReason);
      setSuccess(result.message || 'Transaction reverted to NOT_PROCESSED');
      setShowRevertNotProcessedDialog(false);
      setRevertNotProcessedReason('');

      // Wait a bit for backend to update, then refresh and close
      setTimeout(() => {
        onUpdate?.();
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      setError(extractApiError(err, 'Failed to revert transaction'));
    } finally {
      setProcessing(false);
    }
  };

  const handleRevertCombinedOrder = async () => {
    if (!transaction || !revertCombinedOrderReason.trim()) {
      toast.error('Please provide a reason for reverting');
      return;
    }

    try {
      setProcessing(true);
      const result = await revertCombinedOrder(
        transaction.tx_id,
        revertCombinedOrderReason,
        'user'
      );
      toast.success(result.message || 'Combined order reverted successfully');
      setShowRevertCombinedOrderDialog(false);
      setRevertCombinedOrderReason('');
      onUpdate?.();
      onOpenChange(false); // Close modal since order is deleted
    } catch (err: any) {
      toast.error(extractApiError(err, 'Failed to revert combined order'));
    } finally {
      setProcessing(false);
    }
  };

  const handleIssueRegistrationFromPartial = async () => {
    if (!transaction) return;

    if (!confirm('Convert this partially fulfilled transaction to a Registration? This will issue a kit and consume the fulfilled amount.')) {
      return;
    }

    try {
      setIsIssuingRegistrationFromPartial(true);
      setError(null);
      setSuccess(null);

      const result = await issueRegistrationFromPartial(transaction.id);
      setSuccess(result.message || 'Registration issued successfully from partial transaction');

      // Refresh to show updated transaction
      setTimeout(() => {
        onUpdate?.();
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      setError(extractApiError(err, 'Failed to issue registration'));
    } finally {
      setIsIssuingRegistrationFromPartial(false);
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
  // Filter out REG_KIT_001 from line items total if registration kit is separately tracked
  const lineItemsTotal = transaction.line_items?.filter((item: any) =>
    !(transaction.is_registration && transaction.registration_kit_issued && item.product_code === 'REG_KIT_001')
  ).reduce(
    (sum: number, item: any) => sum + parseFloat(item.line_total || '0'),
    0
  ) || 0;
  const registrationKitAmount = transaction.is_registration && transaction.registration_kit_issued
    ? parseFloat(transaction.registration_kit_amount_deducted || '0')
    : 0;
  const actualFulfilledAmount = lineItemsTotal + registrationKitAmount;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange} fullScreen>
        <DialogContent fullScreen>
          <DialogHeader onClose={() => onOpenChange(false)} className="bg-[rgb(var(--color-card))]/80 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <DialogTitle className="shrink-0">{isFulfilling ? 'Fulfill Order' : 'Order Details'}</DialogTitle>
              {!isFulfilling && (
                <Badge
                  style={{ backgroundColor: getStatusColor(transaction.status) }}
                  className="text-white px-3 py-1 text-xs shrink-0"
                >
                  {getStatusLabel(transaction.status)}
                </Badge>
              )}
            </div>
            <DialogDescription>
              {isFulfilling ? 'Scan products to fulfill order' : `#${transaction.tx_id}`}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="flex-1 min-h-0 overflow-y-auto">
            <div className="mx-auto w-full max-w-5xl">
            {/* Alerts */}
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {success && (
              <Alert className="mb-4 bg-[rgb(var(--color-secondary))/0.1] border-[rgb(var(--color-secondary))/0.3] text-[rgb(var(--color-secondary))]">
                <AlertDescription>{success}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-6">
              {/* Combined Order View */}
              {showCombinedOrder && (transaction.combined_order_info || transaction.tx_id?.startsWith('CMB-')) ? (
                <CombinedOrderDetailsView
                  combinedOrderId={transaction.combined_order_info?.combined_order_id || transaction.tx_id}
                  onClose={() => setShowCombinedOrder(false)}
                  onUpdate={() => {
                    setShowCombinedOrder(false);
                    onUpdate?.();
                  }}
                />
              ) : (
                <>
                  {/* Status Badge and Actions */}
                  <div className="space-y-4 rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/70 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        style={{ backgroundColor: getStatusColor(transaction.status) }}
                        className="text-white px-4 py-2 text-sm"
                      >
                        {getStatusLabel(transaction.status)}
                      </Badge>
                      {transaction.is_registration && (
                        <Badge className="bg-[rgb(var(--color-secondary))] text-[rgb(var(--color-secondary-foreground))] px-3 py-1 text-sm">
                          Registration
                        </Badge>
                      )}
                      {['PROCESSING', 'PARTIALLY_FULFILLED'].includes(transaction.status) && hasProcessorAccess && !transaction.is_in_combined_order && (
                        <button
                          title="Revert to Not Processed"
                          onClick={() => setShowRevertNotProcessedDialog(true)}
                          className="rounded-lg border border-[rgb(var(--color-destructive))/0.3] px-2 py-1 text-xs font-medium text-red-600 hover:bg-[rgb(var(--color-destructive))/0.1] dark:border-red-700 dark:hover:bg-red-950/30"
                        >
                          Revert
                        </button>
                      )}
                    </div>

                    {/* Action Buttons - Different layout for combined orders vs regular transactions */}
                    {transaction.tx_id?.startsWith('CMB-') ? (
                      /* Combined Order Actions - Cleaner layout */
                      <div className="flex flex-wrap gap-2">
                        {canFulfill && (
                          <Button
                            variant="default"
                            size="sm"
                            onClick={handleOpenScanner}
                            className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))/0.85]"
                          >
                            {transaction.is_registration && !transaction.registration_kit_issued
                              ? 'Issue Registration Kit'
                              : 'Fulfill Order'}
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowAddTransactionsDialog(true)}
                          className="border-[rgb(var(--color-secondary))]/40 text-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/10"
                        >
                          Add Transactions
                        </Button>
                        {canMarkAsRegistration && !isMerchandiseTransaction && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleMarkAsRegistration}
                            disabled={isMarkingRegistration}
                            className="border-[rgb(var(--color-secondary))]/40 text-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/10"
                          >
                            Mark as Registration
                          </Button>
                        )}
                        {/* Only show Revert Combined Order if not completed/cancelled and user is admin */}
                        {!['FULFILLED', 'CANCELLED'].includes(transaction.status) && isAdmin && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setShowRevertCombinedOrderDialog(true)}
                            className=""
                          >
                            Revert Order
                          </Button>
                        )}
                      </div>
                    ) : (
                      /* Regular Transaction Actions */
                      <div className="flex flex-wrap gap-2">
                        {transaction.is_in_combined_order && transaction.combined_order_info ? (
                          <Button
                            variant="default"
                            size="sm"
                            onClick={() => {
                              const parentId = transaction.combined_order_info?.parent_transaction_id;
                              const combinedOrderId = transaction.combined_order_info?.combined_order_id;
                              if (onViewParentTransaction) {
                                onViewParentTransaction(parentId, combinedOrderId);
                              } else {
                                setShowCombinedOrder(true);
                              }
                            }}
                            className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/90"
                          >
                            View Order
                          </Button>
                        ) : canFulfill ? (
                          <Button
                            variant="default"
                            size="sm"
                            onClick={handleOpenScanner}
                            className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))/0.85]"
                          >
                            {isMerchandiseTransaction
                              ? 'Fulfill Merchandise'
                              : transaction.is_registration && !transaction.registration_kit_issued
                                ? 'Issue Registration Kit'
                                : 'Fulfill Order'}
                          </Button>
                        ) : null}

                        {transaction.is_in_issuance && hasProcessorAccess && !transaction.tx_id?.startsWith('CMB-') && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={async () => {
                              if (!confirm('Cancel active issuance? All scanned items will be removed and the transaction will return to its previous state.')) return;
                              try {
                                setProcessing(true);
                                await cancelIssuance(transaction.id, 'Cancelled from order details');
                                toast.success('Issuance cancelled');
                                onUpdate?.();
                              } catch (err: any) {
                                toast.error(extractApiError(err, 'Failed to cancel issuance'));
                              } finally {
                                setProcessing(false);
                              }
                            }}
                            disabled={processing}
                            className=""
                          >
                            <XCircle className="h-4 w-4" /> Cancel Issuance
                          </Button>
                        )}

                        {canMarkAsRegistration && !isMerchandiseTransaction && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleMarkAsRegistration}
                            disabled={isMarkingRegistration}
                            className="border-[rgb(var(--color-secondary))]/40 text-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/10"
                          >
                            Mark as Registration
                          </Button>
                        )}

                        {(isFulfilled || transaction.status === 'PARTIALLY_FULFILLED') && isAdmin && !transaction.is_in_combined_order && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setShowCancelDialog(true)}
                            className="bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))/0.85]"
                          >
                            Cancel Order
                          </Button>
                        )}

                        {transaction.is_registration && transaction.registration_kit_issued && isAdmin && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setShowCancelRegistrationDialog(true)}
                            className="bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))/0.85]"
                          >
                            Cancel Registration
                          </Button>
                        )}

                        {transaction.is_registration && !transaction.registration_kit_issued && hasProcessorAccess && !transaction.tx_id?.startsWith('CMB-') && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleUnmarkRegistration}
                            disabled={isUnmarkingRegistration}
                            className="border-[rgb(var(--color-primary))/0.3] text-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-accent))] dark:border-orange-600 dark:text-orange-400 dark:hover:bg-orange-950"
                          >
                            {isUnmarkingRegistration ? 'Removing...' : 'Unmark Registration'}
                          </Button>
                        )}

                        {transaction.status === 'NOT_PROCESSED' && isAdmin && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setShowDeleteDialog(true)}
                            className="bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))/0.85]"
                          >
                            Delete Transaction
                          </Button>
                        )}

                        {transaction.status === 'PARTIALLY_FULFILLED' && !transaction.is_registration && hasProcessorAccess && !isMerchandiseTransaction && (
                          <Button
                              variant="default"
                              size="sm"
                              onClick={handleIssueRegistrationFromPartial}
                              disabled={isIssuingRegistrationFromPartial}
                              className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))/0.85]"
                            >
                              Add to Order
                            </Button>
                        )}
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
                      <Label className="mb-2 block">Scanned Products ({currentIssuance.line_items_count} items)</Label>
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
              )}
                <>
                  {/* Fulfilled Items Section */}
                  {((transaction.line_items && transaction.line_items.length > 0) || (transaction.is_registration && transaction.registration_kit_issued)) && (
                    <div className="mb-6">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                          Fulfilled Items ({(transaction.line_items?.filter((item: any) => !(transaction.is_registration && transaction.registration_kit_issued && item.product_code === 'REG_KIT_001')).length || 0)}{transaction.is_registration && transaction.registration_kit_issued ? ' + Kit' : ''})
                        </h3>
                      </div>
                      <div className="overflow-hidden rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85">
                        <Table>
                          <TableHeader className="bg-[rgb(var(--color-secondary))/0.1]">
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
                              <TableRow className="bg-[rgb(var(--color-accent))]/45">
                                <TableCell>
                                  <div>
                                    <div className="font-medium text-gray-900 dark:text-gray-100 flex items-center gap-2">
                                      <Badge variant="outline" className="bg-[rgb(var(--color-accent))] border-[rgb(var(--color-border))]">
                                        Registration Kit
                                      </Badge>
                                    </div>
                                    <div className="text-sm text-[rgb(var(--color-muted-foreground))]">
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
                                <TableCell className="text-right font-bold text-[rgb(var(--color-primary))]">
                                  {formatCurrency(parseFloat(transaction.registration_kit_amount_deducted || '0'))}
                                </TableCell>
                                <TableCell className="text-right text-sm text-[rgb(var(--color-muted-foreground))]">
                                  Issued
                                </TableCell>
                              </TableRow>
                            )}

                            {/* Show scanned products (filter out REG_KIT_001 if registration kit is already shown above) */}
                            {transaction.line_items?.filter((item: any) =>
                              !(transaction.is_registration && transaction.registration_kit_issued && item.product_code === 'REG_KIT_001')
                            ).map((item: any) => (
                              <TableRow key={item.id} className="hover:bg-[rgb(var(--color-secondary))/0.1]">
                                <TableCell>
                                  <div>
                                    <div className="font-medium text-gray-900 dark:text-gray-100">
                                      {item.product_name}
                                    </div>
                                    <div className="text-sm text-[rgb(var(--color-muted-foreground))]">
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
                                <TableCell className="text-right text-sm text-[rgb(var(--color-muted-foreground))]">
                                  {item.scanned_at ? formatDate(item.scanned_at) : 'N/A'}
                                </TableCell>
                              </TableRow>
                            ))}
                            <TableRow className="bg-[rgb(var(--color-secondary))/0.08] font-bold border-t-2 border-[rgb(var(--color-secondary))/0.3]">
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
                        <div className="mt-3 p-3 bg-[rgb(var(--color-accent))] dark:bg-orange-900/20 border border-[rgb(var(--color-primary))/0.3] rounded-xl">
                          <div className="text-[rgb(var(--color-foreground))]">
                            <div className="font-semibold text-[rgb(var(--color-foreground))]">
                              Remaining for Products: {formatCurrency(parseFloat(getDisplayAmount()) - actualFulfilledAmount)} of {formatCurrency(getDisplayAmount())}
                            </div>
                            {transaction.is_registration && transaction.registration_kit_issued && (
                              <div className="mt-1 text-sm text-[rgb(var(--color-muted-foreground))]">
                                (Registration Kit {formatCurrency(registrationKitAmount)} +
                                Products {formatCurrency(lineItemsTotal)})
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-1 gap-4 rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/65 p-4 md:grid-cols-3">
                    <div className="space-y-3 rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/75 p-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-[rgb(var(--color-muted-foreground))]">Transaction</p>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Transaction ID</Label>
                        <p className="mt-1 font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">{transaction.tx_id}</p>
                      </div>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Gateway</Label>
                        <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{transaction.gateway_name || transaction.gateway_type || 'N/A'}</p>
                      </div>
                    </div>
                    <div className="space-y-3 rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/75 p-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-[rgb(var(--color-muted-foreground))]">Customer</p>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Sender Name</Label>
                        <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{transaction.sender_name || 'N/A'}</p>
                      </div>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Phone Number</Label>
                        <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{transaction.sender_phone || 'N/A'}</p>
                      </div>
                    </div>
                    <div className="space-y-3 rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/75 p-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-[rgb(var(--color-muted-foreground))]">Amounts & Time</p>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Amount</Label>
                        <p className="mt-1 text-2xl font-bold text-[rgb(var(--color-primary))] dark:text-orange-500">{formatCurrency(getDisplayAmount())}</p>
                      </div>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Remaining Amount</Label>
                        <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{formatCurrency(getDisplayRemainingAmount())}</p>
                      </div>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Date & Time</Label>
                        <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{formatDate(transaction.timestamp)}</p>
                      </div>
                      <div>
                        <Label className="text-gray-600 dark:text-gray-400">Created</Label>
                        <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">{formatDate(transaction.created_at)}</p>
                      </div>
                    </div>
                  </div>

              {/* Notes Section */}
              {transaction.notes && (
                <div className="pt-4 border-t border-[rgb(var(--color-border))]">
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mb-2">
                    <FileText className="h-4 w-4" />
                    Notes
                  </Label>
                  <p className="text-sm text-gray-700 dark:text-gray-300 bg-[rgb(var(--color-card))]/75 p-3 rounded-xl border border-[rgb(var(--color-border))]">
                    {transaction.notes}
                  </p>
                </div>
              )}

              {/* Raw Messages */}
              {transaction.raw_messages && transaction.raw_messages.length > 0 && (
                <div className="pt-4 border-t border-[rgb(var(--color-border))]">
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mb-2">
                    <MessageSquare className="h-4 w-4" />
                    Original SMS Message{transaction.raw_messages.length > 1 ? 's' : ''}
                  </Label>
                  <div className="space-y-2">
                    {transaction.raw_messages.map((msg, idx) => (
                      <div
                        key={idx}
                        className="text-sm text-gray-700 dark:text-gray-300 bg-[rgb(var(--color-card))]/75 border border-[rgb(var(--color-border))] p-3 rounded-xl font-mono"
                      >
                        {msg.raw_text}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Manual Payments */}
              {transaction.manual_payments && transaction.manual_payments.length > 0 && (
                <div className="pt-4 border-t border-[rgb(var(--color-border))]">
                  <Label className="text-gray-600 dark:text-gray-400 mb-2">
                    Manual Payment Entries
                  </Label>
                  <div className="space-y-2">
                    {transaction.manual_payments.map((payment: any, idx: number) => (
                      <div
                        key={idx}
                        className="text-sm text-gray-700 dark:text-gray-300 bg-[rgb(var(--color-card))]/75 border border-[rgb(var(--color-border))] p-3 rounded-xl"
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
                <div className="pt-4 border-t border-[rgb(var(--color-border))]">
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mb-3">
                    <Clock className="h-4 w-4" />
                    Activity Log
                  </Label>
                  <div className="space-y-2">
                    {transaction.activity_log.map((entry, idx) => (
                      <div key={idx} className="flex gap-3 text-sm p-3 bg-[rgb(var(--color-card))]/75 border border-[rgb(var(--color-border))] rounded-xl">
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
            </div>
          </div>
          </DialogBody>

          <DialogFooter>
            {isFulfilling ? (
              <div className="flex gap-2 w-full">
                <Button
                  variant="outline"
                  onClick={handleCancelFulfill}
                  disabled={processing}
                  className="flex-1 border-[rgb(var(--color-destructive))/0.3] text-red-600 hover:bg-[rgb(var(--color-destructive))/0.1]"
                >
                  Cancel Fulfillment
                </Button>
                <Button
                  onClick={handleComplete}
                  disabled={processing || !currentIssuance || currentIssuance.line_items_count === 0}
                  className="flex-1 bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))/0.85]"
                >
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
              <Alert className="bg-[rgb(var(--color-accent))] border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800">
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
                className="flex-1 bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))/0.85]"
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
              <Alert className="bg-[rgb(var(--color-accent))] border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800">
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
                className="flex-1 bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))/0.85]"
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
                className="flex-1 bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))/0.85]"
              >
                {processing ? 'Deleting...' : 'Permanently Delete'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Revert to Not Processed Dialog */}
      <Dialog open={showRevertNotProcessedDialog} onOpenChange={setShowRevertNotProcessedDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Revert to Not Processed</DialogTitle>
            <DialogDescription>
              Revert this transaction completely back to not processed status.
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
              <Alert className="bg-[rgb(var(--color-destructive))/0.1] border-red-200 dark:bg-red-900/20 dark:border-red-800">
                <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
                <AlertDescription className="text-[rgb(var(--color-destructive))] dark:text-red-200">
                  <strong>Warning:</strong>
                  <ul className="list-disc ml-5 mt-2 space-y-1">
                    <li>This will reset the transaction to NOT_PROCESSED</li>
                    <li>Status will return to original payment receipt state</li>
                  </ul>
                </AlertDescription>
              </Alert>

              <div>
                <Label htmlFor="revert-not-processed-reason" className="mb-2 block">
                  Reason for Reverting *
                </Label>
                <Textarea
                  id="revert-not-processed-reason"
                  placeholder="Enter reason..."
                  value={revertNotProcessedReason}
                  onChange={(e) => setRevertNotProcessedReason(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setShowRevertNotProcessedDialog(false);
                  setRevertNotProcessedReason('');
                  setError(null);
                }}
                disabled={processing}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleRevertToNotProcessed}
                disabled={processing || !revertNotProcessedReason.trim()}
                className="flex-1"
              >
                {processing ? 'Processing...' : 'Confirm Reset'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Revert Combined Order Dialog */}
      <Dialog open={showRevertCombinedOrderDialog} onOpenChange={setShowRevertCombinedOrderDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Revert Combined Order?</DialogTitle>
            <DialogDescription>
              This will completely revert the combined order to pre-combination state.
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            <div className="space-y-4">
              <Alert className="bg-[rgb(var(--color-destructive))/0.1] border-red-200 dark:bg-red-900/20 dark:border-red-800">
                <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
                <AlertDescription className="text-[rgb(var(--color-destructive))] dark:text-red-200">
                  <strong>Warning:</strong> This action will:
                  <ul className="list-disc ml-5 mt-2 space-y-1">
                    <li>Restore all child transactions to their original status</li>
                    <li>Return all scanned products to inventory</li>
                    <li>Delete all line items</li>
                    <li>Delete the combined order entirely</li>
                  </ul>
                  <p className="mt-3 font-semibold">This action cannot be undone!</p>
                </AlertDescription>
              </Alert>

              <div>
                <Label htmlFor="revert-combined-order-reason" className="mb-2 block">
                  Reason for revert <span className="text-red-500">*</span>
                </Label>
                <Textarea
                  id="revert-combined-order-reason"
                  placeholder="Enter reason (required)"
                  value={revertCombinedOrderReason}
                  onChange={(e) => setRevertCombinedOrderReason(e.target.value)}
                  rows={3}
                  className="resize-none"
                />
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setShowRevertCombinedOrderDialog(false);
                  setRevertCombinedOrderReason('');
                }}
                disabled={processing}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleRevertCombinedOrder}
                disabled={processing || !revertCombinedOrderReason.trim()}
                className="flex-1 bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))/0.85]"
              >
                {processing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Reverting...
                  </>
                ) : (
                  <>
                    <RotateCcw className="mr-2 h-4 w-4" />
                    Revert Order
                  </>
                )}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Issue Registration Kit Dialog */}
      {transaction && (
        <IssueRegistrationKitDialog
          transaction={transaction}
          open={showIssueKitDialog}
          onOpenChange={setShowIssueKitDialog}
          onSuccess={() => onUpdate?.()}
        />
      )}

      {/* Add Transactions to Combined Order Dialog */}
      {transaction && (transaction.is_in_combined_order && transaction.combined_order_info || transaction.tx_id?.startsWith('CMB-')) && (
        <AddToCombinedOrderDialog
          open={showAddTransactionsDialog}
          onOpenChange={setShowAddTransactionsDialog}
          combinedOrderId={transaction.combined_order_info?.combined_order_id || transaction.tx_id}
          combinedOrderStatus={transaction.status}
          onSuccess={() => {
            onUpdate?.();
            onOpenChange(false);
          }}
        />
      )}
    </>
  );
}