import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Textarea } from '../components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  BarChart3,
  Calendar,
  FileDown,
  Package,
  Loader2,
  DollarSign,
  Save,
  CheckCircle2,
  Edit3,
  Lock,
} from 'lucide-react';
import { api, formatCurrency } from '../services/api';
import { toast } from 'sonner';

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
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [reconciliation, setReconciliation] = useState<StockReconciliation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [editedAdjustments, setEditedAdjustments] = useState<Record<number, Partial<StockAdjustment>>>({});

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
      const errorMsg = error.response?.data?.error || error.message || 'Failed to generate stock report';
      toast.error(errorMsg);
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
      const errorMsg = error.response?.data?.error || error.message || 'Failed to save adjustment';
      toast.error(errorMsg);
    } finally {
      setIsSaving(false);
    }
  };

  const handleConfirmReconciliation = async () => {
    if (!reconciliation) return;

    if (!confirm('Are you sure you want to confirm this reconciliation? This will update inventory and cannot be undone.')) {
      return;
    }

    try {
      setIsConfirming(true);
      await api.post(`/stock-reconciliation/${reconciliation.id}/confirm/`);

      // Refresh reconciliation data
      const response = await api.get(`/stock-reconciliation/${reconciliation.id}/`);
      setReconciliation(response.data);

      toast.success('Stock reconciliation confirmed and applied to inventory');
    } catch (error: any) {
      console.error('Error confirming reconciliation:', error);
      const errorMsg = error.response?.data?.error || error.message || 'Failed to confirm reconciliation';
      toast.error(errorMsg);
    } finally {
      setIsConfirming(false);
    }
  };

  const handleCancelReconciliation = async () => {
    if (!reconciliation) return;

    if (!confirm('Are you sure you want to cancel this draft reconciliation? All unsaved changes will be lost.')) {
      return;
    }

    try {
      setIsCancelling(true);
      await api.delete(`/stock-reconciliation/${reconciliation.id}/cancel/`);

      setReconciliation(null);
      setEditedAdjustments({});

      toast.success('Draft reconciliation cancelled');
    } catch (error: any) {
      console.error('Error cancelling reconciliation:', error);
      const errorMsg = error.response?.data?.error || error.message || 'Failed to cancel reconciliation';
      toast.error(errorMsg);
    } finally {
      setIsCancelling(false);
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
      const errorMsg = error.response?.data?.error || error.message || 'Failed to download Excel file';
      toast.error(errorMsg);
    } finally {
      setIsExporting(false);
    }
  };

  const getStockBadge = (status: string) => {
    switch (status) {
      case 'OUT_OF_STOCK':
        return <Badge variant="destructive">Out of Stock</Badge>;
      case 'LOW_STOCK':
        return <Badge className="bg-orange-500 hover:bg-orange-600">Low Stock</Badge>;
      case 'IN_STOCK':
        return <Badge className="bg-green-500 hover:bg-green-600">In Stock</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

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
            <BarChart3 className="h-8 w-8" />
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
          <CardTitle className="text-base flex items-center gap-2">
            <Calendar className="h-4 w-4" />
            Select Report Date
          </CardTitle>
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
                className="bg-blue-600 hover:bg-blue-700"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Loading...
                  </>
                ) : (
                  <>
                    <Package className="mr-2 h-4 w-4" />
                    Generate Report
                  </>
                )}
              </Button>
              {reconciliation && (
                <>
                  {!isLocked && (
                    <Button
                      onClick={handleCancelReconciliation}
                      disabled={isCancelling}
                      variant="outline"
                      className="border-red-300 text-red-700 hover:bg-red-50"
                    >
                      {isCancelling ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Cancelling...
                        </>
                      ) : (
                        <>
                          Cancel Draft
                        </>
                      )}
                    </Button>
                  )}
                  <Button
                    onClick={handleConfirmReconciliation}
                    disabled={isConfirming || isLocked}
                    className="bg-green-600 hover:bg-green-700"
                  >
                    {isConfirming ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Confirming...
                      </>
                    ) : isLocked ? (
                      <>
                        <Lock className="mr-2 h-4 w-4" />
                        Confirmed
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                        Confirm
                      </>
                    )}
                  </Button>
                  <Button
                    onClick={handleExportXlsx}
                    disabled={isExporting || !isLocked}
                    variant="outline"
                    className="bg-green-50 hover:bg-green-100 border-green-300 text-green-700"
                  >
                    {isExporting ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Exporting...
                      </>
                    ) : (
                      <>
                        <FileDown className="mr-2 h-4 w-4" />
                        Export Excel
                      </>
                    )}
                  </Button>
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

      {/* Summary Card */}
      {reconciliation && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <DollarSign className="h-4 w-4" />
              Inventory Summary
            </CardTitle>
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
                <div className="text-xl font-bold text-blue-600">{totals.totalReplenished}</div>
              </div>
              <div>
                <div className="text-sm text-gray-600">Total Sales (Units)</div>
                <div className="text-xl font-bold text-purple-600">{totals.totalSales}</div>
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
                  <Edit3 className="h-5 w-5 text-blue-600" />
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
                    <TableHead className="text-right text-blue-600">Replenished</TableHead>
                    <TableHead className="text-right text-green-600">Added</TableHead>
                    <TableHead className="text-right text-red-600">Deducted</TableHead>
                    <TableHead className="text-right font-bold">Totals</TableHead>
                    <TableHead className="text-right">Closing</TableHead>
                    <TableHead className="text-right text-purple-600 font-bold">Sales</TableHead>
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
                      <TableRow key={adjustment.id} className={edited ? 'bg-yellow-50 dark:bg-yellow-900/20' : ''}>
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
                        <TableCell className="text-right text-blue-600 font-semibold">
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
                                ? 'text-orange-600 font-bold'
                                : 'font-semibold text-green-600'
                            }
                          >
                            {adjustment.closing_stock}
                          </span>
                        </TableCell>
                        <TableCell className="text-right text-purple-600 font-bold">
                          {edited ? calculatedSales : adjustment.sales}
                        </TableCell>
                        <TableCell className="text-right font-semibold">
                          {formatCurrency(adjustment.cost_price)}
                        </TableCell>
                        <TableCell className="text-right font-semibold text-blue-600">
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
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <>
                                  <Save className="h-4 w-4 mr-1" />
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
    </div>
  );
}
