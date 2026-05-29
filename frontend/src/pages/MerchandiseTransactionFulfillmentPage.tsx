import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, SpinnerGap, Plus, TShirt, Trash } from '@phosphor-icons/react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { formatCurrency, getTransactionById, type MerchandiseCatalogItem, type Transaction } from '@/services/api';
import {
  useFulfillMerchandiseOrder,
  useMerchandiseCatalog,
  useMerchandisePendingOrders,
} from '@/services/queries/merchandise';

type BuilderLine = {
  id: string;
  item_code: string;
  quantity: number;
  color: string;
  size: string;
};

const newBuilderLine = (): BuilderLine => ({
  id: crypto.randomUUID(),
  item_code: '',
  quantity: 1,
  color: '',
  size: '',
});

function getOptions(item: MerchandiseCatalogItem | undefined, optionType: 'COLOR' | 'SIZE'): string[] {
  if (!item) return [];
  return item.options
    .filter((option) => option.option_type === optionType)
    .map((option) => option.value);
}

function getApiErrorMessage(error: unknown, fallback: string): string {
  if (typeof error !== 'object' || error === null || !('response' in error)) {
    return fallback;
  }
  const response = (error as { response?: { data?: unknown } }).response;
  const data = response?.data;
  if (!data) return fallback;
  if (typeof data === 'string') return data;
  if (typeof data === 'object') {
    const values = Object.values(data as Record<string, unknown>).flat().map(String);
    if (values.length) return values.join(', ');
  }
  return fallback;
}

export default function MerchandiseTransactionFulfillmentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const transactionId = Number(id);

  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [loadingTransaction, setLoadingTransaction] = useState(true);
  const [lines, setLines] = useState<BuilderLine[]>([newBuilderLine()]);
  const [notes, setNotes] = useState('');

  const { data: catalog = [], isLoading: isCatalogLoading } = useMerchandiseCatalog();
  const { data: pendingOrders = [], isLoading: isOrdersLoading } = useMerchandisePendingOrders();
  const fulfillMutation = useFulfillMerchandiseOrder();

  useEffect(() => {
    const loadTransaction = async () => {
      if (!transactionId) {
        setLoadingTransaction(false);
        return;
      }
      try {
        const tx = await getTransactionById(transactionId);
        setTransaction(tx);
      } catch {
        toast.error('Failed to load transaction');
      } finally {
        setLoadingTransaction(false);
      }
    };
    loadTransaction();
  }, [transactionId]);

  const pendingOrder = useMemo(() => {
    if (!transaction) return null;
    return pendingOrders.find((order) => order.transaction_id === transaction.tx_id) ?? null;
  }, [pendingOrders, transaction]);

  const itemByCode = useMemo(() => {
    const mapped = new Map<string, MerchandiseCatalogItem>();
    for (const item of catalog) mapped.set(item.code, item);
    return mapped;
  }, [catalog]);

  const lineTotal = (line: BuilderLine): number => {
    const item = itemByCode.get(line.item_code);
    if (!item) return 0;
    return Number(item.unit_price) * line.quantity;
  };

  const totalAmount = lines.reduce((sum, line) => sum + lineTotal(line), 0);
  const expectedAmount = pendingOrder ? Number(pendingOrder.amount) : 0;
  const amountDelta = totalAmount - expectedAmount;
  const hasAmountMismatch = pendingOrder ? Math.abs(amountDelta) > 0.0001 : false;

  const updateLine = (lineId: string, patch: Partial<BuilderLine>) => {
    setLines((current) => current.map((line) => (line.id === lineId ? { ...line, ...patch } : line)));
  };

  const addLine = () => setLines((current) => [...current, newBuilderLine()]);

  const removeLine = (lineId: string) => {
    setLines((current) => (current.length === 1 ? current : current.filter((line) => line.id !== lineId)));
  };

  const submitFulfillment = async () => {
    if (!pendingOrder) return;
    if (hasAmountMismatch) {
      toast.error('Fulfillment total must match amount paid before submitting');
      return;
    }
    try {
      await fulfillMutation.mutateAsync({
        orderId: pendingOrder.id,
        payload: {
          lines: lines.map((line) => {
            const item = itemByCode.get(line.item_code);
            const base = { item_code: line.item_code, quantity: line.quantity };
            if (!item) return base;
            if (item.item_type === 'TSHIRT') return { ...base, color: line.color, size: line.size };
            if (item.item_type === 'HAT') return { ...base, color: line.color };
            return base;
          }),
          notes: notes.trim() || undefined,
        },
      });
      await queryClient.invalidateQueries({ queryKey: ['transactions'] });
      await queryClient.invalidateQueries({ queryKey: ['merchandise', 'stock'] });
      await queryClient.invalidateQueries({ queryKey: ['reports', 'merchandise'] });
      toast.success('Merchandise order fulfilled');
      navigate('/transactions');
    } catch (error) {
      toast.error(getApiErrorMessage(error, 'Failed to fulfill merchandise order'));
    }
  };

  if (loadingTransaction || isCatalogLoading || isOrdersLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <SpinnerGap className="h-8 w-8 animate-spin text-[rgb(var(--color-primary))]" />
        <span className="ml-2 text-gray-600 dark:text-gray-400">Loading merchandise fulfillment...</span>
      </div>
    );
  }

  if (!transaction) {
    return <p className="text-sm text-red-600">Transaction not found.</p>;
  }

  if (!pendingOrder) {
    return (
      <div className="space-y-4">
        <Button variant="outline" onClick={() => navigate('/transactions')}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Orders
        </Button>
        <Alert>
          <AlertDescription>
            No pending merchandise order found for transaction `{transaction.tx_id}`. It may already be fulfilled.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/80 p-4 sm:p-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Fulfill Merchandise</h1>
          <p className="text-gray-600 dark:text-gray-400">
            Transaction {pendingOrder.transaction_id} - Paid {formatCurrency(pendingOrder.amount)}
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate('/transactions')}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      <Card className="border-[rgb(var(--color-border))]">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TShirt className="h-5 w-5 text-[rgb(var(--color-primary))]" />
            Merchandise Builder
          </CardTitle>
          <CardDescription>Build variant-accurate lines with amount parity guardrails.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/70">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead>Colour</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead className="w-[90px]">Qty</TableHead>
                  <TableHead className="text-right">Line Total</TableHead>
                  <TableHead className="w-[48px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((line) => {
                  const item = itemByCode.get(line.item_code);
                  const colorOptions = getOptions(item, 'COLOR');
                  const sizeOptions = getOptions(item, 'SIZE');
                  const needsColor = item?.item_type === 'TSHIRT' || item?.item_type === 'HAT';
                  const needsSize = item?.item_type === 'TSHIRT';

                  return (
                    <TableRow key={line.id}>
                      <TableCell>
                        <Select
                          value={line.item_code}
                          onChange={(e) => updateLine(line.id, { item_code: e.target.value, color: '', size: '' })}
                        >
                          <option value="">Select item</option>
                          {catalog.map((catalogItem) => (
                            <option key={catalogItem.code} value={catalogItem.code}>
                              {catalogItem.name} ({formatCurrency(catalogItem.unit_price)})
                            </option>
                          ))}
                        </Select>
                      </TableCell>
                      <TableCell>
                        {needsColor ? (
                          <Select value={line.color} onChange={(e) => updateLine(line.id, { color: e.target.value })}>
                            <option value="">Select colour</option>
                            {colorOptions.map((color) => (
                              <option key={color} value={color}>
                                {color}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <span className="text-sm text-gray-500">n/a</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {needsSize ? (
                          <Select value={line.size} onChange={(e) => updateLine(line.id, { size: e.target.value })}>
                            <option value="">Select size</option>
                            {sizeOptions.map((size) => (
                              <option key={size} value={size}>
                                {size}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <span className="text-sm text-gray-500">n/a</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          min={1}
                          value={line.quantity}
                          onChange={(e) =>
                            updateLine(line.id, {
                              quantity: Math.max(1, Number.parseInt(e.target.value || '1', 10)),
                            })
                          }
                        />
                      </TableCell>
                      <TableCell className="text-right font-medium">{formatCurrency(lineTotal(line))}</TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => removeLine(line.id)}
                          disabled={lines.length === 1}
                        >
                          <Trash className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-between rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/60 p-3">
            <Button type="button" variant="outline" onClick={addLine}>
              <Plus className="mr-2 h-4 w-4" />
              Add Line
            </Button>
            <div className="text-right">
              <div className="text-xs text-gray-600 dark:text-gray-400">Fulfillment total</div>
              <div className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                {formatCurrency(totalAmount)}
              </div>
            </div>
          </div>

          <Textarea
            placeholder="Optional notes..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
          />

          <Alert className={hasAmountMismatch ? 'border-[rgb(var(--color-primary))/0.3] bg-[rgb(var(--color-accent))] dark:bg-orange-900/20' : 'border-[rgb(var(--color-secondary))/0.3] bg-[rgb(var(--color-secondary))/0.1] dark:bg-emerald-900/20'}>
            <AlertDescription className="text-sm">
              <span className="font-medium">Amount paid:</span> {formatCurrency(expectedAmount)} |{' '}
              <span className="font-medium">Selected total:</span> {formatCurrency(totalAmount)} |{' '}
              <span className={hasAmountMismatch ? 'font-semibold text-[rgb(var(--color-primary))] dark:text-orange-300' : 'font-semibold text-green-700 dark:text-green-300'}>
                {hasAmountMismatch ? `Difference: ${formatCurrency(amountDelta)}` : 'Totals match'}
              </span>
            </AlertDescription>
          </Alert>

          <Button
            type="button"
            onClick={submitFulfillment}
            disabled={fulfillMutation.isPending || hasAmountMismatch}
            className="w-full"
          >
            {fulfillMutation.isPending ? (
              <>
                <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                Fulfilling...
              </>
            ) : (
              'Complete Merchandise Fulfillment'
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
