import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import {
  getCombinedOrderDetails,
  activateCombinedOrder,
  scanProductToCombinedOrder,
  completeCombinedOrder,
  removeCombinedOrderLineItem,
  searchProductBySku,
} from '../../services/api';
import type { CombinedOrder, CombinedOrderLineItem } from '../../types/transaction.types';
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
import { Loader2, Package, Trash2, CheckCircle, Plus, Layers } from 'lucide-react';
import BarcodeScanner from '../scanner/BarcodeScanner';
import type { ParsedBarcode } from '../../utils/barcodeParser';
import { AddToCombinedOrderDialog } from './AddToCombinedOrderDialog';

interface CombinedOrderFulfillmentViewProps {
  combinedOrderId: string;
  onClose: () => void;
  onComplete?: () => void;
}

export default function CombinedOrderFulfillmentView({
  combinedOrderId,
  onClose,
  onComplete,
}: CombinedOrderFulfillmentViewProps) {
  const [order, setOrder] = useState<CombinedOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [activationAttempted, setActivationAttempted] = useState(false);
  const [showAddTransactionsDialog, setShowAddTransactionsDialog] = useState(false);

  const fetchOrderDetails = async () => {
    try {
      setLoading(true);
      const data = await getCombinedOrderDetails(combinedOrderId);
      setOrder(data);

      // Auto-activate if PENDING (only once)
      if (data.status === 'PENDING' && !activationAttempted) {
        setActivationAttempted(true);
        try {
          await activateCombinedOrder(combinedOrderId, 'user');
          const updatedData = await getCombinedOrderDetails(combinedOrderId);
          setOrder(updatedData);
        } catch (error: any) {
          // If activation fails (e.g., already activated by another request), just fetch latest data
          console.log('Activation error (may be already activated):', error);
          const updatedData = await getCombinedOrderDetails(combinedOrderId);
          setOrder(updatedData);
        }
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

  const handleScan = async (barcode: ParsedBarcode) => {
    try {
      setProcessing(true);

      // Search for product by SKU
      const productData = await searchProductBySku(barcode.sku);

      if (!productData) {
        toast.error(`Product not found: ${barcode.sku}`);
        return;
      }

      // Scan product to combined order (staged)
      await scanProductToCombinedOrder(
        combinedOrderId,
        productData.id,
        barcode.quantity,
        'user'
      );

      toast.success(`Added ${barcode.quantity}x ${productData.prod_name} (STAGED)`);
      await fetchOrderDetails();
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to scan product');
    } finally {
      setProcessing(false);
    }
  };

  const handleRemoveItem = async (itemId: number) => {
    try {
      setProcessing(true);
      await removeCombinedOrderLineItem(combinedOrderId, itemId);
      toast.success('Item removed');
      await fetchOrderDetails();
    } catch (error: any) {
      toast.error('Failed to remove item');
    } finally {
      setProcessing(false);
    }
  };

  const handleComplete = async () => {
    if (!order?.line_items?.length) {
      toast.error('Cannot complete order with no items');
      return;
    }

    try {
      setProcessing(true);
      await completeCombinedOrder(combinedOrderId, 'user');
      toast.success('Combined order completed! All transactions marked as COMBINED_FULFILLED.');
      onComplete?.();
      onClose();
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to complete order');
    } finally {
      setProcessing(false);
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

  const isCompleted = order.status === 'FULFILLED' || order.status === 'PARTIALLY_FULFILLED';
  const isCancelled = order.status === 'CANCELLED';
  const canEdit = order.status === 'IN_PROGRESS';

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
            <Layers className="h-4 w-4" />
          </Button>
          <div>
            <h3 className="text-lg font-semibold">{order.combined_order_id}</h3>
            <p className="text-sm text-gray-500">
              {order.transaction_count} transactions combined
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {(order.status === 'PENDING' || order.status === 'PARTIALLY_FULFILLED' || order.status === 'IN_PROGRESS') && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAddTransactionsDialog(true)}
              disabled={processing}
              className="border-purple-300 text-purple-600 hover:bg-purple-50"
            >
              <Plus className="mr-2 h-4 w-4" />
              Add Transactions
            </Button>
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

      {/* Summary Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Order Summary</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Total Budget:</span>
            <span className="font-semibold">KES {order.total_amount}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Fulfilled:</span>
            <span className="font-semibold">KES {order.amount_fulfilled}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Remaining:</span>
            <span className="font-semibold text-orange-600">
              KES {order.remaining_amount}
            </span>
          </div>
          {order.customer_name && (
            <div className="flex justify-between text-sm pt-2 border-t">
              <span className="text-gray-600">Customer:</span>
              <span>{order.customer_name}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Barcode Scanner - only show if order is in progress */}
      {canEdit && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Package className="h-4 w-4" />
              Scan Products
            </CardTitle>
          </CardHeader>
          <CardContent>
            <BarcodeScanner
              onScan={handleScan}
              disabled={processing}
              placeholder="Scan or enter barcode..."
              autoFocus
            />
            <p className="text-xs text-gray-500 mt-2">
              Scan products to add to this combined order. Items are staged until you complete the order.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Scanned Items Table */}
      {order.line_items && order.line_items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Scanned Items {canEdit && <Badge variant="outline" className="ml-2">STAGED</Badge>}
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
                  {canEdit && <TableHead className="w-[50px]"></TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {order.line_items.map((item: CombinedOrderLineItem) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-medium">
                      {item.product_name}
                    </TableCell>
                    <TableCell className="text-gray-600">
                      {item.product_code}
                    </TableCell>
                    <TableCell className="text-right">{item.quantity}</TableCell>
                    <TableCell className="text-right">
                      KES {item.unit_price}
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      KES {item.line_total}
                    </TableCell>
                    {canEdit && (
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRemoveItem(item.id)}
                          disabled={processing}
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      {canEdit && (
        <>
          <div className="flex justify-end gap-2">
            <Button
              onClick={handleComplete}
              disabled={processing || !order.line_items?.length}
              className="w-full sm:w-auto"
            >
              {processing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Completing...
                </>
              ) : (
                <>
                  <CheckCircle className="mr-2 h-4 w-4" />
                  Complete Order
                </>
              )}
            </Button>
          </div>

          <p className="text-xs text-gray-500 text-center">
            Completing this order will update inventory and mark all {order.transaction_count} linked transactions as COMBINED_FULFILLED
          </p>
        </>
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
