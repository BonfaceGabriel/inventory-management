import { useState } from 'react';
import { Plus, Search, Package, AlertTriangle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Select } from '@/components/ui/select';
import { mockProducts } from '@/services/mockData';
import { formatCurrency } from '@/services/api';
import type { Product, ProductFilters } from '@/types/product.types';

export default function ProductsPage() {
  const [products] = useState<Product[]>(mockProducts);
  const [filters, setFilters] = useState<ProductFilters>({});
  const [searchTerm, setSearchTerm] = useState('');

  // Filter products
  const filteredProducts = products.filter((product) => {
    if (searchTerm && !product.name.toLowerCase().includes(searchTerm.toLowerCase()) &&
        !product.sku?.toLowerCase().includes(searchTerm.toLowerCase())) {
      return false;
    }
    if (filters.category && product.category !== filters.category) {
      return false;
    }
    if (filters.low_stock && product.quantity >= (product.reorder_level || 0)) {
      return false;
    }
    if (filters.is_active !== undefined && product.is_active !== filters.is_active) {
      return false;
    }
    return true;
  });

  // Get unique categories
  const categories = Array.from(new Set(products.map(p => p.category).filter(Boolean)));

  // Calculate summary stats
  const totalProducts = products.length;
  const lowStockCount = products.filter(p => p.quantity <= (p.reorder_level || 0)).length;
  const outOfStockCount = products.filter(p => p.quantity === 0).length;
  const totalValue = products.reduce((sum, p) => sum + (parseFloat(p.price) * p.quantity), 0);

  const getStockStatus = (product: Product) => {
    if (product.quantity === 0) {
      return <Badge variant="destructive">Out of Stock</Badge>;
    }
    if (product.quantity <= (product.reorder_level || 0)) {
      return <Badge className="bg-orange-500 hover:bg-orange-600">Low Stock</Badge>;
    }
    return <Badge className="bg-green-500 hover:bg-green-600">In Stock</Badge>;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Products & Inventory</h1>
        <p className="text-gray-600 dark:text-gray-400">Manage your product catalog and stock levels</p>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Products</CardTitle>
            <Package className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalProducts}</div>
            <p className="text-xs text-gray-600 dark:text-gray-400">Active SKUs</p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Inventory Value</CardTitle>
            <Package className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCurrency(totalValue.toString())}</div>
            <p className="text-xs text-gray-600 dark:text-gray-400">Total stock value</p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow border-orange-200 dark:border-orange-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Low Stock</CardTitle>
            <AlertTriangle className="h-4 w-4 text-orange-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-orange-600">{lowStockCount}</div>
            <p className="text-xs text-gray-600 dark:text-gray-400">Items need reorder</p>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow border-red-200 dark:border-red-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Out of Stock</CardTitle>
            <AlertTriangle className="h-4 w-4 text-red-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">{outOfStockCount}</div>
            <p className="text-xs text-gray-600 dark:text-gray-400">Items unavailable</p>
          </CardContent>
        </Card>
      </div>

      {/* Filters and Actions */}
      <Card>
        <CardHeader>
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <CardTitle>Product Catalog</CardTitle>
              <CardDescription>Browse and manage your inventory</CardDescription>
            </div>
            <Button className="w-fit">
              <Plus className="mr-2 h-4 w-4" />
              Add Product
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <Input
                placeholder="Search products by name or SKU..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select
              value={filters.category || 'all'}
              onChange={(e) =>
                setFilters({ ...filters, category: e.target.value === 'all' ? undefined : e.target.value })
              }
              className="w-full md:w-[200px]"
            >
              <option value="all">All Categories</option>
              {categories.map((cat) => (
                <option key={cat} value={cat!}>
                  {cat}
                </option>
              ))}
            </Select>
            <Select
              value={filters.low_stock ? 'low' : 'all'}
              onChange={(e) =>
                setFilters({ ...filters, low_stock: e.target.value === 'low' })
              }
              className="w-full md:w-[200px]"
            >
              <option value="all">All Stock</option>
              <option value="low">Low Stock Only</option>
            </Select>
          </div>

          {/* Products Table */}
          <div className="rounded-md border border-gray-200 dark:border-gray-700">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>SKU</TableHead>
                  <TableHead>Product Name</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Supplier</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredProducts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-gray-500 py-8">
                      No products found
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredProducts.map((product) => (
                    <TableRow
                      key={product.id}
                      className="cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700"
                    >
                      <TableCell className="font-mono text-sm">{product.sku}</TableCell>
                      <TableCell>
                        <div>
                          <div className="font-medium">{product.name}</div>
                          <div className="text-sm text-gray-500 dark:text-gray-400 line-clamp-1">
                            {product.description}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{product.category}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {formatCurrency(product.price)}
                      </TableCell>
                      <TableCell className="text-right text-gray-600 dark:text-gray-400">
                        {formatCurrency(product.cost_price || '0')}
                      </TableCell>
                      <TableCell className="text-right">
                        <span
                          className={
                            product.quantity === 0
                              ? 'text-red-600 font-bold'
                              : product.quantity <= (product.reorder_level || 0)
                              ? 'text-orange-600 font-bold'
                              : 'font-semibold'
                          }
                        >
                          {product.quantity}
                        </span>
                      </TableCell>
                      <TableCell>{getStockStatus(product)}</TableCell>
                      <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                        {product.supplier}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
