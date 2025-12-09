import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
  getCombinedOrderDetails,
  activateCombinedOrder,
  scanProductToCombinedOrder,
  completeCombinedOrder,
  removeCombinedOrderLineItem,
  searchProductBySku,
  cancelCombinedOrder,
} from '../services/api';
import type { CombinedOrder, CombinedOrderLineItem } from '../types/transaction.types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { Loader2, Package, Trash2, CheckCircle, ArrowLeft, XCircle } from 'lucide-react';
import BarcodeScanner from '../components/scanner/BarcodeScanner';
import type { ParsedBarcode } from '../utils/barcodeParser';

export default function CombinedOrderScanningPage() {
  const { id: combinedOrderId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [order, setOrder] = useState<CombinedOrder | null>(null);
  const [lineItems, setLineItems] = useState<CombinedOrderLineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [activationAttempted, setActivationAttempted] = useState(false);

  const fetchOrderDetails = async () => {
    if (!combinedOrderId) return;

    try {
      setLoading(true);
      const data = await getCombinedOrderDetails(combinedOrderId);
      setOrder(data);
      setLineItems(data.line_items || []);

      // Auto-activate if PENDING or PARTIALLY_FULFILLED (only once)
      if ((data.status === 'PENDING' || data.status === 'PARTIALLY_FULFILLED') && !activationAttempted) {
        setActivationAttempted(true);
        try {
          await activateCombinedOrder(combinedOrderId, 'user');
          const updatedData = await getCombinedOrderDetails(combinedOrderId);
          setOrder(updatedData);
          setLineItems(updatedData.line_items || []);
          toast.success(`Combined order ${data.status === 'PARTIALLY_FULFILLED' ? 'reopened' : 'activated'} for fulfillment`);
        } catch (error: any) {
          console.log('Activation error (may be already activated):', error);
          const updatedData = await getCombinedOrderDetails(combinedOrderId);
          setOrder(updatedData);
          setLineItems(updatedData.line_items || []);
        }
      }
    } catch (error: any) {
      toast.error('Failed to load combined order details');
      console.error(error);
      navigate('/transactions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrderDetails();
  }, [combinedOrderId]);

  // Prevent browser close/refresh if items are scanned
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (order?.status === 'IN_PROGRESS' && lineItems.length > 0) {
        e.preventDefault();
        return (e.returnValue = 'You have unsaved scanned items. Are you sure you want to leave?');
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload, { capture: true });
    return () => window.removeEventListener('beforeunload', handleBeforeUnload, { capture: true });
  }, [order?.status, lineItems.length]);

  const handleScan = async (barcode: ParsedBarcode) => {
    if (!combinedOrderId) return;

    try {
      setProcessing(true);

      // Search for product by SKU
      const productData = await searchProductBySku(barcode.sku);

      if (!productData) {
        toast.error(`Product not found: ${barcode.sku}`);
        return;
      }

      // Scan product to combined order (staged)
      const result = await scanProductToCombinedOrder(
        combinedOrderId,
        productData.id,
        barcode.quantity,
        'user'
      );

      toast.success(`Added ${barcode.quantity}x ${productData.prod_name} (STAGED)`);

      // Update line items optimistically
      const existingIndex = lineItems.findIndex(item => item.id === result.line_item_id);
      if (existingIndex >= 0) {
        setLineItems(prev =>
          prev.map((item, index) =>
            index === existingIndex
              ? {
                  ...item,
                  quantity: result.quantity,
                  line_total: result.line_total,
                }
              : item
          )
        );
      } else {
        const newItem: CombinedOrderLineItem = {
          id: result.line_item_id,
          product_code: productData.prod_code,
          product_name: productData.prod_name,
          sku: barcode.sku,
          quantity: result.quantity,
          unit_price: result.unit_price,
          line_total: result.line_total,
          scanned_at: new Date().toISOString(),
          scanned_by: 'user',
        };
        setLineItems(prev => [...prev, newItem]);
      }

      // Refresh order summary
      await fetchOrderDetails();
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to scan product');
    } finally {
      setProcessing(false);
    }
  };

  const handleRemoveItem = async (itemId: number) => {
    if (!combinedOrderId) return;

    try {
      setProcessing(true);
      await removeCombinedOrderLineItem(combinedOrderId, itemId);
      toast.success('Item removed');
      setLineItems(prev => prev.filter(item => item.id !== itemId));
      await fetchOrderDetails();
    } catch (error: any) {
      toast.error('Failed to remove item');
    } finally {
      setProcessing(false);
    }
  };

  const handleComplete = async () => {
    if (!combinedOrderId) return;

    if (!lineItems.length) {
      toast.error('Cannot complete order with no items');
      return;
    }

    try {
      setProcessing(true);
      await completeCombinedOrder(combinedOrderId, 'user');
      toast.success('Combined order completed! All transactions marked as COMBINED_FULFILLED.');
      navigate('/transactions');
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to complete order');
    } finally {
      setProcessing(false);
    }
  };

  const handleCancel = async () => {
    if (!combinedOrderId) return;

    const shouldCancel = window.confirm(
      'Cancel this combined order? All scanned items will be discarded and the order will be marked as cancelled. This action cannot be undone.'
    );

    if (!shouldCancel) return;

    try {
      setProcessing(true);
      await cancelCombinedOrder(combinedOrderId);
      toast.success('Combined order cancelled');
      navigate('/transactions');
    } catch (error: any) {
      toast.error('Failed to cancel order');
    } finally {
      setProcessing(false);
    }
  };

  const handleBack = async () => {
    if (order?.status === 'IN_PROGRESS' && lineItems.length > 0) {
      const shouldLeave = window.confirm(
        `You have ${lineItems.length} scanned ${lineItems.length === 1 ? 'item' : 'items'}. Going back will cancel the order and discard all scanned items. This action cannot be undone.`
      );

      if (!shouldLeave) return;

      // Cancel the issuance before going back
      try {
        await cancelCombinedOrder(combinedOrderId!);
      } catch (error) {
        console.error('Failed to cancel order:', error);
      }
    }
    navigate('/transactions');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  if (!order) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center p-8 text-gray-500">
          Combined order not found
        </div>
      </div>
    );
  }

  const isActive = order.status === 'IN_PROGRESS';
  const isCompleted = order.status === 'FULFILLED';
  const isCancelled = order.status === 'CANCELLED';
  const isTimeLocked = order.is_time_locked || false;
  const isReadOnly = isCompleted || isCancelled || isTimeLocked;

  return (
    <div className="container mx-auto p-6 max-w-6xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleBack}
            disabled={processing}
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
          <div>
            <h1 className="text-2xl font-bold">{order.combined_order_id}</h1>
            <p className="text-sm text-gray-500">
              {order.transaction_count} transactions combined
            </p>
          </div>
        </div>
        <Badge
          variant={
            isCompleted
              ? 'default'
              : isCancelled
              ? 'destructive'
              : 'secondary'
          }
          className="text-sm px-3 py-1"
        >
          {order.status}
        </Badge>
      </div>

      {/* Time-Locked Warning Banner */}
      {isTimeLocked && (
        <div className="bg-orange-50 border-l-4 border-orange-500 p-4">
          <div className="flex items-center">
            <div className="flex-shrink-0">
              <XCircle className="h-5 w-5 text-orange-500" />
            </div>
            <div className="ml-3">
              <p className="text-sm text-orange-700">
                <strong>Order Locked:</strong> This combined order was time-locked at end-of-day on{' '}
                {order.locked_at ? new Date(order.locked_at).toLocaleDateString() : 'unknown date'}.
                It cannot be modified.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Summary Card */}
      <Card>
        <CardHeader>
          <CardTitle>Order Summary</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-sm text-gray-600">Total Budget</p>
            <p className="text-2xl font-bold">KES {order.total_amount}</p>
          </div>
          <div>
            <p className="text-sm text-gray-600">Fulfilled</p>
            <p className="text-2xl font-bold text-green-600">
              KES {order.amount_fulfilled}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600">Remaining</p>
            <p className="text-2xl font-bold text-orange-600">
              KES {order.remaining_amount}
            </p>
          </div>
          {order.customer_name && (
            <div>
              <p className="text-sm text-gray-600">Customer</p>
              <p className="text-lg font-semibold">{order.customer_name}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Barcode Scanner - only show if order is in progress */}
      {isActive && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Package className="h-5 w-5" />
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
            <p className="text-sm text-gray-500 mt-3">
              Scan products to add to this combined order. Items are staged until you complete the order.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Scanned Items Table */}
      {lineItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Scanned Items
              {isActive && (
                <Badge variant="outline" className="ml-2">
                  STAGED
                </Badge>
              )}
              <span className="text-sm font-normal text-gray-500 ml-auto">
                {lineItems.length} {lineItems.length === 1 ? 'item' : 'items'}
              </span>
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
                  {isActive && <TableHead className="w-[50px]"></TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {lineItems.map((item: CombinedOrderLineItem) => (
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
                    {isActive && (
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

      {/* No items message */}
      {lineItems.length === 0 && isActive && (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            <Package className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>No items scanned yet. Start scanning products to fulfill this order.</p>
          </CardContent>
        </Card>
      )}

      {/* Action Buttons */}
      {isActive && (
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={handleCancel}
            disabled={processing}
          >
            <XCircle className="mr-2 h-4 w-4" />
            Cancel Order
          </Button>
          <Button
            onClick={handleComplete}
            disabled={processing || !lineItems.length}
            size="lg"
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
      )}

      {isActive && (
        <p className="text-sm text-gray-500 text-center">
          Completing this order will update inventory and mark all {order.transaction_count} linked
          transactions as COMBINED_FULFILLED
        </p>
      )}
    </div>
  );
}
