import { useState } from 'react';
import { Download, FileSpreadsheet, FileText, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useDailyReport, useDailyReconciliationV2 } from '@/services/queries/reports';
import { downloadDailyReportPDF, downloadTransactionsCSV, downloadTransactionsXLSX, downloadUnfulfilledOrdersXlsx, formatCurrency } from '@/services/api';
import { toast } from 'sonner';

export default function ReportsPage() {
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [isExporting, setIsExporting] = useState(false);
  const { data: report, isLoading } = useDailyReport(selectedDate);
  const { data: reconciliationV2, isLoading: isLoadingV2 } = useDailyReconciliationV2(selectedDate);

  const handleDownloadPDF = () => {
    downloadDailyReportPDF(selectedDate);
  };

  const handleDownloadCSV = async () => {
    try {
      setIsExporting(true);
      await downloadTransactionsCSV({ date: selectedDate });
      toast.success('CSV export downloaded successfully');
    } catch (error) {
      console.error('CSV export error:', error);
      toast.error('Failed to download CSV export');
    } finally {
      setIsExporting(false);
    }
  };

  const handleDownloadXLSX = async () => {
    try {
      setIsExporting(true);
      await downloadTransactionsXLSX({ date: selectedDate });
      toast.success('Excel export downloaded successfully');
    } catch (error) {
      console.error('XLSX export error:', error);
      toast.error('Failed to download Excel export');
    } finally {
      setIsExporting(false);
    }
  };

  const handleDownloadUnfulfilledOrders = async () => {
    const loadingToast = toast.loading('Generating unfulfilled orders export...');
    try {
      setIsExporting(true);
      await downloadUnfulfilledOrdersXlsx();
      toast.dismiss(loadingToast);
      toast.success('Unfulfilled orders exported successfully!');
    } catch (error) {
      console.error('Unfulfilled export error:', error);
      toast.dismiss(loadingToast);
      toast.error('Failed to export unfulfilled orders');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Reports</h1>
        <p className="text-gray-600 dark:text-gray-400">Generate and download reconciliation reports</p>
      </div>

      {/* Date Selection */}
      <Card>
        <CardHeader>
          <CardTitle>Select Date</CardTitle>
          <CardDescription>Choose a date to view the reconciliation report</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4">
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
            <div className="flex items-end gap-2 flex-wrap">
              <Button onClick={handleDownloadPDF} disabled={isLoading || isExporting} variant="default">
                <Download className="mr-2 h-4 w-4" />
                PDF Report
              </Button>
              <Button onClick={handleDownloadCSV} disabled={isLoading || isExporting} variant="outline">
                <FileText className="mr-2 h-4 w-4" />
                Export CSV
              </Button>
              <Button onClick={handleDownloadXLSX} disabled={isLoading || isExporting} variant="outline">
                <FileSpreadsheet className="mr-2 h-4 w-4" />
                Export Excel
              </Button>
              <Button onClick={handleDownloadUnfulfilledOrders} disabled={isExporting} variant="outline" className="bg-orange-50 hover:bg-orange-100 border-orange-300 text-orange-700">
                <FileSpreadsheet className="mr-2 h-4 w-4" />
                Unfulfilled Orders
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
            <Card className="border-blue-200 dark:border-blue-800">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-blue-600 dark:text-blue-400">
                  X Value
                </CardTitle>
                <CardDescription className="text-xs">
                  Paybill - Unused + PDQ + Previous - Sales
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className={`text-3xl font-bold ${reconciliationV2.x_value >= 0 ? 'text-blue-600' : 'text-red-600'}`}>
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
            <Card className="border-purple-200 dark:border-purple-800">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-purple-600 dark:text-purple-400">
                  Y Value
                </CardTitle>
                <CardDescription className="text-xs">
                  Till - Previous - Credit - KITS
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className={`text-3xl font-bold ${reconciliationV2.y_value >= 0 ? 'text-purple-600' : 'text-red-600'}`}>
                  {formatCurrency(reconciliationV2.y_value)}
                </div>
                <div className="mt-2 text-xs text-gray-500 space-y-1">
                  <div className="flex justify-between">
                    <span>+ Till:</span>
                    <span>{formatCurrency(reconciliationV2.y_formula.till)}</span>
                  </div>
                  <div className="flex justify-between text-red-500">
                    <span>- Previous:</span>
                    <span>{formatCurrency(reconciliationV2.y_formula.previous)}</span>
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
              ? 'border-green-400 bg-green-50 dark:bg-green-900/20 dark:border-green-600'
              : 'border-red-400 bg-red-50 dark:bg-red-900/20 dark:border-red-600'
            }>
              <CardHeader className="pb-2">
                <CardTitle className={`text-sm font-medium flex items-center gap-2 ${
                  reconciliationV2.is_balanced ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                }`}>
                  {reconciliationV2.is_balanced ? (
                    <CheckCircle2 className="h-5 w-5" />
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
            <Alert className="border-orange-300 bg-orange-50 dark:bg-orange-900/20">
              <AlertTriangle className="h-4 w-4 text-orange-600" />
              <AlertDescription className="text-orange-800 dark:text-orange-200">
                <strong>Launch Day Exception Applied:</strong> Transaction {reconciliationV2.cmb_exception.tx_id} remaining balance of {formatCurrency(reconciliationV2.cmb_exception.remaining_treated_as_fulfilled)} treated as fulfilled.
              </AlertDescription>
            </Alert>
          )}


        </>
      ) : null}

      {/* Legacy Report Summary - kept for additional context */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-32" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : report ? (
        <>
          {/* Overall Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Transaction Summary</CardTitle>
              <CardDescription>Overview of all transactions for {selectedDate}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-3">
                <div className="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <div className="text-sm font-medium text-gray-600 dark:text-gray-400">Total Transactions</div>
                  <div className="text-2xl font-bold">{report.summary.total_transactions}</div>
                </div>
                <div className="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <div className="text-sm font-medium text-gray-600 dark:text-gray-400">Total Amount</div>
                  <div className="text-2xl font-bold">{formatCurrency(report.summary.total_amount)}</div>
                </div>
                <div className="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <div className="text-sm font-medium text-gray-600 dark:text-gray-400">Status</div>
                  <div className="flex gap-4">
                    <span className="text-green-600 font-medium">{report.status_breakdown.FULFILLED?.count || 0} Fulfilled</span>
                    <span className="text-yellow-600 font-medium">{(report.status_breakdown.NOT_PROCESSED?.count || 0) + (report.status_breakdown.PROCESSING?.count || 0)} Pending</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Gateway Breakdown */}
          {report.gateway_reports && report.gateway_reports.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Gateway Breakdown</CardTitle>
                <CardDescription>Transaction summary by payment gateway</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {report.gateway_reports.map((gateway, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between rounded-lg border p-4"
                    >
                      <div>
                        <p className="font-medium">{gateway.gateway_name}</p>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          {gateway.transaction_count} transactions
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="font-bold">{formatCurrency(gateway.total_amount)}</p>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          To Shop: {formatCurrency(gateway.settlement.shop_amount.toString())}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
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
