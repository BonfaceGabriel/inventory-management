import { useState, useEffect } from 'react';
import { Package, Hash, DollarSign, Layers, AlertTriangle, Save, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select } from '@/components/ui/select';
import { formatCurrency, updateProduct, getProductCategories } from '@/services/api';
import type { Product, ProductCategory } from '@/services/api';

interface ProductDetailDialogProps {
  product: Product | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate?: () => void;
}

export function ProductDetailDialog({
  product,
  open,
  onOpenChange,
  onUpdate,
}: ProductDetailDialogProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState<Partial<Product>>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [categories, setCategories] = useState<ProductCategory[]>([]);

  useEffect(() => {
    if (product) {
      setFormData({
        prod_name: product.prod_name,
        sku_name: product.sku_name,
        current_price: product.current_price,
        cost_price: product.cost_price,
        current_pv: product.current_pv,
        quantity: product.quantity,
        reorder_level: product.reorder_level,
        category: product.category,
      });
    }
  }, [product]);

  // Load categories when dialog opens
  useEffect(() => {
    const loadCategories = async () => {
      try {
        const cats = await getProductCategories();
        const catsList = Array.isArray(cats) ? cats : (cats as any).results || [];
        setCategories(catsList);
      } catch (err) {
        console.error('Failed to load categories:', err);
      }
    };
    if (open) loadCategories();
  }, [open]);

  if (!product) return null;

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

  const handleSave = async () => {
    if (!product) return;

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await updateProduct(product.id, {
        prod_name: formData.prod_name,
        sku_name: formData.sku_name,
        current_price: formData.current_price,
        cost_price: formData.cost_price,
        current_pv: formData.current_pv,
        quantity: formData.quantity,
        reorder_level: formData.reorder_level,
        category: formData.category,
      });

      setSuccess('Product updated successfully!');
      setIsEditing(false);

      // Notify parent to refresh
      onUpdate?.();

      // Close dialog after short delay
      setTimeout(() => {
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || err.message || 'Failed to update product';
      setError(errorMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setIsEditing(false);
    setFormData({
      prod_name: product.prod_name,
      sku_name: product.sku_name,
      current_price: product.current_price,
      cost_price: product.cost_price,
      current_pv: product.current_pv,
      quantity: product.quantity,
      reorder_level: product.reorder_level,
      category: product.category,
    });
    setError(null);
    setSuccess(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader onClose={() => onOpenChange(false)}>
          <DialogTitle>
            {isEditing ? 'Edit Product' : 'Product Details'}
          </DialogTitle>
          <DialogDescription>
            {product.prod_code} - {product.sku}
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          {error && (
            <Alert variant="destructive" className="mb-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {success && (
            <Alert className="mb-4 bg-green-50 border-green-200 text-green-800">
              <AlertDescription>{success}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-6">
            {/* Stock Status Badge */}
            <div className="flex items-center justify-between">
              {getStockBadge(product.stock_status)}
              {!isEditing && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setIsEditing(true)}
                >
                  Edit Product
                </Button>
              )}
            </div>

            {/* Product Info Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div>
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                    <Hash className="h-4 w-4" />
                    Product Code
                  </Label>
                  <p className="mt-1 font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {product.prod_code}
                  </p>
                </div>

                <div>
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                    <Package className="h-4 w-4" />
                    Product Name
                  </Label>
                  {isEditing ? (
                    <Input
                      value={formData.prod_name || ''}
                      onChange={(e) => setFormData({ ...formData, prod_name: e.target.value })}
                      className="mt-1"
                    />
                  ) : (
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {product.prod_name}
                    </p>
                  )}
                </div>

                <div>
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                    <Hash className="h-4 w-4" />
                    SKU
                  </Label>
                  <p className="mt-1 font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {product.sku}
                  </p>
                </div>

                <div>
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                    Package Description
                  </Label>
                  {isEditing ? (
                    <Input
                      value={formData.sku_name || ''}
                      onChange={(e) => setFormData({ ...formData, sku_name: e.target.value })}
                      className="mt-1"
                    />
                  ) : (
                    <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">
                      {product.sku_name}
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                    <DollarSign className="h-4 w-4" />
                    Current Price
                  </Label>
                  {isEditing ? (
                    <Input
                      type="number"
                      step="0.01"
                      value={formData.current_price || ''}
                      onChange={(e) => setFormData({ ...formData, current_price: e.target.value })}
                      className="mt-1"
                    />
                  ) : (
                    <p className="mt-1 text-2xl font-bold text-blue-600 dark:text-blue-500">
                      {formatCurrency(product.current_price)}
                    </p>
                  )}
                </div>

                <div>
                  <Label className="text-gray-600 dark:text-gray-400">
                    Cost Price
                  </Label>
                  {isEditing ? (
                    <Input
                      type="number"
                      step="0.01"
                      value={formData.cost_price || ''}
                      onChange={(e) => setFormData({ ...formData, cost_price: e.target.value })}
                      className="mt-1"
                    />
                  ) : (
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {formatCurrency(product.cost_price)}
                    </p>
                  )}
                </div>

                <div>
                  <Label className="text-gray-600 dark:text-gray-400">
                    Point Value (PV)
                  </Label>
                  {isEditing ? (
                    <Input
                      type="number"
                      step="0.01"
                      value={formData.current_pv || ''}
                      onChange={(e) => setFormData({ ...formData, current_pv: e.target.value })}
                      className="mt-1"
                    />
                  ) : (
                    <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
                      {product.current_pv}
                    </p>
                  )}
                </div>

                <div>
                  <Label className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                    <Layers className="h-4 w-4" />
                    Category
                  </Label>
                  {isEditing ? (
                    <Select
                      value={formData.category?.toString() || ''}
                      onChange={(e) => setFormData({
                        ...formData,
                        category: e.target.value ? parseInt(e.target.value) : null
                      })}
                      className="mt-1"
                    >
                      <option value="">Select Category (Optional)</option>
                      {categories.map((cat) => (
                        <option key={cat.id} value={cat.id}>
                          {cat.name}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">
                      {product.category_name || 'Uncategorized'}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Inventory Section */}
            <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold mb-4">Inventory</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-gray-600 dark:text-gray-400">
                    Current Stock
                  </Label>
                  {isEditing ? (
                    <Input
                      type="number"
                      min="0"
                      value={formData.quantity || 0}
                      onChange={(e) => setFormData({ ...formData, quantity: parseInt(e.target.value) })}
                      className="mt-1"
                    />
                  ) : (
                    <p className={`mt-1 text-3xl font-bold ${
                      product.stock_status === 'OUT_OF_STOCK'
                        ? 'text-red-600'
                        : product.stock_status === 'LOW_STOCK'
                        ? 'text-orange-600'
                        : 'text-green-600'
                    }`}>
                      {product.quantity}
                    </p>
                  )}
                </div>

                <div>
                  <Label className="text-gray-600 dark:text-gray-400">
                    Reorder Level
                  </Label>
                  {isEditing ? (
                    <Input
                      type="number"
                      min="0"
                      value={formData.reorder_level || 0}
                      onChange={(e) => setFormData({ ...formData, reorder_level: parseInt(e.target.value) })}
                      className="mt-1"
                    />
                  ) : (
                    <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">
                      {product.reorder_level}
                    </p>
                  )}
                </div>
              </div>

              {product.stock_status === 'LOW_STOCK' && (
                <Alert className="mt-4 bg-orange-50 border-orange-200 text-orange-800">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>
                    Stock is below reorder level. Consider restocking soon.
                  </AlertDescription>
                </Alert>
              )}

              {product.stock_status === 'OUT_OF_STOCK' && (
                <Alert variant="destructive" className="mt-4">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>
                    Product is out of stock. Restock immediately.
                  </AlertDescription>
                </Alert>
              )}
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          {isEditing ? (
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={handleCancel}
                disabled={saving}
                className="flex-1"
              >
                <X className="mr-2 h-4 w-4" />
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 bg-blue-600 hover:bg-blue-700"
              >
                <Save className="mr-2 h-4 w-4" />
                Save Changes
              </Button>
            </div>
          ) : (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
