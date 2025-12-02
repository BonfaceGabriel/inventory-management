import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  listCombinedOrders,
  createCombinedOrder,
  type CombinedOrder,
  type CreateCombinedOrderRequest
} from '../services/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
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
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Package, Plus, Eye, CheckCircle, XCircle, Clock, AlertCircle } from 'lucide-react';
import { format } from 'date-fns';

export default function CombinedOrdersPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createForm, setCreateForm] = useState<CreateCombinedOrderRequest>({
    transaction_ids: [],
    customer_name: '',
    customer_phone: '',
    notes: '',
    created_by: 'System', // TODO: Get from auth context
  });
  const [transactionIdsInput, setTransactionIdsInput] = useState('');

  // Fetch combined orders
  const { data, isLoading, error } = useQuery({
    queryKey: ['combined-orders', statusFilter],
    queryFn: () => listCombinedOrders({ status: statusFilter || undefined }),
  });

  // Create combined order mutation
  const createMutation = useMutation({
    mutationFn: createCombinedOrder,
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['combined-orders'] });
      setShowCreateDialog(false);
      // Navigate to detail page
      navigate(`/combined-orders/${response.combined_order_id}`);
    },
  });

  const handleCreateSubmit = () => {
    // Parse transaction IDs from comma-separated input
    const ids = transactionIdsInput
      .split(',')
      .map(id => parseInt(id.trim()))
      .filter(id => !isNaN(id));

    if (ids.length < 2) {
      alert('Please enter at least 2 transaction IDs');
      return;
    }

    createMutation.mutate({
      ...createForm,
      transaction_ids: ids,
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

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Package className="w-8 h-8" />
            Combined Orders
          </h1>
          <p className="text-muted-foreground mt-1">
            Combine multiple transactions into one fulfillment order
          </p>
        </div>
        <Button onClick={() => setShowCreateDialog(true)}>
          <Plus className="w-4 h-4 mr-2" />
          Create Combined Order
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-4 items-center">
        <div className="flex gap-2">
          <Button
            variant={statusFilter === '' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStatusFilter('')}
          >
            All
          </Button>
          <Button
            variant={statusFilter === 'PENDING' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStatusFilter('PENDING')}
          >
            Pending
          </Button>
          <Button
            variant={statusFilter === 'IN_PROGRESS' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStatusFilter('IN_PROGRESS')}
          >
            In Progress
          </Button>
          <Button
            variant={statusFilter === 'FULFILLED' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStatusFilter('FULFILLED')}
          >
            Fulfilled
          </Button>
        </div>
      </div>

      {/* Combined Orders Table */}
      <div className="border rounded-lg">
        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground">Loading combined orders...</div>
        ) : error ? (
          <div className="p-8 text-center text-red-500">Error loading combined orders</div>
        ) : data && data.combined_orders.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Order ID</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Transactions</TableHead>
                <TableHead>Total Amount</TableHead>
                <TableHead>Fulfilled</TableHead>
                <TableHead>Remaining</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.combined_orders.map((order: CombinedOrder) => (
                <TableRow key={order.id}>
                  <TableCell className="font-mono font-semibold">{order.combined_order_id}</TableCell>
                  <TableCell>{getStatusBadge(order.status)}</TableCell>
                  <TableCell>{order.transaction_count}</TableCell>
                  <TableCell className="font-semibold">KES {parseFloat(order.total_amount).toLocaleString()}</TableCell>
                  <TableCell>KES {parseFloat(order.amount_fulfilled).toLocaleString()}</TableCell>
                  <TableCell>KES {parseFloat(order.remaining_amount).toLocaleString()}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="w-20 bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-blue-500 h-2 rounded-full"
                          style={{ width: `${order.fulfillment_percentage}%` }}
                        />
                      </div>
                      <span className="text-sm text-muted-foreground">
                        {parseFloat(order.fulfillment_percentage).toFixed(0)}%
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {order.customer_name || '-'}
                    {order.customer_phone && (
                      <div className="text-xs text-muted-foreground">{order.customer_phone}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {format(new Date(order.created_at), 'MMM dd, yyyy HH:mm')}
                  </TableCell>
                  <TableCell>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate(`/combined-orders/${order.combined_order_id}`)}
                    >
                      <Eye className="w-4 h-4 mr-1" />
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="p-8 text-center text-muted-foreground">
            No combined orders found. Create your first one!
          </div>
        )}
      </div>

      {/* Create Combined Order Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Create Combined Order</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="transaction_ids">Transaction IDs *</Label>
              <Input
                id="transaction_ids"
                placeholder="e.g., 123, 456, 789"
                value={transactionIdsInput}
                onChange={(e) => setTransactionIdsInput(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Enter transaction IDs separated by commas (minimum 2)
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="customer_name">Customer Name</Label>
              <Input
                id="customer_name"
                placeholder="Optional"
                value={createForm.customer_name}
                onChange={(e) => setCreateForm({ ...createForm, customer_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="customer_phone">Customer Phone</Label>
              <Input
                id="customer_phone"
                placeholder="Optional"
                value={createForm.customer_phone}
                onChange={(e) => setCreateForm({ ...createForm, customer_phone: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="notes">Notes</Label>
              <Textarea
                id="notes"
                placeholder="Optional notes..."
                value={createForm.notes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setCreateForm({ ...createForm, notes: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateSubmit} disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Creating...' : 'Create Order'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
