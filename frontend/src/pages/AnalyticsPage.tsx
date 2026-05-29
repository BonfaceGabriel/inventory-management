import { useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatCurrency } from '@/services/api';
import {
  useAnalyticsOverview,
  useMerchandiseAnalytics,
  useProductAnalytics,
  useRevenueAnalytics,
} from '@/services/queries/analytics';

const COLORS = ['#2563eb', '#0ea5e9', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6'];

function chartTooltipStyle() {
  return {
    backgroundColor: 'rgba(255,255,255,0.95)',
    border: '1px solid #e5e7eb',
    borderRadius: '8px',
  };
}

export default function AnalyticsPage() {
  const today = new Date().toISOString().split('T')[0];
  const defaultStart = new Date(Date.now() - 89 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(today);
  const [granularity, setGranularity] = useState<'day' | 'week' | 'month'>('week');

  const params = useMemo(() => ({ start_date: startDate, end_date: endDate }), [startDate, endDate]);
  const overviewQuery = useAnalyticsOverview(params);
  const revenueQuery = useRevenueAnalytics({ ...params, granularity });
  const productsQuery = useProductAnalytics(params);
  const merchandiseQuery = useMerchandiseAnalytics(params);

  const isLoading =
    overviewQuery.isLoading ||
    revenueQuery.isLoading ||
    productsQuery.isLoading ||
    merchandiseQuery.isLoading;
  const hasError =
    overviewQuery.isError ||
    revenueQuery.isError ||
    productsQuery.isError ||
    merchandiseQuery.isError;

  const applyPreset = (daysBack: number, trendGranularity: 'week' | 'month') => {
    const start = new Date(Date.now() - daysBack * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    setStartDate(start);
    setEndDate(today);
    setGranularity(trendGranularity);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Analytics</h1>
        <p className="text-muted-foreground">Revenue, product movement, and merchandise performance.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Date Range</CardTitle>
          <CardDescription>Summary-first defaults. Use daily only for deep investigation.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <div>
            <Label htmlFor="start-date">Start Date</Label>
            <Input id="start-date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="end-date">End Date</Label>
            <Input id="end-date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="granularity">Trend Bucket</Label>
            <select
              id="granularity"
              className="mt-2 h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs"
              value={granularity}
              onChange={(e) => setGranularity(e.target.value as 'day' | 'week' | 'month')}
            >
              <option value="week">Weekly</option>
              <option value="month">Monthly</option>
              <option value="day">Daily (Detailed)</option>
            </select>
          </div>
          <div className="md:col-span-3 flex flex-wrap gap-2 pt-1">
            <Button type="button" variant="outline" size="sm" onClick={() => applyPreset(29, 'week')}>
              Last 30 Days
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => applyPreset(89, 'week')}>
              Last 90 Days
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => applyPreset(179, 'month')}>
              Last 6 Months
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => applyPreset(364, 'month')}>
              Last 12 Months
            </Button>
          </div>
        </CardContent>
      </Card>

      {hasError && (
        <Card>
          <CardContent className="py-8 text-sm text-red-600">Failed to load analytics data. Please retry.</CardContent>
        </Card>
      )}

      {isLoading && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <Card key={i}>
                <CardHeader className="pb-2">
                  <Skeleton className="h-4 w-20" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-8 w-32" />
                </CardContent>
              </Card>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {[...Array(2)].map((_, i) => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-5 w-36" />
                  <Skeleton className="h-3 w-48 mt-1" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-[300px] w-full rounded-lg" />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-3 w-44 mt-1" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-[320px] w-full rounded-lg" />
            </CardContent>
          </Card>
        </>
      )}

      {!isLoading && !hasError && overviewQuery.data && revenueQuery.data && productsQuery.data && merchandiseQuery.data && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Revenue</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatCurrency(overviewQuery.data.revenue.total_revenue)}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Transactions</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{overviewQuery.data.revenue.total_transactions.toLocaleString()}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Avg Transaction</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatCurrency(overviewQuery.data.revenue.average_transaction_value)}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Top Product (Qty)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm font-semibold">{overviewQuery.data.top_product?.product_name || 'N/A'}</div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Revenue Trend</CardTitle>
                <CardDescription>{`${granularity.charAt(0).toUpperCase() + granularity.slice(1)} collections across the selected range.`}</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={revenueQuery.data.timeline}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis />
                    <Tooltip contentStyle={chartTooltipStyle()} formatter={(v: number) => formatCurrency(v)} />
                    <Line type="monotone" dataKey="total" stroke="#2563eb" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Gateway Share</CardTitle>
                <CardDescription>Revenue distribution by gateway.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie data={revenueQuery.data.gateway_share} dataKey="value" nameKey="gateway" outerRadius={100}>
                      {revenueQuery.data.gateway_share.map((_, index) => (
                        <Cell key={`gateway-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={chartTooltipStyle()} formatter={(v: number) => formatCurrency(v)} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Gateway Trend</CardTitle>
              <CardDescription>Daily gateway contribution over time.</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={revenueQuery.data.timeline}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" />
                  <YAxis />
                  <Tooltip contentStyle={chartTooltipStyle()} formatter={(v: number) => formatCurrency(v)} />
                  <Legend />
                  <Bar dataKey="MPESA_TILL" stackId="a" fill="#2563eb" />
                  <Bar dataKey="MPESA_PAYBILL" stackId="a" fill="#0ea5e9" />
                  <Bar dataKey="PDQ" stackId="a" fill="#22c55e" />
                  <Bar dataKey="MERCH" stackId="a" fill="#f59e0b" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Fast-Moving Products</CardTitle>
                <CardDescription>Top products by quantity sold.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={productsQuery.data.fast_moving_products} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis dataKey="product_name" type="category" width={180} />
                    <Tooltip contentStyle={chartTooltipStyle()} />
                    <Bar dataKey="quantity" fill="#2563eb" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Slow-Moving Products</CardTitle>
                <CardDescription>Lowest movement products in the period.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={productsQuery.data.slow_moving_products} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis dataKey="product_name" type="category" width={180} />
                    <Tooltip contentStyle={chartTooltipStyle()} />
                    <Bar dataKey="quantity" fill="#f59e0b" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Product Line Contribution</CardTitle>
              <CardDescription>Revenue by product line.</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={productsQuery.data.product_line_contribution}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="product_line" />
                  <YAxis />
                  <Tooltip contentStyle={chartTooltipStyle()} formatter={(v: number) => formatCurrency(v)} />
                  <Bar dataKey="revenue" fill="#22c55e" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Merchandise Trend</CardTitle>
                <CardDescription>Daily merchandise quantity and revenue.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={merchandiseQuery.data.timeline}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis />
                    <Tooltip contentStyle={chartTooltipStyle()} formatter={(v: number, name: string) => (name === 'revenue' ? formatCurrency(v) : v)} />
                    <Legend />
                    <Line type="monotone" dataKey="revenue" stroke="#a855f7" strokeWidth={2} />
                    <Line type="monotone" dataKey="quantity" stroke="#14b8a6" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Top Merchandise Items</CardTitle>
                <CardDescription>Highest-performing merchandise by revenue.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={merchandiseQuery.data.top_items} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis dataKey="item_name" type="category" width={180} />
                    <Tooltip contentStyle={chartTooltipStyle()} formatter={(v: number) => formatCurrency(v)} />
                    <Bar dataKey="revenue" fill="#a855f7" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Size / Color Mix</CardTitle>
              <CardDescription>Top apparel combinations by quantity.</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={360}>
                <BarChart data={merchandiseQuery.data.size_color_mix.slice(0, 12)}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="item_name" />
                  <YAxis />
                  <Tooltip contentStyle={chartTooltipStyle()} />
                  <Legend />
                  <Bar dataKey="quantity" fill="#14b8a6" name="Quantity" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
