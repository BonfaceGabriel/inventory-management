import { useState } from 'react';
import { DownloadSimple, CheckCircle, XCircle, Warning } from '@phosphor-icons/react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useDailyReconciliationV2 } from '@/services/queries/reports';
import { downloadUnifiedReport, formatCurrency } from '@/services/api';
import { toast } from 'sonner';

export default function ReportsPage() {
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [isExporting, setIsExporting] = useState(false);
  const { data: reconciliationV2, isLoading: isLoadingV2 } = useDailyReconciliationV2(selectedDate);

  const handleDownloadReport = async () => {
    const loadingToast = toast.loading('Generating report...');
    try {
      setIsExporting(true);
      await downloadUnifiedReport(selectedDate);
      toast.dismiss(loadingToast);
      toast.success('Report downloaded successfully');
    } catch (error) {
      console.error('Report export error:', error);
      toast.dismiss(loadingToast);
      toast.error('Failed to download report');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="relative overflow-hidden rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/80 p-6 shadow-sm">
        <div className="pointer-events-none absolute -right-16 -top-16 h-44 w-44 rounded-full bg-[rgb(var(--color-secondary))]/15 blur-3xl" />
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Reports Console</h1>
        <p className="text-gray-600 dark:text-gray-400">
          Reconciliation intelligence, exception tracing, and daily export.
        </p>
      </div>

      {/* Date Selection */}
      <Card className="border-[rgb(var(--color-border))]">
        <CardHeader>
          <CardTitle>Select Date</CardTitle>
          <CardDescription>Choose a day and generate a reconciled financial snapshot.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 md:flex-row md:items-end">
            <div className="flex-1 max-w-xs">
              <Label htmlFor="date">Report Date</Label>
              <Input
                id="date"
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                max={new Date().toISOString().split('T')[0]}
              />
            </div>
            <div className="flex items-end gap-2">
              <Button onClick={handleDownloadReport} disabled={isExporting} variant="default" className="min-w-44">
                <DownloadSimple className="mr-2 h-4 w-4" />
                {isExporting ? 'Preparing export...' : 'Download Report'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Daily Reconciliation X/Y Formula */}
      {isLoadingV2 ? (
        <div className="grid gap-4 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-10 w-32" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : reconciliationV2 ? (
        <>
          {/* X, Y, and Result Cards */}
          <div className="grid gap-4 md:grid-cols-3">
            {/* X Value Card */}
            <Card className="border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-[rgb(var(--color-primary))]">
                  X Value
                </CardTitle>
                <CardDescription className="text-xs">
                  Paybill - Unused + PDQ + Previous - Sales
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className={`text-3xl font-bold ${reconciliationV2.x_value >= 0 ? 'text-[rgb(var(--color-primary))]' : 'text-red-600'}`}>
                  {formatCurrency(reconciliationV2.x_value)}
                </div>
                <div className="mt-2 text-xs text-gray-500 space-y-1">
                  <div className="flex justify-between">
                    <span>+ Mpesa Paybill:</span>
                    <span>{formatCurrency(reconciliationV2.x_formula.mpesa_paybill)}</span>
                  </div>
                  <div className="flex justify-between text-red-500">
                    <span>- Unused:</span>
                    <span>{formatCurrency(reconciliationV2.x_formula.unused)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>+ PDQ:</span>
                    <span>{formatCurrency(reconciliationV2.x_formula.pdq)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>+ Previous:</span>
                    <span>{formatCurrency(reconciliationV2.x_formula.previous)}</span>
                  </div>
                  <div className="flex justify-between text-red-500">
                    <span>- Sales:</span>
                    <span>{formatCurrency(reconciliationV2.x_formula.sales)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Y Value Card */}
            <Card className="border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-[rgb(var(--color-secondary))]">
                  Y Value
                </CardTitle>
                <CardDescription className="text-xs">
                  Till - Credit - KITS
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className={`text-3xl font-bold ${reconciliationV2.y_value >= 0 ? 'text-[rgb(var(--color-secondary))]' : 'text-red-600'}`}>
                  {formatCurrency(reconciliationV2.y_value)}
                </div>
                <div className="mt-2 text-xs text-gray-500 space-y-1">
                  <div className="flex justify-between">
                    <span>+ Till:</span>
                    <span>{formatCurrency(reconciliationV2.y_formula.till)}</span>
                  </div>
                  <div className="flex justify-between text-red-500">
                    <span>- Credit:</span>
                    <span>{formatCurrency(reconciliationV2.y_formula.credit)}</span>
                  </div>
                  <div className="flex justify-between text-red-500">
                    <span>- KITS:</span>
                    <span>{formatCurrency(reconciliationV2.y_formula.kits)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* X + Y Result Card */}
            <Card className={reconciliationV2.is_balanced
              ? 'border-[rgb(var(--color-secondary))/0.3] bg-[rgb(var(--color-secondary))/0.1] dark:bg-emerald-900/20 dark:border-emerald-500/60'
              : 'border-[rgb(var(--color-destructive))/0.3] bg-[rgb(var(--color-destructive))/0.1] dark:bg-red-900/20 dark:border-red-600'
            }>
              <CardHeader className="pb-2">
                <CardTitle className={`text-sm font-medium flex items-center gap-2 ${
                  reconciliationV2.is_balanced ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                }`}>
                  {reconciliationV2.is_balanced ? (
                    <CheckCircle className="h-5 w-5" />
                  ) : (
                    <XCircle className="h-5 w-5" />
                  )}
                  X + Y Result
                </CardTitle>
                <CardDescription className="text-xs">
                  {reconciliationV2.is_balanced ? 'Books are balanced!' : 'Discrepancy detected'}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className={`text-4xl font-bold ${
                  reconciliationV2.is_balanced ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                }`}>
                  {formatCurrency(reconciliationV2.result)}
                </div>
                <div className="mt-2 text-sm">
                  {reconciliationV2.is_balanced ? (
                    <span className="text-green-600 dark:text-green-400 font-medium">
                      Reconciliation successful
                    </span>
                  ) : (
                    <span className="text-red-600 dark:text-red-400 font-medium">
                      Review required - {reconciliationV2.result > 0 ? 'Overage' : 'Shortage'} of {formatCurrency(Math.abs(reconciliationV2.result))}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* CMB Exception Alert */}
          {reconciliationV2.cmb_exception && (
            <Alert className="border-[rgb(var(--color-primary))/0.3] bg-[rgb(var(--color-accent))] dark:bg-orange-900/20">
              <Warning className="h-4 w-4 text-[rgb(var(--color-primary))]" />
                <AlertDescription className="text-[rgb(var(--color-primary))] dark:text-orange-200">
                <strong>Launch Day Exception Applied:</strong> Transaction {reconciliationV2.cmb_exception.tx_id} remaining balance of {formatCurrency(reconciliationV2.cmb_exception.remaining_treated_as_fulfilled)} treated as fulfilled.
              </AlertDescription>
            </Alert>
          )}


        </>
      ) : null}

      {/* Gateway Breakdown — amounts received per gateway */}
      {isLoadingV2 ? (
        <Card className="border-[rgb(var(--color-border))]">
          <CardHeader>
            <Skeleton className="h-4 w-40" />
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-24 rounded-lg" />
              ))}
            </div>
          </CardContent>
        </Card>
      ) : reconciliationV2 ? (
        <Card>
          <CardHeader>
            <CardTitle>Gateway Breakdown</CardTitle>
            <CardDescription>Amounts received per gateway for {selectedDate}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              {/* Paybill */}
              <div className="p-4 rounded-xl border bg-[rgb(var(--color-card))] border-[rgb(var(--color-border))]">
                <div className="text-sm font-medium text-[rgb(var(--color-primary))]">Paybill</div>
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
                  {formatCurrency(reconciliationV2.raw_breakdown.paybill)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {reconciliationV2.details.mpesa_paybill.count} transactions
                </div>
              </div>

              {/* Till */}
              <div className="p-4 rounded-xl border bg-[rgb(var(--color-card))] border-[rgb(var(--color-border))]">
                <div className="text-sm font-medium text-green-600 dark:text-green-400">Till</div>
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
                  {formatCurrency(reconciliationV2.raw_breakdown.till)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {reconciliationV2.details.till.gateways?.join(', ') || 'Till'}
                </div>
              </div>

              {/* PDQ */}
              <div className="p-4 rounded-xl border bg-[rgb(var(--color-card))] border-[rgb(var(--color-border))]">
                <div className="text-sm font-medium text-[rgb(var(--color-secondary))]">PDQ</div>
                <div className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
                  {formatCurrency(reconciliationV2.raw_breakdown.pdq)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {reconciliationV2.details.pdq.count} transactions
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-gray-600 dark:text-gray-400">
              No report data available for the selected date
            </p>
          </CardContent>
        </Card>
      )}

    </div>
  );
}
