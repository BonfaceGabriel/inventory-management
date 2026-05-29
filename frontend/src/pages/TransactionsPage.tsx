import { useState, useEffect, useCallback } from 'react';
import { StackSimple, UserPlus, CaretRight } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogBody, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Pagination } from '@/components/ui/pagination';
import { AdvancedFilters } from '@/components/transactions/AdvancedFilters';
import type { TransactionFilters } from '@/components/transactions/AdvancedFilters';
import { TransactionDetailModal } from '@/components/transactions/TransactionDetailModal';
import { StatusDropdown } from '@/components/transactions/StatusDropdown';
import { useTransactions } from '@/services/queries/transactions';
import { useDailyReport } from '@/services/queries/reports';
import { useWebSocketContext } from '@/contexts/WebSocketContext';
import { useAuth } from '@/contexts/AuthContext';
import {
  formatCurrency, formatDate, getGatewayLabel,
  createCombinedOrder, getTransactionById, getTransactions,
  getIssuerStats, type IssuerStats
} from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { toast } from 'sonner';
import { extractApiError } from '@/lib/error-utils';
import { useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';

export default function TransactionsPage() {
  const { hasProcessorAccess, hasIssuerAccess } = useAuth();
  const queryClient = useQueryClient();

  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [page, setPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [filters, setFilters] = useState<TransactionFilters>({});
  const [issuerStats, setIssuerStats] = useState<IssuerStats | null>(null);
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<number[]>([]);
  const [showCombineDialog, setShowCombineDialog] = useState(false);
  const [combineForm, setCombineForm] = useState({ customer_name: '', customer_phone: '', notes: '' });
  const [isCombining, setIsCombining] = useState(false);

  const { data, isLoading, refetch } = useTransactions({ ...filters, page, page_size: itemsPerPage });
  const { data: report, refetch: refetchReport } = useDailyReport(undefined, hasProcessorAccess());
  const { onTransactionCreated } = useWebSocketContext();

  const fetchIssuerStats = useCallback(async () => {
    if (!hasIssuerAccess() || hasProcessorAccess()) return;
    try { setIssuerStats(await getIssuerStats()); } catch {}
  }, []);

  const orders = data?.results || [];
  const totalItems = data?.count || 0;

  useEffect(() => { fetchIssuerStats(); }, [fetchIssuerStats]);

  useEffect(() => {
    const cleanup = onTransactionCreated(() => {
      refetch();
      if (hasProcessorAccess()) refetchReport();
      fetchIssuerStats();
    });
    return cleanup;
  }, [onTransactionCreated, refetch, refetchReport, fetchIssuerStats, hasProcessorAccess]);

  const handleFiltersChange = (newFilters: TransactionFilters) => {
    setFilters(newFilters);
    setPage(1);
  };

  const handleClearFilters = () => {
    setFilters({});
    setPage(1);
  };

  const handleRowClick = (tx: Transaction) => {
    setSelectedTransaction(tx);
    setShowDetail(true);
  };

  const handleUpdateSuccess = async () => {
    await queryClient.invalidateQueries({ queryKey: ['transactions'] });
    await queryClient.invalidateQueries({ queryKey: ['transaction'] });
    refetch();
    if (selectedTransaction) {
      try { setSelectedTransaction(await getTransactionById(selectedTransaction.id)); } catch {}
    }
  };

  const handleViewParentTransaction = async (parentTransactionId: number | undefined, combinedOrderId?: string) => {
    try {
      let parentTransaction;
      if (parentTransactionId) {
        parentTransaction = await getTransactionById(parentTransactionId);
      } else if (combinedOrderId) {
        const response = await getTransactions({ search: combinedOrderId, page_size: 1 });
        parentTransaction = response.results?.find((t: Transaction) => t.tx_id === combinedOrderId);
        if (!parentTransaction) { toast.error(`Could not find combined order ${combinedOrderId}`); return; }
      } else { toast.error('No parent transaction information available'); return; }
      setSelectedTransaction(parentTransaction);
    } catch { toast.error('Failed to load combined order details'); }
  };

  const handleToggleSelection = (txId: number, tx: Transaction) => {
    if (tx.is_in_combined_order) { toast.error('Already part of a combined order'); return; }
    if (tx.tx_id?.startsWith('CMB-')) { toast.error('Combined order parents cannot be re-combined'); return; }
    if (!['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status)) {
      toast.error('Only NOT_PROCESSED or PARTIALLY_FULFILLED transactions can be combined.');
      return;
    }
    setSelectedTransactionIds(prev =>
      prev.includes(txId) ? prev.filter(id => id !== txId) : [...prev, txId]
    );
  };

  const handleSelectAll = () => {
    const eligible = orders.filter(
      tx => ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) && !tx.is_in_combined_order && !tx.tx_id?.startsWith('CMB-')
    );
    if (selectedTransactionIds.length === eligible.length && eligible.length > 0) {
      setSelectedTransactionIds([]);
    } else {
      setSelectedTransactionIds(eligible.map(tx => tx.id));
    }
  };

  const handleCombineSubmit = async () => {
    const loadingToast = toast.loading('Creating combined order...');
    try {
      setIsCombining(true);
      const result = await createCombinedOrder({
        transaction_ids: selectedTransactionIds,
        customer_name: combineForm.customer_name,
        customer_phone: combineForm.customer_phone,
        notes: combineForm.notes,
        created_by: 'System',
      });
      toast.dismiss(loadingToast);
      toast.success(`Combined order created! ${result.transaction_count} transactions combined.`);
      setSelectedTransactionIds([]);
      setCombineForm({ customer_name: '', customer_phone: '', notes: '' });
      setShowCombineDialog(false);
      refetch();
    } catch (error: any) {
      toast.dismiss(loadingToast);
      toast.error(extractApiError(error, 'Failed to create combined order'));
    } finally { setIsCombining(false); }
  };

  return (
    <div className="space-y-4 pb-4 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Orders</h1>
          <p className="text-sm text-[rgb(var(--color-muted-foreground))]">Manage and fulfill customer orders</p>
        </div>
        {selectedTransactionIds.length >= 2 && (
          <Button onClick={() => setShowCombineDialog(true)} size="sm" className="gap-1.5">
            <StackSimple className="h-4 w-4" />
            Combine ({selectedTransactionIds.length})
          </Button>
        )}
      </div>

      {/* Stats Row */}
      {isLoading ? (
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {hasProcessorAccess() ? (
            <>
              <div className="stat-card">
                <p className="text-xs font-medium uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">Today's Orders</p>
                <p className="text-2xl font-semibold mt-0.5 text-[rgb(var(--color-foreground))]">{report?.summary?.total_transactions ?? 0}</p>
              </div>
              <div className="stat-card">
                <p className="text-xs font-medium uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">Today's Revenue</p>
                <p className="text-2xl font-semibold mt-0.5 text-[rgb(var(--color-foreground))]">{formatCurrency(report?.summary?.total_amount ?? 0)}</p>
              </div>
            </>
          ) : (
            <>
              <div className="stat-card">
                <p className="text-xs font-medium uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">Fulfilled Today</p>
                <p className="text-2xl font-semibold mt-0.5 text-[rgb(var(--color-foreground))]">{issuerStats?.fulfilled_today ?? 0}</p>
              </div>
              <div className="stat-card">
                <p className="text-xs font-medium uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">Amount Fulfilled</p>
                <p className="text-2xl font-semibold mt-0.5 text-[rgb(var(--color-foreground))]">{formatCurrency(issuerStats?.amount_fulfilled_today ?? 0)}</p>
              </div>
            </>
          )}
        </div>
      )}

      {/* Filters */}
      <AdvancedFilters filters={filters} onFiltersChange={handleFiltersChange} onClear={handleClearFilters} />

      {/* Orders List */}
      <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 overflow-hidden">
        {isLoading ? (
          <div className="p-4 space-y-3">
            {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-xl" />)}
          </div>
        ) : orders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-[rgb(var(--color-muted-foreground))]">
            <StackSimple className="h-12 w-12 mb-3 opacity-30" />
            <p className="font-semibold">No orders found</p>
            <p className="text-sm mt-1">Try adjusting your filters</p>
          </div>
        ) : (
          <>
            {/* Header row — visible on wider screens, hidden on small */}
            <div className="hidden sm:flex items-center px-4 py-2.5 border-b border-[rgb(var(--color-border))]/50 text-[11px] font-medium uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">
              <div className="w-10 shrink-0">
                <input
                  type="checkbox"
                  checked={selectedTransactionIds.length > 0 && selectedTransactionIds.length === orders.filter(tx => ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) && !tx.is_in_combined_order).length}
                  onChange={handleSelectAll}
                  className="h-4 w-4 rounded border-[rgb(var(--color-border))] accent-[rgb(var(--color-primary))]"
                />
              </div>
              <div className="flex-1 min-w-0 grid grid-cols-7 gap-2">
                <span>TX ID</span>
                <span>Amount</span>
                <span>Fulf.</span>
                <span>Rem.</span>
                <span>Sender</span>
                <span>Gateway</span>
                <span>Status</span>
              </div>
              <div className="w-20 shrink-0 text-right">Time</div>
            </div>

            {/* Order rows */}
            <div className="divide-y divide-[rgb(var(--color-border))]/50">
              {orders.map((tx) => {
                const isSelectable = ['NOT_PROCESSED', 'PARTIALLY_FULFILLED'].includes(tx.status) && !tx.is_in_combined_order && !tx.tx_id?.startsWith('CMB-');
                return (
                  <div
                    key={tx.id}
                    className="touch-table-row active:scale-[0.995] transition-transform"
                    onClick={() => handleRowClick(tx)}
                  >
                    {/* Desktop grid layout */}
                    <div className="hidden sm:flex items-center w-full gap-0">
                      <div className="w-10 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedTransactionIds.includes(tx.id)}
                          onChange={() => handleToggleSelection(tx.id, tx)}
                          disabled={!isSelectable}
                          className={cn('h-4 w-4 rounded border-[rgb(var(--color-border))] accent-[rgb(var(--color-primary))]', !isSelectable && 'opacity-30')}
                        />
                      </div>
                      <div className="flex-1 min-w-0 grid grid-cols-7 gap-2 items-center">
                        <div className="flex items-center gap-1.5 text-sm text-[rgb(var(--color-foreground))]">
                          {tx.tx_id}
                          {tx.is_registration && <UserPlus className="w-3.5 h-3.5 text-[rgb(var(--color-secondary))]" />}
                          {tx.is_in_combined_order && <StackSimple className="w-3.5 h-3.5 text-[rgb(var(--color-muted-foreground))]" />}
                        </div>
                        <div className="font-semibold text-[rgb(var(--color-foreground))]">{formatCurrency(tx.amount)}</div>
                        <div className="text-[rgb(var(--color-muted-foreground))]">{formatCurrency(tx.amount_fulfilled || tx.amount_paid || '0')}</div>
                        <div className="text-[rgb(var(--color-muted-foreground))]">{formatCurrency(tx.remaining_amount || '0')}</div>
                        <div className="text-sm text-[rgb(var(--color-muted-foreground))] truncate">{tx.sender_name}</div>
                        <div className={cn('text-sm', tx.gateway_type === 'MPESA_TILL' && 'text-[rgb(var(--color-secondary))]')}>{getGatewayLabel(tx.gateway_type, tx.gateway_name)}</div>
                        <div onClick={(e) => e.stopPropagation()}>
                          <StatusDropdown transaction={tx} onUpdate={refetch} />
                        </div>
                      </div>
                      <div className="w-20 shrink-0 text-right text-xs text-[rgb(var(--color-muted-foreground))]">{formatDate(tx.timestamp)}</div>
                    </div>

                    {/* Mobile/card layout */}
                    <div className="sm:hidden flex items-center gap-3">
                      <div onClick={(e) => e.stopPropagation()} className="shrink-0">
                        <input
                          type="checkbox"
                          checked={selectedTransactionIds.includes(tx.id)}
                          onChange={() => handleToggleSelection(tx.id, tx)}
                          disabled={!isSelectable}
                          className={cn('h-4 w-4 rounded accent-[rgb(var(--color-primary))]', !isSelectable && 'opacity-30')}
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm">{tx.tx_id}</span>
                          {tx.is_registration && <UserPlus className="w-3.5 h-3.5 text-[rgb(var(--color-secondary))]" />}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="font-semibold">{formatCurrency(tx.amount)}</span>
                          <CaretRight className="h-3 w-3 text-[rgb(var(--color-muted-foreground))]" />
                        </div>
                        <div className="text-xs text-[rgb(var(--color-muted-foreground))] truncate">{tx.sender_name}</div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="flex items-center gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
                          <StatusDropdown transaction={tx} onUpdate={refetch} />
                        </div>
                        <div className="text-xs text-[rgb(var(--color-muted-foreground))] mt-0.5">{formatDate(tx.timestamp)}</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Pagination */}
            <div className="px-4 py-3 border-t border-[rgb(var(--color-border))]/50">
              <Pagination
                currentPage={page}
                totalPages={Math.ceil(totalItems / itemsPerPage)}
                totalItems={totalItems}
                itemsPerPage={itemsPerPage}
                onPageChange={setPage}
                onItemsPerPageChange={(n) => { setItemsPerPage(n); setPage(1); }}
              />
            </div>
          </>
        )}
      </div>

      {/* Status summary footer */}
      {!isLoading && orders.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs text-[rgb(var(--color-muted-foreground))]">
          <span>Total: {totalItems} orders</span>
          <span className="opacity-50">|</span>
          <span>Page {page} of {Math.ceil(totalItems / itemsPerPage)}</span>
        </div>
      )}

      {/* Detail Modal */}
      <TransactionDetailModal
        transaction={selectedTransaction}
        open={showDetail}
        onOpenChange={setShowDetail}
        onUpdate={handleUpdateSuccess}
        onViewParentTransaction={handleViewParentTransaction}
      />

      {/* Combine Dialog */}
      <Dialog open={showCombineDialog} onOpenChange={setShowCombineDialog}>
        <DialogContent>
          <DialogHeader onClose={() => setShowCombineDialog(false)}>
            <DialogTitle>Combine {selectedTransactionIds.length} Orders</DialogTitle>
            <DialogDescription>Create a combined order from selected transactions.</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div className="space-y-4">
              <div className="rounded-xl border border-[rgb(var(--color-border))] p-4 max-h-40 overflow-y-auto">
                <div className="space-y-2">
                  {orders.filter(tx => selectedTransactionIds.includes(tx.id)).map(tx => (
                    <div key={tx.id} className="flex justify-between text-sm">
                      <span>{tx.tx_id}</span>
                      <span className="font-semibold">{formatCurrency(tx.amount)}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-[rgb(var(--color-border))] flex justify-between font-bold text-sm">
                  <span>Total:</span>
                  <span>{formatCurrency(orders.filter(tx => selectedTransactionIds.includes(tx.id)).reduce((s, tx) => s + parseFloat(tx.amount), 0))}</span>
                </div>
              </div>
              <div>
                <Label>Customer Name (Optional)</Label>
                <Input value={combineForm.customer_name} onChange={e => setCombineForm(f => ({ ...f, customer_name: e.target.value }))} placeholder="Enter customer name" />
              </div>
              <div>
                <Label>Customer Phone (Optional)</Label>
                <Input value={combineForm.customer_phone} onChange={e => setCombineForm(f => ({ ...f, customer_phone: e.target.value }))} placeholder="e.g., 0712345678" />
              </div>
              <div>
                <Label>Notes (Optional)</Label>
                <Textarea value={combineForm.notes} onChange={e => setCombineForm(f => ({ ...f, notes: e.target.value }))} placeholder="Add any notes" rows={3} />
              </div>
            </div>
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCombineDialog(false)} disabled={isCombining}>Cancel</Button>
            <Button onClick={handleCombineSubmit} disabled={isCombining}>
              {isCombining ? 'Creating...' : 'Create Combined Order'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
