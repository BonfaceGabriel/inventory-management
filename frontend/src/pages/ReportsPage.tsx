import { useState } from 'react';
import { Download, FileSpreadsheet, FileText } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useDailyReport } from '@/services/queries/reports';
import { downloadDailyReportPDF, downloadTransactionsCSV, downloadTransactionsXLSX, formatCurrency } from '@/services/api';
import { toast } from 'sonner';

export default function ReportsPage() {
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [isExporting, setIsExporting] = useState(false);
  const { data: report, isLoading } = useDailyReport(selectedDate);

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
            <div className="flex items-end gap-2">
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
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Report Summary */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(6)].map((_, i) => (
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
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Total Transactions</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{report.summary.total_transactions}</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Total Amount</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {formatCurrency(report.summary.total_amount)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">To Parent Company</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {formatCurrency(report.summary.total_to_parent)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">To Shop</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {formatCurrency(report.summary.total_to_shop)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Fulfilled</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-600 dark:text-green-400">
                  {report.status_breakdown.FULFILLED?.count || 0}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Pending</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
                  {(report.status_breakdown.NOT_PROCESSED?.count || 0) + (report.status_breakdown.PROCESSING?.count || 0)}
                </div>
              </CardContent>
            </Card>
          </div>

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
                        <p className="font-medium">{gateway.gateway_type}</p>
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
