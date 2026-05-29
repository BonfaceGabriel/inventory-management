import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  getCombinedOrderDetails,
  activateCombinedOrder,
  revertCombinedOrder,
} from '../../services/api';
import type { CombinedOrder } from '../../types/transaction.types';
import { Button } from '../ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { SpinnerGap, ArrowLeft, Plus, Play, Calendar, User, ArrowsCounterClockwise } from '@phosphor-icons/react';
import { formatCurrency, formatDate } from '../../services/api';
import { AddToCombinedOrderDialog } from './AddToCombinedOrderDialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../ui/alert-dialog';
import { Label } from '../ui/label';
import { Textarea } from '../ui/textarea';


interface CombinedOrderDetailsViewProps {
  combinedOrderId: string;
  onClose: () => void;
  onUpdate?: () => void;
}

export default function CombinedOrderDetailsView({
  combinedOrderId,
  onClose,
}: CombinedOrderDetailsViewProps) {
  const navigate = useNavigate();
  const [order, setOrder] = useState<CombinedOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [showAddTransactionsDialog, setShowAddTransactionsDialog] = useState(false);
  const [showRevertDialog, setShowRevertDialog] = useState(false);
  const [revertReason, setRevertReason] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  const fetchOrderDetails = async () => {
    console.log('[fetchOrderDetails] CALLED for combinedOrderId:', combinedOrderId);
    try {
      setLoading(true);
      console.log('[fetchOrderDetails] Calling getCombinedOrderDetails...');
      const data = await getCombinedOrderDetails(combinedOrderId);
      console.log('[fetchOrderDetails] SUCCESS - Fetched combined order details:', {
        combined_order_id: data.combined_order_id,
        transaction_count: data.transaction_count,
        total_amount: data.total_amount,
        amount_fulfilled: data.amount_fulfilled,
        remaining_amount: data.remaining_amount,
        status: data.status
      });
      setOrder(data);
      setRefreshKey(prev => prev + 1); // Force component re-render with new data
      console.log('[fetchOrderDetails] State updated, refreshKey incremented');

      // If order is already in progress, we can offer to continue fulfillment
      // using the "Activate" button logic (which will now just navigate)
      if (data.status === 'IN_PROGRESS') {
        // Optional: auto-navigate or just show status
      }
    } catch (error: any) {
      console.error('[fetchOrderDetails] ERROR:', error);
      console.error('[fetchOrderDetails] Error details:', {
        message: error.message,
        response: error.response?.data,
        status: error.response?.status
      });
      toast.error('Failed to load combined order details');
    } finally {
      setLoading(false);
      console.log('[fetchOrderDetails] COMPLETED (finally block)');
    }
  };

  useEffect(() => {
    fetchOrderDetails();
  }, [combinedOrderId]);

  const handleActivateForFulfillment = async () => {
    try {
      setActivating(true);
      await activateCombinedOrder(combinedOrderId, 'user');
      toast.success('Combined order activated for fulfillment');
      // Navigate to the standardized scanning page
      navigate(`/transactions/${combinedOrderId}/scan`);
      onClose(); // Close the modal/details view
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to activate order');
    } finally {
      setActivating(false);
    }
  };

  const handleRevertOrder = async () => {
    if (!revertReason.trim()) {
      toast.error('Please provide a reason for reverting');
      return;
    }

    try {
      setReverting(true);
      const result = await revertCombinedOrder(combinedOrderId, revertReason, 'user');
      toast.success(result.message || 'Combined order reverted successfully');
      setShowRevertDialog(false);
      setRevertReason('');
      onClose(); // Close the details view since order is deleted
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to revert combined order');
    } finally {
      setReverting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <SpinnerGap className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  if (!order) {
    return (
      <div className="text-center p-8 text-gray-500">
        Combined order not found
      </div>
    );
  }



  const isCompleted = order.status === 'FULFILLED';
  const isCancelled = order.status === 'CANCELLED';
  const isPartiallyFulfilled = order.status === 'PARTIALLY_FULFILLED';
  const isPending = order.status === 'PENDING';
  const isInProgress = order.status === 'IN_PROGRESS';
  const isProcessing = order.status === 'PROCESSING'; // Handle legacy/invalid status
  const canActivate = isPending || isPartiallyFulfilled || isProcessing;
  const canAddTransactions = isPending || isInProgress || isPartiallyFulfilled || isProcessing;

  // Debug logging
  console.log('CombinedOrderDetailsView:', {
    status: order.status,
    isPending,
    isInProgress,
    isProcessing,
    isPartiallyFulfilled,
    canAddTransactions,
    canActivate
  });

  return (
    <div className="space-y-4" key={`combined-order-${combinedOrderId}-${refreshKey}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="h-8 w-8 p-0"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h3 className="text-lg font-semibold">{order.combined_order_id}</h3>
            <p className="text-sm text-gray-500">
              {order.transaction_count} transactions combined
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Revert Button - Only show if not completed or cancelled */}
          {!isCompleted && !isCancelled && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowRevertDialog(true)}
              disabled={reverting}
              className=""
            >
              <ArrowsCounterClockwise className="mr-2 h-4 w-4" />
              Revert Order
            </Button>
          )}
          {canAddTransactions && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAddTransactionsDialog(true)}
              className="border-[rgb(var(--color-secondary))]/[0.3] text-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/[0.1]"
            >
              <Plus className="mr-2 h-4 w-4" />
              Add Transactions
            </Button>
          )}
          {canActivate && (
            <Button
              variant="default"
              size="sm"
              onClick={handleActivateForFulfillment}
              disabled={activating}
              className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/[0.85]"
            >
              {activating ? (
                <>
                  <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                  Activating...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Activate for Fulfillment
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Order Summary Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Order Summary</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Total Budget</p>
              <p className="text-xl font-bold">{formatCurrency(order.total_amount)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Fulfilled</p>
              <p className="text-xl font-bold text-green-600">
                {formatCurrency(order.amount_fulfilled)}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Remaining</p>
              <p className="text-xl font-bold text-[rgb(var(--color-primary))]">
                {formatCurrency(order.remaining_amount)}
              </p>
            </div>
          </div>

          {order.customer_name && (
            <div className="pt-3 border-t">
              <div className="flex items-center gap-2 text-sm">
                <User className="h-4 w-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">Customer:</span>
                <span className="font-medium">{order.customer_name}</span>
              </div>
            </div>
          )}

          {order.created_at && (
            <div className="flex items-center gap-2 text-sm">
              <Calendar className="h-4 w-4 text-gray-400" />
              <span className="text-gray-600 dark:text-gray-400">Created:</span>
              <span className="font-medium">{formatDate(order.created_at)}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Scanned Items (if any) */}
      {order.line_items && order.line_items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Previously Scanned Items ({order.line_items.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Unit Price</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {order.line_items.map((item: any) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-medium">
                      {item.product_name}
                    </TableCell>
                    <TableCell className="text-gray-600">
                      {item.product_code}
                    </TableCell>
                    <TableCell className="text-right">{item.quantity}</TableCell>
                    <TableCell className="text-right">
                      {formatCurrency(item.unit_price)}
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      {formatCurrency(item.line_total)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Help Text */}
      {canActivate && (
        <div className="text-center p-4 bg-[rgb(var(--color-primary))]/[0.1] dark:bg-blue-900/20 border border-[rgb(var(--color-primary))]/[0.3] dark:border-blue-800 rounded-lg">
          <p className="text-sm text-[rgb(var(--color-primary))] dark:text-blue-200">
            Click <strong>"{isInProgress ? 'Continue Fulfillment' : 'Activate for Fulfillment'}"</strong> above to start scanning products for this combined order.
          </p>
        </div>
      )}

      {/* Add Transactions Dialog */}
      <AddToCombinedOrderDialog
        open={showAddTransactionsDialog}
        onOpenChange={setShowAddTransactionsDialog}
        combinedOrderId={combinedOrderId}
        combinedOrderStatus={order.status}
        onSuccess={(updatedOrderData) => {
          console.log('[CombinedOrderDetailsView] onSuccess called with data:', updatedOrderData);
          toast.success('Transactions added successfully');

          // If we have updated data from the response, use it directly
          if (updatedOrderData) {
            console.log('[CombinedOrderDetailsView] Using updated data from response directly');
            setOrder(updatedOrderData);
            setRefreshKey(prev => prev + 1);
          } else {
            // Fallback to fetching
            console.log('[CombinedOrderDetailsView] No data provided, fetching...');
            fetchOrderDetails();
          }
        }}
      />

      {/* Revert Order Dialog */}
      <AlertDialog open={showRevertDialog} onOpenChange={setShowRevertDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revert Combined Order?</AlertDialogTitle>
            <AlertDialogDescription>
              This will completely revert the combined order to pre-combination state:
              <ul className="list-disc ml-5 mt-2 space-y-1">
                <li>All child transactions will be restored to their original status</li>
                <li>All scanned products will be returned to inventory</li>
                <li>All line items will be deleted</li>
                <li>The combined order will be deleted entirely</li>
              </ul>
              <p className="mt-3 font-semibold text-red-600">This action cannot be undone!</p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="my-4">
            <Label htmlFor="revert-reason" className="mb-2 block">
              Reason for revert <span className="text-red-500">*</span>
            </Label>
            <Textarea
              id="revert-reason"
              placeholder="Enter reason (required)"
              value={revertReason}
              onChange={(e) => setRevertReason(e.target.value)}
              rows={3}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel
              disabled={reverting}
              onClick={() => {
                setShowRevertDialog(false);
                setRevertReason('');
              }}
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevertOrder}
              disabled={reverting || !revertReason.trim()}
              className="bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/[0.85]"
            >
              {reverting ? (
                <>
                  <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                  Reverting...
                </>
              ) : (
                <>
                  <ArrowsCounterClockwise className="mr-2 h-4 w-4" />
                  Revert Order
                </>
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
