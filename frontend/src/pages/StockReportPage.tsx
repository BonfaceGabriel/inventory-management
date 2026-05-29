import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Skeleton } from '../components/ui/skeleton';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { StockBadge } from '../components/products/StockBadge';
import { Textarea } from '../components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/ui/alert-dialog';
import {
  ChartBar,
  DownloadSimple,
  Package,
  SpinnerGap,
  FloppyDisk,
  StackPlus,
  CheckCircle,
  PencilSimple,
  Lock,
  ArrowsCounterClockwise,
} from '@phosphor-icons/react';
import {
  api,
  confirmTodayEndOfDayValueReconciliation,
  formatCurrency,
  getTodayEndOfDayValueReconciliation,
  type EndOfDayValueReconciliation,
  updateTodayEndOfDayValueReconciliation,
} from '../services/api';
import { toast } from 'sonner';
import { extractApiError } from '../lib/error-utils';

interface StockAdjustment {
  id: string;
  product_id: number;
  product_code: string;
  product_name: string;
  sku: string;
  opening_stock: number;
  opening_stock_baseline: number | null;
  effective_opening_stock: number;
  has_baseline: boolean;
  quantity_replenished: number;
  quantity_added: number;
  quantity_deducted: number;
  calculated_totals: number;
  closing_stock: number;
  sales: number;
  expected_consignment: number;
  notes: string;
  stock_status: 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK';
  cost_price: number;
  current_price: number;
  stock_value: number;
}

interface StockReconciliation {
  id: string;
  reconciliation_date: string;
  status: 'DRAFT' | 'CONFIRMED';
  adjustments: StockAdjustment[];
  created_at: string;
  confirmed_at: string | null;
  created_by: string | null;
  confirmed_by: string | null;
}

export default function StockReportPage() {
  const today = new Date().toISOString().split('T')[0];
  const [selectedDate, setSelectedDate] = useState(
    today
  );
  const [activeTab, setActiveTab] = useState<'stock' | 'eod'>('stock');
  const [reconciliation, setReconciliation] = useState<StockReconciliation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isSavingAll, setIsSavingAll] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isReverting, setIsReverting] = useState(false);
  const [editedAdjustments, setEditedAdjustments] = useState<Record<number, Partial<StockAdjustment>>>({});
  const [eodReconciliation, setEodReconciliation] = useState<EndOfDayValueReconciliation | null>(null);
  const [isLoadingEod, setIsLoadingEod] = useState(false);
  const [isSavingEod, setIsSavingEod] = useState(false);
  const [isConfirmingEod, setIsConfirmingEod] = useState(false);
  const [showConfirmReconciliationDialog, setShowConfirmReconciliationDialog] = useState(false);
  const [showCancelReconciliationDialog, setShowCancelReconciliationDialog] = useState(false);
  const [showRevertReconciliationDialog, setShowRevertReconciliationDialog] = useState(false);
  const [showConfirmEodDialog, setShowConfirmEodDialog] = useState(false);
  const [eodInputs, setEodInputs] = useState({
    stock_value: '0',
    bk_stock: '0',
    duplicated: '0',
    hq_value: '0',
    kitengela_value: '0',
    kitui_value: '0',
    nakuru_value: '0',
  });

  const handleGenerateReport = async () => {
    if (!selectedDate) {
      toast.error('Please select a date');
      return;
    }

    try {
      setIsLoading(true);
      const response = await api.post('/stock-reconciliation/create/', {
        reconciliation_date: selectedDate
      });
      console.log('Reconciliation Response:', response.data);
      console.log('First Adjustment:', response.data.adjustments?.[0]);
      setReconciliation(response.data);
      setEditedAdjustments({});
      toast.success(`Stock report generated for ${selectedDate}`);
    } catch (error: any) {
      console.error('Error generating stock report:', error);
      toast.error(extractApiError(error, 'Failed to generate stock report'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleCellEdit = (productId: number, field: 'quantity_added' | 'quantity_deducted' | 'notes', value: string | number) => {
    setEditedAdjustments(prev => ({
      ...prev,
      [productId]: {
        ...prev[productId],
        [field]: field === 'notes' ? value : parseInt(value as string) || 0
      }
    }));
  };

  const handleSaveAdjustment = async (adjustment: StockAdjustment) => {
    if (!reconciliation) return;

    const edited = editedAdjustments[adjustment.product_id];
    if (!edited) {
      toast.info('No changes to save');
      return;
    }

    try {
      setIsSaving(true);
      await api.patch(`/stock-reconciliation/${reconciliation.id}/adjust/`, {
        product_id: adjustment.product_id,
        quantity_added: edited.quantity_added ?? adjustment.quantity_added,
        quantity_deducted: edited.quantity_deducted ?? adjustment.quantity_deducted,
        notes: edited.notes ?? adjustment.notes
      });

      // Refresh reconciliation data
      const response = await api.get(`/stock-reconciliation/${reconciliation.id}/`);
      setReconciliation(response.data);

      // Clear edited state for this product
      setEditedAdjustments(prev => {
        const newState = { ...prev };
        delete newState[adjustment.product_id];
        return newState;
      });

      toast.success(`Saved adjustments for ${adjustment.product_name}`);
    } catch (error: any) {
      console.error('Error saving adjustment:', error);
      toast.error(extractApiError(error, 'Failed to save adjustment'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAllAdjustments = async () => {
    if (!reconciliation) return;

    const editedProductIds = Object.keys(editedAdjustments);
    if (editedProductIds.length === 0) {
      toast.info('No changes to save');
      return;
    }

    try {
      setIsSavingAll(true);

      // Build the adjustments array from edited items
      const adjustments = editedProductIds.map(productIdStr => {
        const productId = parseInt(productIdStr);
        const originalAdj = reconciliation.adjustments.find(a => a.product_id === productId);
        const edited = editedAdjustments[productId];
        return {
          product_id: productId,
          quantity_added: edited.quantity_added ?? originalAdj?.quantity_added ?? 0,
          quantity_deducted: edited.quantity_deducted ?? originalAdj?.quantity_deducted ?? 0,
          notes: edited.notes ?? originalAdj?.notes ?? ''
        };
      });

      await api.post(`/stock-reconciliation/${reconciliation.id}/adjust-bulk/`, {
        adjustments
      });

      // Refresh reconciliation data
      const response = await api.get(`/stock-reconciliation/${reconciliation.id}/`);
      setReconciliation(response.data);

      // Clear all edited states
      setEditedAdjustments({});

      toast.success(`Saved ${adjustments.length} adjustment(s)`);
    } catch (error: any) {
      console.error('Error saving all adjustments:', error);
      toast.error(extractApiError(error, 'Failed to save adjustments'));
    } finally {
      setIsSavingAll(false);
    }
  };

  const handleConfirmReconciliation = () => {
    setShowConfirmReconciliationDialog(true);
  };

  const executeConfirmReconciliation = async () => {
    if (!reconciliation) return;

    setShowConfirmReconciliationDialog(false);

    try {
      setIsConfirming(true);
      await api.post(`/stock-reconciliation/${reconciliation.id}/confirm/`);

      // Refresh reconciliation data
      const response = await api.get(`/stock-reconciliation/${reconciliation.id}/`);
      setReconciliation(response.data);

      toast.success('Stock reconciliation confirmed and applied to inventory');
    } catch (error: any) {
      console.error('Error confirming reconciliation:', error);
      toast.error(extractApiError(error, 'Failed to confirm reconciliation'));
    } finally {
      setIsConfirming(false);
    }
  };

  const handleCancelReconciliation = () => {
    setShowCancelReconciliationDialog(true);
  };

  const executeCancelReconciliation = async () => {
    if (!reconciliation) return;

    setShowCancelReconciliationDialog(false);

    try {
      setIsCancelling(true);
      await api.delete(`/stock-reconciliation/${reconciliation.id}/cancel/`);

      setReconciliation(null);
      setEditedAdjustments({});

      toast.success('Draft reconciliation cancelled');
    } catch (error: any) {
      console.error('Error cancelling reconciliation:', error);
      toast.error(extractApiError(error, 'Failed to cancel reconciliation'));
    } finally {
      setIsCancelling(false);
    }
  };

  const handleRevertReconciliation = () => {
    setShowRevertReconciliationDialog(true);
  };

  const executeRevertReconciliation = async () => {
    if (!reconciliation) return;

    setShowRevertReconciliationDialog(false);

    try {
      setIsReverting(true);
      const response = await api.post(`/stock-reconciliation/${reconciliation.id}/revert/`);

      // Refresh reconciliation data
      const refreshedResponse = await api.get(`/stock-reconciliation/${reconciliation.id}/`);
      setReconciliation(refreshedResponse.data);
      setEditedAdjustments({});

      toast.success(response.data.message || 'Reconciliation reverted to DRAFT');
    } catch (error: any) {
      console.error('Error reverting reconciliation:', error);
      toast.error(extractApiError(error, 'Failed to revert reconciliation'));
    } finally {
      setIsReverting(false);
    }
  };

  const handleExportXlsx = async () => {
    if (!selectedDate) {
      toast.error('Please select a date');
      return;
    }

    try {
      setIsExporting(true);
      const response = await api.get('/reports/stock/historical/xlsx/', {
        params: { date: selectedDate },
        responseType: 'blob',
      });

      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `Stock_Report_${selectedDate}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      toast.success('Excel file downloaded successfully');
    } catch (error: any) {
      console.error('Error downloading XLSX:', error);
      toast.error(extractApiError(error, 'Failed to download Excel file'));
    } finally {
      setIsExporting(false);
    }
  };

  const loadEodValueReconciliation = async () => {
    try {
      setIsLoadingEod(true);
      const data = await getTodayEndOfDayValueReconciliation();
      setEodReconciliation(data);
      setEodInputs({
        stock_value: data.stock_value || '0',
        bk_stock: data.bk_stock || '0',
        duplicated: data.duplicated || '0',
        hq_value: data.hq_value || '0',
        kitengela_value: data.kitengela_value || '0',
        kitui_value: data.kitui_value || '0',
        nakuru_value: data.nakuru_value || '0',
      });
    } catch (error: any) {
      toast.error(extractApiError(error, 'Failed to load value reconciliation'));
    } finally {
      setIsLoadingEod(false);
    }
  };

  const parseMoney = (value: string) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const handleSaveEodDraft = async () => {
    if (selectedDate !== today) {
      toast.error('Value reconciliation is editable only for today');
      return;
    }

    try {
      setIsSavingEod(true);
      const updated = await updateTodayEndOfDayValueReconciliation({
        stock_value: parseMoney(eodInputs.stock_value),
        bk_stock: parseMoney(eodInputs.bk_stock),
        duplicated: parseMoney(eodInputs.duplicated),
        hq_value: parseMoney(eodInputs.hq_value),
        kitengela_value: parseMoney(eodInputs.kitengela_value),
        kitui_value: parseMoney(eodInputs.kitui_value),
        nakuru_value: parseMoney(eodInputs.nakuru_value),
      });
      setEodReconciliation(updated);
      toast.success('Value reconciliation draft saved');
    } catch (error: any) {
      toast.error(extractApiError(error, 'Failed to save value reconciliation'));
    } finally {
      setIsSavingEod(false);
    }
  };

  const handleConfirmEod = () => {
    if (selectedDate !== today) {
      toast.error('Only today can be confirmed');
      return;
    }
    setShowConfirmEodDialog(true);
  };

  const executeConfirmEod = async () => {
    setShowConfirmEodDialog(false);
    try {
      setIsConfirmingEod(true);
      const response = await confirmTodayEndOfDayValueReconciliation();
      setEodReconciliation(response.reconciliation);
      toast.success(response.message);
    } catch (error: any) {
      toast.error(extractApiError(error, 'Failed to confirm value reconciliation'));
    } finally {
      setIsConfirmingEod(false);
    }
  };

  const getStockBadge = (status: string) => <StockBadge status={status} />;

  const isEdited = (productId: number) => {
    return productId in editedAdjustments;
  };

  const getDisplayValue = (adjustment: StockAdjustment, field: 'quantity_added' | 'quantity_deducted' | 'notes') => {
    const edited = editedAdjustments[adjustment.product_id];
    return edited?.[field] ?? adjustment[field];
  };

  const isLocked = reconciliation?.status === 'CONFIRMED';

  // Calculate totals
  const calculateTotals = () => {
    if (!reconciliation) return { inventoryValue: 0, totalSales: 0, totalReplenished: 0 };
    return reconciliation.adjustments.reduce((acc, adj) => {
      return {
        inventoryValue: acc.inventoryValue + Number(adj.stock_value || 0),
        totalSales: acc.totalSales + (adj.sales || 0),
        totalReplenished: acc.totalReplenished + (adj.quantity_replenished || 0),
      };
    }, { inventoryValue: 0, totalSales: 0, totalReplenished: 0 });
  };

  const totals = calculateTotals();

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ChartBar className="h-8 w-8" />
            Stock Reconciliation
          </h1>
          <p className="text-gray-600 mt-1">
            Generate report, enter adjustments, and confirm to update inventory
          </p>
        </div>
      </div>

      {/* Date Selection */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Select Report Date</CardTitle>
          <CardDescription>
            Choose a date to create or view stock reconciliation
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label htmlFor="report-date">Report Date</Label>
              <Input
                id="report-date"
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                max={new Date().toISOString().split('T')[0]}
                className="mt-1"
                disabled={isLoading}
              />
            </div>
            <div className="flex items-end gap-2">
              <Button
                onClick={handleGenerateReport}
                disabled={!selectedDate || isLoading}
                className="bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]"
              >
                {isLoading ? (
                  <>
                    <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Package className="mr-2 h-4 w-4" />
                    Generate Report
                  </>
                )}
              </Button>
              <Button
                onClick={loadEodValueReconciliation}
                disabled={isLoadingEod || selectedDate !== today}
                variant="outline"
              >
                {isLoadingEod ? (
                  <>
                    <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                    Loading Value Recon...
                  </>
                ) : (
                  'Load Value Recon'
                )}
              </Button>
              {reconciliation && (
                <>
                  {!isLocked && (
                    <>
                      <Button
                        onClick={handleSaveAllAdjustments}
                        disabled={isSavingAll || Object.keys(editedAdjustments).length === 0}
                        className="bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]"
                      >
                        {isSavingAll ? (
                          <>
                            <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                            Saving All...
                          </>
                        ) : (
                          <>
                            <StackPlus className="mr-2 h-4 w-4" />
                            Save All ({Object.keys(editedAdjustments).length})
                          </>
                        )}
                      </Button>
                      <Button
                        onClick={handleCancelReconciliation}
                        disabled={isCancelling}
                        variant="outline"
                        className="border-[rgb(var(--color-destructive))]/[0.3] text-red-700 hover:bg-[rgb(var(--color-destructive))]/[0.1]"
                      >
                        {isCancelling ? (
                          <>
                            <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                            Cancelling...
                          </>
                        ) : (
                          <>
                            Cancel Draft
                          </>
                        )}
                      </Button>
                    </>
                  )}
                  <Button
                    onClick={handleConfirmReconciliation}
                    disabled={isConfirming || isLocked}
                    className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/[0.85]"
                  >
                    {isConfirming ? (
                      <>
                        <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                        Confirming...
                      </>
                    ) : isLocked ? (
                      <>
                        <Lock className="mr-2 h-4 w-4" />
                        Confirmed
                      </>
                    ) : (
                      <>
                        <CheckCircle className="mr-2 h-4 w-4" />
                        Confirm
                      </>
                    )}
                  </Button>
                  <Button
                    onClick={handleExportXlsx}
                    disabled={isExporting || !isLocked}
                    variant="outline"
                    className="bg-[rgb(var(--color-secondary))]/[0.1] hover:bg-green-100 border-[rgb(var(--color-secondary))]/[0.3] text-green-700"
                  >
                    {isExporting ? (
                      <>
                        <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                        Exporting...
                      </>
                    ) : (
                      <>
                        <DownloadSimple className="mr-2 h-4 w-4" />
                        Export Excel
                      </>
                    )}
                  </Button>
                  {isLocked && (
                    <Button
                      onClick={handleRevertReconciliation}
                      disabled={isReverting}
                      variant="outline"
                      className="border-[rgb(var(--color-primary))]/[0.3] text-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-accent))]"
                    >
                      {isReverting ? (
                        <>
                          <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                          Reverting...
                        </>
                      ) : (
                        <>
                          <ArrowsCounterClockwise className="mr-2 h-4 w-4" />
                          Revert
                        </>
                      )}
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
          {reconciliation && (
            <div className="mt-4 flex items-center gap-4">
              <div className="text-sm text-gray-600">
                Status: <Badge variant={isLocked ? 'default' : 'secondary'}>{reconciliation.status}</Badge>
              </div>
              {isLocked && (
                <div className="text-sm text-gray-600">
                  Confirmed by {reconciliation.confirmed_by} on {new Date(reconciliation.confirmed_at!).toLocaleString()}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const nextTab = value as 'stock' | 'eod';
          setActiveTab(nextTab);
          if (nextTab === 'eod' && !eodReconciliation) {
            loadEodValueReconciliation();
          }
        }}
      >
        <TabsList className="mb-6">
          <TabsTrigger value="stock">Stock Reconciliation</TabsTrigger>
          <TabsTrigger value="eod">End-of-Day Reconciliation</TabsTrigger>
        </TabsList>

        <TabsContent value="stock">
      {/* Summary Card */}
      {reconciliation && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-base">Inventory Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <div className="text-sm text-gray-600">Date</div>
                <div className="text-xl font-bold">{reconciliation.reconciliation_date}</div>
              </div>
              <div>
                <div className="text-sm text-gray-600">Total Products</div>
                <div className="text-xl font-bold">{reconciliation.adjustments.length}</div>
              </div>
              <div>
                <div className="text-sm text-gray-600">Total Replenished</div>
                <div className="text-xl font-bold text-[rgb(var(--color-primary))]">{totals.totalReplenished}</div>
              </div>
              <div>
                <div className="text-sm text-gray-600">Total Sales (Units)</div>
                <div className="text-xl font-bold text-[rgb(var(--color-secondary))]">{totals.totalSales}</div>
              </div>
              <div>
                <div className="text-sm text-gray-600">Closing Inventory Value</div>
                <div className="text-xl font-bold text-green-600">
                  {formatCurrency(totals.inventoryValue)}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Reconciliation Table */}
      {reconciliation && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {isLocked ? (
                <>
                  <Lock className="h-5 w-5 text-green-600" />
                  Stock Report (Confirmed - Read Only)
                </>
              ) : (
                <>
                  <PencilSimple className="h-5 w-5 text-[rgb(var(--color-primary))]" />
                  Stock Report (Editable)
                </>
              )}
            </CardTitle>
            <CardDescription>
              {isLocked
                ? 'This reconciliation has been confirmed. Export to download the report.'
                : 'Enter Added/Deducted quantities and notes for each product, then click Save. When done, click Confirm to apply changes to inventory.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>SKU</TableHead>
                    <TableHead>Product Name</TableHead>
                    <TableHead className="text-right">Opening</TableHead>
                    <TableHead className="text-right text-[rgb(var(--color-primary))]">Replenished</TableHead>
                    <TableHead className="text-right text-green-600">Added</TableHead>
                    <TableHead className="text-right text-red-600">Deducted</TableHead>
                    <TableHead className="text-right font-bold">Totals</TableHead>
                    <TableHead className="text-right">Closing</TableHead>
                    <TableHead className="text-right text-[rgb(var(--color-secondary))] font-bold">Sales</TableHead>
                    <TableHead className="text-right text-[rgb(var(--color-primary))] font-bold">Expected Consignment</TableHead>
                    <TableHead className="text-right">Unit Cost</TableHead>
                    <TableHead className="text-right">Stock Value</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Notes</TableHead>
                    {!isLocked && <TableHead>Action</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reconciliation.adjustments.map((adjustment) => {
                    const edited = isEdited(adjustment.product_id);
                    const added = getDisplayValue(adjustment, 'quantity_added');
                    const deducted = getDisplayValue(adjustment, 'quantity_deducted');

                    // Calculate totals and sales when editing
                    const effectiveOpening = adjustment.effective_opening_stock;
                    const replenished = adjustment.quantity_replenished;
                    const addedNum = typeof added === 'number' ? added : 0;
                    const deductedNum = typeof deducted === 'number' ? deducted : 0;
                    const calculatedTotals = effectiveOpening + replenished + addedNum - deductedNum;
                    const calculatedSales = calculatedTotals - adjustment.closing_stock;

                    return (
                      <TableRow key={adjustment.id} className={edited ? 'bg-[rgb(var(--color-accent))] dark:bg-yellow-900/20' : ''}>
                        <TableCell className="font-mono text-sm">{adjustment.sku || '-'}</TableCell>
                        <TableCell>
                          <div>
                            <div className="font-medium">{adjustment.product_name}</div>
                            <div className="text-sm text-gray-500">{adjustment.product_code}</div>
                          </div>
                        </TableCell>
                        <TableCell className="text-right text-gray-600 font-semibold">
                          {adjustment.has_baseline ? (
                            <span title={`Baseline: ${adjustment.opening_stock_baseline}, Calculated: ${adjustment.opening_stock}`}>
                              {effectiveOpening}*
                            </span>
                          ) : (
                            effectiveOpening
                          )}
                        </TableCell>
                        <TableCell className="text-right text-[rgb(var(--color-primary))] font-semibold">
                          {replenished}
                        </TableCell>
                        <TableCell className="text-right">
                          {isLocked ? (
                            <span className="text-green-600 font-semibold">{adjustment.quantity_added}</span>
                          ) : (
                            <Input
                              type="number"
                              min="0"
                              value={added}
                              onChange={(e) => handleCellEdit(adjustment.product_id, 'quantity_added', e.target.value)}
                              className="w-16 text-right text-green-600 font-semibold"
                            />
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {isLocked ? (
                            <span className="text-red-600 font-semibold">{adjustment.quantity_deducted}</span>
                          ) : (
                            <Input
                              type="number"
                              min="0"
                              value={deducted}
                              onChange={(e) => handleCellEdit(adjustment.product_id, 'quantity_deducted', e.target.value)}
                              className="w-16 text-right text-red-600 font-semibold"
                            />
                          )}
                        </TableCell>
                        <TableCell className="text-right font-bold">
                          {edited ? calculatedTotals : adjustment.calculated_totals}
                        </TableCell>
                        <TableCell className="text-right">
                          <span
                            className={
                              adjustment.closing_stock <= 0
                                ? 'text-red-600 font-bold'
                                : adjustment.closing_stock <= 10
                                ? 'text-[rgb(var(--color-primary))] font-bold'
                                : 'font-semibold text-green-600'
                            }
                          >
                            {adjustment.closing_stock}
                          </span>
                        </TableCell>
                        <TableCell className="text-right text-[rgb(var(--color-secondary))] font-bold">
                          {edited ? calculatedSales : adjustment.sales}
                        </TableCell>
                        <TableCell className="text-right text-[rgb(var(--color-primary))] font-bold">
                          {adjustment.expected_consignment ?? 0}
                        </TableCell>
                        <TableCell className="text-right font-semibold">
                          {formatCurrency(adjustment.cost_price)}
                        </TableCell>
                        <TableCell className="text-right font-semibold text-[rgb(var(--color-primary))]">
                          {formatCurrency(adjustment.stock_value)}
                        </TableCell>
                        <TableCell>{getStockBadge(adjustment.stock_status)}</TableCell>
                        <TableCell>
                          {isLocked ? (
                            <span className="text-sm text-gray-600">{adjustment.notes || '-'}</span>
                          ) : (
                            <Textarea
                              value={getDisplayValue(adjustment, 'notes')}
                              onChange={(e) => handleCellEdit(adjustment.product_id, 'notes', e.target.value)}
                              className="min-w-[150px] text-sm"
                              rows={2}
                              placeholder="Reason..."
                            />
                          )}
                        </TableCell>
                        {!isLocked && (
                          <TableCell>
                            <Button
                              size="sm"
                              onClick={() => handleSaveAdjustment(adjustment)}
                              disabled={!edited || isSaving}
                              variant={edited ? 'default' : 'outline'}
                            >
                              {isSaving ? (
                                <SpinnerGap className="h-4 w-4 animate-spin" />
                              ) : (
                                <>
                                  <FloppyDisk className="h-4 w-4 mr-1" />
                                  Save
                                </>
                              )}
                            </Button>
                          </TableCell>
                        )}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Placeholder when no report */}
      {!reconciliation && !isLoading && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Package className="h-16 w-16 text-gray-300 mb-4" />
            <p className="text-gray-600 mb-2 font-medium">No Reconciliation Generated</p>
            <p className="text-sm text-gray-500 text-center max-w-md">
              Select a date above and click "Generate Report" to start stock reconciliation.
              You can then edit Added/Deducted quantities and confirm to update inventory.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Loading skeleton while report generates */}
      {!reconciliation && isLoading && (
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
              {[...Array(5)].map((_, i) => (
                <div key={i}>
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-7 w-24 mt-2" />
                </div>
              ))}
            </div>
            <div className="space-y-3">
              {[...Array(6)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      )}
        </TabsContent>

        <TabsContent value="eod">
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>End-of-Day Reconciliation (X - Y - Z)</CardTitle>
              <CardDescription>
                X is system-derived from stock report values; Y and Z are editable for today only; confirm locks the record.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {selectedDate !== today && (
                <div className="rounded-md border border-[rgb(var(--color-primary))]/[0.3] bg-[rgb(var(--color-accent))] p-3 text-sm text-[rgb(var(--color-primary))]">
                  This tab is editable only for today ({today}). Switch the selected date to today to save or confirm.
                </div>
              )}

              {!eodReconciliation ? (
                <div className="text-sm text-muted-foreground">
                  Click "Load Value Recon" to initialize today&apos;s record.
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                    <div>
                      <Label>Opening Stock Value</Label>
                      <Input value={formatCurrency(eodReconciliation.opening_stock_value)} disabled />
                    </div>
                    <div>
                      <Label>Replenished Value</Label>
                      <Input value={formatCurrency(eodReconciliation.replenished_value)} disabled />
                    </div>
                    <div>
                      <Label>Sales Value</Label>
                      <Input value={formatCurrency(eodReconciliation.sales_value)} disabled />
                    </div>
                    <div>
                      <Label>X Value</Label>
                      <Input value={formatCurrency(eodReconciliation.x_value)} disabled />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                    <div>
                      <Label>Stock Value (Y)</Label>
                      <Input
                        type="number"
                        value={eodInputs.stock_value}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, stock_value: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                    <div>
                      <Label>BK&apos;s Stock (Y)</Label>
                      <Input
                        type="number"
                        value={eodInputs.bk_stock}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, bk_stock: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                    <div>
                      <Label>Duplicated (Y)</Label>
                      <Input
                        type="number"
                        value={eodInputs.duplicated}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, duplicated: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                    <div>
                      <Label>HQ (Z)</Label>
                      <Input
                        type="number"
                        value={eodInputs.hq_value}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, hq_value: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                    <div>
                      <Label>Kitengela (Z)</Label>
                      <Input
                        type="number"
                        value={eodInputs.kitengela_value}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, kitengela_value: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                    <div>
                      <Label>Kitui (Z)</Label>
                      <Input
                        type="number"
                        value={eodInputs.kitui_value}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, kitui_value: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                    <div>
                      <Label>Nakuru (Z)</Label>
                      <Input
                        type="number"
                        value={eodInputs.nakuru_value}
                        onChange={(e) => setEodInputs((prev) => ({ ...prev, nakuru_value: e.target.value }))}
                        disabled={eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                    <div>
                      <Label>Y Value</Label>
                      <Input value={formatCurrency(eodReconciliation.y_value)} disabled />
                    </div>
                    <div>
                      <Label>Z Value</Label>
                      <Input value={formatCurrency(eodReconciliation.z_value)} disabled />
                    </div>
                    <div>
                      <Label>V = X - Y - Z</Label>
                      <Input value={formatCurrency(eodReconciliation.v_value)} disabled />
                    </div>
                    <div>
                      <Label>Threshold (V &lt;= 100)</Label>
                      <div className="pt-2">
                        <Badge variant={eodReconciliation.is_within_threshold ? 'default' : 'destructive'}>
                          {eodReconciliation.is_within_threshold ? 'Within Threshold' : 'Above Threshold'}
                        </Badge>
                      </div>
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      onClick={handleSaveEodDraft}
                      disabled={isSavingEod || eodReconciliation.status === 'CONFIRMED' || selectedDate !== today}
                    >
                      {isSavingEod ? (
                        <>
                          <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        'Save Draft'
                      )}
                    </Button>
                    <Button
                      onClick={handleConfirmEod}
                      disabled={
                        isConfirmingEod ||
                        eodReconciliation.status === 'CONFIRMED' ||
                        selectedDate !== today
                      }
                      className="bg-[rgb(var(--color-secondary))] hover:bg-[rgb(var(--color-secondary))]/[0.85]"
                    >
                      {isConfirmingEod ? (
                        <>
                          <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
                          Confirming...
                        </>
                      ) : (
                        'Confirm'
                      )}
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Confirm Reconciliation Dialog */}
      <AlertDialog open={showConfirmReconciliationDialog} onOpenChange={setShowConfirmReconciliationDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Reconciliation</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to confirm this reconciliation? This will update inventory and cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setShowConfirmReconciliationDialog(false)}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={executeConfirmReconciliation}>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cancel Reconciliation Dialog */}
      <AlertDialog open={showCancelReconciliationDialog} onOpenChange={setShowCancelReconciliationDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel Reconciliation</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to cancel this draft reconciliation? All unsaved changes will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setShowCancelReconciliationDialog(false)}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={executeCancelReconciliation}>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Revert Reconciliation Dialog */}
      <AlertDialog open={showRevertReconciliationDialog} onOpenChange={setShowRevertReconciliationDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revert Reconciliation</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to REVERT this confirmed reconciliation?
              {'\n\n'}
              This will:
              {'\n'}- Reverse all inventory changes made during confirmation
              {'\n'}- Reset the reconciliation to DRAFT status
              {'\n'}- Allow you to re-edit and re-confirm
              {'\n\n'}
              This action is logged for audit purposes.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setShowRevertReconciliationDialog(false)}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={executeRevertReconciliation}>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm EOD Dialog */}
      <AlertDialog open={showConfirmEodDialog} onOpenChange={setShowConfirmEodDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Value Reconciliation</AlertDialogTitle>
            <AlertDialogDescription>
              Confirm value reconciliation? This will lock today's X - Y - Z record.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setShowConfirmEodDialog(false)}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={executeConfirmEod}>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
