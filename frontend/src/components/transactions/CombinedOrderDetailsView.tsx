import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import {
  getCombinedOrderDetails,
  activateCombinedOrder,
} from '../../services/api';
import type { CombinedOrder } from '../../types/transaction.types';
import { Button } from '../ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Badge } from '../ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { Loader2, ArrowLeft, Plus, Play, Calendar, User } from 'lucide-react';
import { formatCurrency, formatDate } from '../../services/api';
import { AddToCombinedOrderDialog } from './AddToCombinedOrderDialog';
import CombinedOrderFulfillmentView from './CombinedOrderFulfillmentView';

interface CombinedOrderDetailsViewProps {
  combinedOrderId: string;
  onClose: () => void;
  onUpdate?: () => void;
}

export default function CombinedOrderDetailsView({
  combinedOrderId,
  onClose,
  onUpdate,
}: CombinedOrderDetailsViewProps) {
  const [order, setOrder] = useState<CombinedOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);
  const [showAddTransactionsDialog, setShowAddTransactionsDialog] = useState(false);
  const [showFulfillmentView, setShowFulfillmentView] = useState(false);

  const fetchOrderDetails = async () => {
    try {
      setLoading(true);
      const data = await getCombinedOrderDetails(combinedOrderId);
      setOrder(data);

      // If order is already in progress, show fulfillment view
      if (data.status === 'IN_PROGRESS') {
        setShowFulfillmentView(true);
      }
    } catch (error: any) {
      toast.error('Failed to load combined order details');
      console.error(error);
    } finally {
      setLoading(false);
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
      await fetchOrderDetails();
      setShowFulfillmentView(true);
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to activate order');
    } finally {
      setActivating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
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

  // If showing fulfillment view, render that instead
  if (showFulfillmentView) {
    return (
      <CombinedOrderFulfillmentView
        combinedOrderId={combinedOrderId}
        onClose={() => {
          setShowFulfillmentView(false);
          fetchOrderDetails();
        }}
        onComplete={() => {
          setShowFulfillmentView(false);
          onUpdate?.();
          onClose();
        }}
      />
    );
  }

  const isCompleted = order.status === 'FULFILLED';
  const isCancelled = order.status === 'CANCELLED';
  const isPartiallyFulfilled = order.status === 'PARTIALLY_FULFILLED';
  const isPending = order.status === 'PENDING';
  const canActivate = isPending || isPartiallyFulfilled;

  return (
    <div className="space-y-4">
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
          {canActivate && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowAddTransactionsDialog(true)}
                className="border-purple-300 text-purple-600 hover:bg-purple-50"
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Transactions
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={handleActivateForFulfillment}
                disabled={activating}
                className="bg-green-600 hover:bg-green-700"
              >
                {activating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Activating...
                  </>
                ) : (
                  <>
                    <Play className="mr-2 h-4 w-4" />
                    Activate for Fulfillment
                  </>
                )}
              </Button>
            </>
          )}
          <Badge
            variant={
              isCompleted
                ? 'default'
                : isCancelled
                ? 'destructive'
                : 'secondary'
            }
          >
            {order.status}
          </Badge>
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
              <p className="text-xl font-bold text-orange-600">
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
        <div className="text-center p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
          <p className="text-sm text-blue-800 dark:text-blue-200">
            Click <strong>"Activate for Fulfillment"</strong> above to start scanning products for this combined order.
          </p>
        </div>
      )}

      {/* Add Transactions Dialog */}
      <AddToCombinedOrderDialog
        open={showAddTransactionsDialog}
        onOpenChange={setShowAddTransactionsDialog}
        combinedOrderId={combinedOrderId}
        combinedOrderStatus={order.status}
        onSuccess={() => {
          toast.success('Transactions added successfully');
          fetchOrderDetails();
        }}
      />
    </div>
  );
}
