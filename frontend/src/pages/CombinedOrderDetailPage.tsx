import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getCombinedOrderDetail,
  scanProductToCombinedOrder,
  cancelCombinedOrder,
  type ScanProductToCombinedOrderRequest,
  type CancelCombinedOrderRequest
} from '../services/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '../components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter
} from '../components/ui/dialog';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import {
  Package,
  ArrowLeft,
  Scan,
  XCircle,
  CheckCircle,
  AlertCircle,
  Clock,
  ShoppingCart
} from 'lucide-react';
import { format } from 'date-fns';

export default function CombinedOrderDetailPage() {
  const { combinedOrderId } = useParams<{ combinedOrderId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [showScanDialog, setShowScanDialog] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [scanForm, setScanForm] = useState<ScanProductToCombinedOrderRequest>({
    product_id: 0,
    quantity: 1,
    scanned_by: 'System', // TODO: Get from auth context
  });
  const [cancelReason, setCancelReason] = useState('');

  // Fetch combined order details
  const { data: order, isLoading, error } = useQuery({
    queryKey: ['combined-order', combinedOrderId],
    queryFn: () => getCombinedOrderDetail(combinedOrderId!),
    enabled: !!combinedOrderId,
  });

  // Scan product mutation
  const scanMutation = useMutation({
    mutationFn: (data: ScanProductToCombinedOrderRequest) =>
      scanProductToCombinedOrder(combinedOrderId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['combined-order', combinedOrderId] });
      setShowScanDialog(false);
      setScanForm({ product_id: 0, quantity: 1, scanned_by: 'System' });
    },
  });

  // Cancel order mutation
  const cancelMutation = useMutation({
    mutationFn: (data: CancelCombinedOrderRequest) =>
      cancelCombinedOrder(combinedOrderId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['combined-order', combinedOrderId] });
      setShowCancelDialog(false);
      navigate('/combined-orders');
    },
  });

  const handleScanSubmit = () => {
    if (!scanForm.product_id) {
      alert('Please enter a product ID');
      return;
    }
    scanMutation.mutate(scanForm);
  };

  const handleCancelSubmit = () => {
    cancelMutation.mutate({
      cancelled_by: 'System', // TODO: Get from auth context
      reason: cancelReason,
    });
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'FULFILLED':
        return <Badge className="bg-green-500"><CheckCircle className="w-3 h-3 mr-1" />Fulfilled</Badge>;
      case 'CANCELLED':
        return <Badge className="bg-red-500"><XCircle className="w-3 h-3 mr-1" />Cancelled</Badge>;
      case 'IN_PROGRESS':
        return <Badge className="bg-blue-500"><Clock className="w-3 h-3 mr-1" />In Progress</Badge>;
      case 'PENDING':
        return <Badge className="bg-yellow-500"><AlertCircle className="w-3 h-3 mr-1" />Pending</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  if (isLoading) {
    return <div className="p-6 text-center">Loading combined order...</div>;
  }

  if (error || !order) {
    return (
      <div className="p-6 text-center text-red-500">
        Error loading combined order. Please try again.
      </div>
    );
  }

  const canScan = order.status === 'PENDING' || order.status === 'IN_PROGRESS';
  const canCancel = order.status !== 'FULFILLED' && order.status !== 'CANCELLED';

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div className="flex items-center gap-4">
          <Button variant="ghost" onClick={() => navigate('/combined-orders')}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div>
            <h1 className="text-3xl font-bold font-mono">{order.combined_order_id}</h1>
            <p className="text-muted-foreground mt-1">
              Created {format(new Date(order.created_at), 'MMM dd, yyyy HH:mm')} by {order.created_by}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {canScan && (
            <Button onClick={() => setShowScanDialog(true)}>
              <Scan className="w-4 h-4 mr-2" />
              Scan Product
            </Button>
          )}
          {canCancel && (
            <Button variant="destructive" onClick={() => setShowCancelDialog(true)}>
              <XCircle className="w-4 h-4 mr-2" />
              Cancel Order
            </Button>
          )}
        </div>
      </div>

      {/* Status and Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Status</CardTitle>
          </CardHeader>
          <CardContent>
            {getStatusBadge(order.status)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Amount</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">KES {parseFloat(order.total_amount).toLocaleString()}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Amount Fulfilled</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              KES {parseFloat(order.amount_fulfilled).toLocaleString()}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Remaining</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-orange-600">
              KES {parseFloat(order.remaining_amount).toLocaleString()}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Progress Bar */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Fulfillment Progress</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span>Progress</span>
              <span className="font-semibold">{parseFloat(order.fulfillment_percentage).toFixed(1)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-4">
              <div
                className="bg-blue-500 h-4 rounded-full transition-all"
                style={{ width: `${order.fulfillment_percentage}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Customer Info */}
      {(order.customer_name || order.customer_phone) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Customer Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {order.customer_name && <div><strong>Name:</strong> {order.customer_name}</div>}
            {order.customer_phone && <div><strong>Phone:</strong> {order.customer_phone}</div>}
          </CardContent>
        </Card>
      )}

      {/* Linked Transactions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Package className="w-5 h-5" />
            Linked Transactions ({order.transaction_count})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>TX ID</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Sender</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Timestamp</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {order.transactions?.map((tx) => (
                <TableRow key={tx.id}>
                  <TableCell className="font-mono">{tx.tx_id}</TableCell>
                  <TableCell className="font-semibold">KES {parseFloat(tx.amount).toLocaleString()}</TableCell>
                  <TableCell>{tx.sender_name}</TableCell>
                  <TableCell>{tx.sender_phone}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {format(new Date(tx.timestamp), 'MMM dd, yyyy HH:mm')}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Line Items (Scanned Products) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <ShoppingCart className="w-5 h-5" />
            Scanned Products ({order.line_items?.length || 0})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {order.line_items && order.line_items.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product Code</TableHead>
                  <TableHead>Product Name</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead>Quantity</TableHead>
                  <TableHead>Unit Price</TableHead>
                  <TableHead>Line Total</TableHead>
                  <TableHead>Scanned At</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {order.line_items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-mono">{item.scanned_prod_code}</TableCell>
                    <TableCell>{item.scanned_prod_name}</TableCell>
                    <TableCell className="font-mono text-sm">{item.scanned_sku}</TableCell>
                    <TableCell>{item.quantity}</TableCell>
                    <TableCell>KES {parseFloat(item.scanned_price).toLocaleString()}</TableCell>
                    <TableCell className="font-semibold">
                      KES {parseFloat(item.line_total).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {format(new Date(item.scanned_at), 'MMM dd, HH:mm')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              No products scanned yet. Click "Scan Product" to start fulfilling this order.
            </div>
          )}
        </CardContent>
      </Card>

      {/* Notes */}
      {order.notes && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Notes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap">{order.notes}</p>
          </CardContent>
        </Card>
      )}

      {/* Scan Product Dialog */}
      <Dialog open={showScanDialog} onOpenChange={setShowScanDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Scan Product</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="product_id">Product ID *</Label>
              <Input
                id="product_id"
                type="number"
                placeholder="Enter product ID"
                value={scanForm.product_id || ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setScanForm({ ...scanForm, product_id: parseInt(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="quantity">Quantity *</Label>
              <Input
                id="quantity"
                type="number"
                min="1"
                value={scanForm.quantity}
                onChange={(e) => setScanForm({ ...scanForm, quantity: parseInt(e.target.value) })}
              />
            </div>
            <div className="text-sm text-muted-foreground">
              Remaining budget: KES {parseFloat(order.remaining_amount).toLocaleString()}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowScanDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleScanSubmit} disabled={scanMutation.isPending}>
              {scanMutation.isPending ? 'Scanning...' : 'Scan Product'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel Order Dialog */}
      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel Combined Order</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <p className="text-sm text-muted-foreground">
              Are you sure you want to cancel this order? All scanned products will be returned to inventory.
            </p>
            <div className="space-y-2">
              <Label htmlFor="cancel_reason">Reason</Label>
              <Textarea
                id="cancel_reason"
                placeholder="Optional cancellation reason..."
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCancelDialog(false)}>
              No, Keep Order
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelSubmit}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending ? 'Cancelling...' : 'Yes, Cancel Order'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
