import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
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
  AlertTriangle,
  TrendingUp,
  DollarSign,
} from 'lucide-react';
import {
  getHistoricalStockReport,
  downloadHistoricalStockReportXlsx,
  formatCurrency,
  type StockReport,
} from '../services/api';
import { toast } from 'sonner';

export default function StockReportPage() {
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [report, setReport] = useState<StockReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  const handleGenerateReport = async () => {
    if (!selectedDate) {
      toast.error('Please select a date');
      return;
    }

    try {
      setIsLoading(true);
      const data = await getHistoricalStockReport(selectedDate);
      setReport(data);
      toast.success(`Stock report generated for ${selectedDate}`);
    } catch (error: any) {
      console.error('Error generating stock report:', error);
      const errorMsg = error.response?.data?.error || error.message || 'Failed to generate stock report';
      toast.error(errorMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleExportXlsx = async () => {
    if (!selectedDate) {
      toast.error('Please select a date');
      return;
    }

    try {
      setIsExporting(true);
      await downloadHistoricalStockReportXlsx(selectedDate);
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

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <BarChart3 className="h-8 w-8" />
            Historical Stock Reports
          </h1>
          <p className="text-gray-600 mt-1">
            View inventory levels as of any past date
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
            Choose a date to view stock levels as they were on that day
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
                onClick={handleExportXlsx}
                disabled={!selectedDate || isExporting}
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
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Report Summary */}
      {report && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <Card className="hover:shadow-lg transition-shadow">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Products</CardTitle>
                <Package className="h-4 w-4 text-blue-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{report.summary.total_products}</div>
                <p className="text-xs text-gray-600 dark:text-gray-400">
                  As of {report.report_date || selectedDate}
                </p>
              </CardContent>
            </Card>

            <Card className="hover:shadow-lg transition-shadow border-green-200 dark:border-green-800">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">In Stock</CardTitle>
                <TrendingUp className="h-4 w-4 text-green-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-600">
                  {report.summary.in_stock_count}
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400">Items available</p>
              </CardContent>
            </Card>

            <Card className="hover:shadow-lg transition-shadow border-orange-200 dark:border-orange-800">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Low Stock</CardTitle>
                <AlertTriangle className="h-4 w-4 text-orange-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-orange-600">
                  {report.summary.low_stock_count}
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400">Need reorder</p>
              </CardContent>
            </Card>

            <Card className="hover:shadow-lg transition-shadow">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Stock Value</CardTitle>
                <DollarSign className="h-4 w-4 text-blue-600" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {formatCurrency(report.summary.total_stock_value)}
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400">
                  Cost: {formatCurrency(report.summary.total_cost_value)}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Product Lines Breakdown */}
          {report.product_lines.map((productLine, index) => (
            <Card key={index} className="mb-4">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>{productLine.product_line_name}</CardTitle>
                    <CardDescription>
                      {productLine.product_count} products • Total Qty: {productLine.total_quantity} • Value: {formatCurrency(productLine.stock_value)}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="rounded-md border border-gray-200 dark:border-gray-700">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>SKU</TableHead>
                        <TableHead>Product Name</TableHead>
                        <TableHead className="text-right">Quantity</TableHead>
                        <TableHead className="text-right">Unit Price</TableHead>
                        <TableHead className="text-right">Stock Value</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {productLine.products.map((product) => (
                        <TableRow key={product.id}>
                          <TableCell className="font-mono text-sm">{product.sku}</TableCell>
                          <TableCell>
                            <div>
                              <div className="font-medium">{product.prod_name}</div>
                              <div className="text-sm text-gray-500 dark:text-gray-400">
                                {product.prod_code}
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="text-right">
                            <span
                              className={
                                product.stock_status === 'OUT_OF_STOCK'
                                  ? 'text-red-600 font-bold'
                                  : product.stock_status === 'LOW_STOCK'
                                  ? 'text-orange-600 font-bold'
                                  : 'font-semibold text-green-600'
                              }
                            >
                              {product.quantity}
                            </span>
                          </TableCell>
                          <TableCell className="text-right font-semibold">
                            {formatCurrency(product.current_price)}
                          </TableCell>
                          <TableCell className="text-right font-semibold">
                            {formatCurrency(product.stock_value)}
                          </TableCell>
                          <TableCell>{getStockBadge(product.stock_status)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          ))}
        </>
      )}

      {/* Placeholder when no report */}
      {!report && !isLoading && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Package className="h-16 w-16 text-gray-300 mb-4" />
            <p className="text-gray-600 mb-2 font-medium">No Report Generated</p>
            <p className="text-sm text-gray-500 text-center max-w-md">
              Select a date above and click "Generate Report" to view historical stock levels
              as they were on that specific date.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
