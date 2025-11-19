import { useState, useEffect } from 'react';
import { Plus, Search, Package, AlertTriangle, Loader2 } from 'lucide-react';
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
import { ProductDetailDialog } from '@/components/products/ProductDetailDialog';
import { CreateProductDialog } from '@/components/products/CreateProductDialog';
import {
  getProducts,
  getProductCategories,
  getProductSummary,
  formatCurrency,
  type Product,
  type ProductCategory,
  type ProductSummary,
} from '@/services/api';

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [summary, setSummary] = useState<ProductSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<number | undefined>();
  const [showLowStockOnly, setShowLowStockOnly] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  // Fetch data on mount
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [productsData, categoriesData, summaryData] = await Promise.all([
          getProducts(),
          getProductCategories(),
          getProductSummary(),
        ]);
        // Handle both paginated and array responses
        const productsList = Array.isArray(productsData) ? productsData : productsData.results || [];
        const categoriesList = Array.isArray(categoriesData) ? categoriesData : categoriesData.results || [];

        setProducts(productsList);
        setCategories(categoriesList);
        setSummary(summaryData);
      } catch (error) {
        console.error('Error fetching products:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  // Filter products locally (for responsiveness)
  const filteredProducts = products.filter((product) => {
    if (searchTerm) {
      const search = searchTerm.toLowerCase();
      if (
        !product.prod_name.toLowerCase().includes(search) &&
        !product.sku?.toLowerCase().includes(search) &&
        !product.prod_code?.toLowerCase().includes(search)
      ) {
        return false;
      }
    }
    if (selectedCategory && product.category !== selectedCategory) {
      return false;
    }
    if (showLowStockOnly) {
      if (product.stock_status !== 'LOW_STOCK' && product.stock_status !== 'OUT_OF_STOCK') {
        return false;
      }
    }
    return true;
  });

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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
        <span className="ml-2 text-gray-600">Loading products...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Products & Inventory</h1>
        <p className="text-gray-600 dark:text-gray-400">Manage your product catalog and stock levels</p>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          <Card className="hover:shadow-lg transition-shadow">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Products</CardTitle>
              <Package className="h-4 w-4 text-blue-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summary.total_products}</div>
              <p className="text-xs text-gray-600 dark:text-gray-400">
                {summary.active_products} active
              </p>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow border-green-200 dark:border-green-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">In Stock</CardTitle>
              <Package className="h-4 w-4 text-green-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600">
                {summary.active_products - summary.low_stock - summary.out_of_stock}
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
              <div className="text-2xl font-bold text-orange-600">{summary.low_stock}</div>
              <p className="text-xs text-gray-600 dark:text-gray-400">Need reorder</p>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow border-red-200 dark:border-red-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Out of Stock</CardTitle>
              <AlertTriangle className="h-4 w-4 text-red-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">{summary.out_of_stock}</div>
              <p className="text-xs text-gray-600 dark:text-gray-400">Unavailable</p>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Value</CardTitle>
              <Package className="h-4 w-4 text-blue-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatCurrency(summary.total_retail_value)}
              </div>
              <p className="text-xs text-gray-600 dark:text-gray-400">
                Cost: {formatCurrency(summary.total_inventory_value)}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters and Actions */}
      <Card>
        <CardHeader>
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <CardTitle>Product Catalog</CardTitle>
              <CardDescription>
                {filteredProducts.length} of {products.length} products
              </CardDescription>
            </div>
            <Button
              className="w-fit bg-blue-600 hover:bg-blue-700"
              onClick={() => setShowCreate(true)}
            >
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
                placeholder="Search products by name, SKU, or code..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select
              value={selectedCategory?.toString() || 'all'}
              onChange={(e) =>
                setSelectedCategory(e.target.value === 'all' ? undefined : Number(e.target.value))
              }
              className="w-full md:w-[200px]"
            >
              <option value="all">All Categories</option>
              {categories.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name} ({cat.product_count})
                </option>
              ))}
            </Select>
            <Select
              value={showLowStockOnly ? 'low' : 'all'}
              onChange={(e) => setShowLowStockOnly(e.target.value === 'low')}
              className="w-full md:w-[200px]"
            >
              <option value="all">All Stock Levels</option>
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
                  <TableHead className="text-right">PV</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Stock Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredProducts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-gray-500 py-8">
                      No products found
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredProducts.map((product) => (
                    <TableRow
                      key={product.id}
                      className="cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700"
                      onClick={() => {
                        setSelectedProduct(product);
                        setShowDetail(true);
                      }}
                    >
                      <TableCell className="font-mono text-sm">{product.sku}</TableCell>
                      <TableCell>
                        <div>
                          <div className="font-medium">{product.prod_name}</div>
                          <div className="text-sm text-gray-500 dark:text-gray-400">
                            {product.sku_name}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        {product.category_name ? (
                          <Badge variant="outline">{product.category_name}</Badge>
                        ) : (
                          <span className="text-gray-400 text-sm">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {formatCurrency(product.current_price)}
                      </TableCell>
                      <TableCell className="text-right text-gray-600 dark:text-gray-400">
                        {product.current_pv}
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
                      <TableCell>{getStockBadge(product.stock_status)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Product Detail Dialog */}
      <ProductDetailDialog
        product={selectedProduct}
        open={showDetail}
        onOpenChange={setShowDetail}
        onUpdate={() => {
          // Reload products when updated
          fetchData();
        }}
      />

      {/* Create Product Dialog */}
      <CreateProductDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        onSuccess={() => {
          // Reload products when created
          fetchData();
        }}
      />
    </div>
  );

  // Helper function to refetch data
  async function fetchData() {
    try {
      setLoading(true);
      const [productsData, categoriesData, summaryData] = await Promise.all([
        getProducts(),
        getProductCategories(),
        getProductSummary(),
      ]);
      const productsList = Array.isArray(productsData) ? productsData : productsData.results || [];
      const categoriesList = Array.isArray(categoriesData) ? categoriesData : categoriesData.results || [];

      setProducts(productsList);
      setCategories(categoriesList);
      setSummary(summaryData);
    } catch (error) {
      console.error('Error fetching products:', error);
    } finally {
      setLoading(false);
    }
  }
}
