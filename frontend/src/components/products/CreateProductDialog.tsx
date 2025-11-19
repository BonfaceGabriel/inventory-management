import { useState, useEffect } from 'react';
import { Plus, Save, X, AlertTriangle } from 'lucide-react';
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
import { Select } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { createProduct, getProductCategories, type ProductCategory } from '@/services/api';

interface CreateProductDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function CreateProductDialog({
  open,
  onOpenChange,
  onSuccess,
}: CreateProductDialogProps) {
  const [formData, setFormData] = useState({
    prod_code: '',
    prod_name: '',
    sku: '',
    sku_name: '',
    current_price: '',
    cost_price: '',
    current_pv: '',
    quantity: 0,
    reorder_level: 10,
    is_active: true,
    category: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [categories, setCategories] = useState<ProductCategory[]>([]);

  // Load categories when dialog opens
  useEffect(() => {
    const loadCategories = async () => {
      try {
        const cats = await getProductCategories();
        const catsList = Array.isArray(cats) ? cats : cats.results || [];
        setCategories(catsList);
      } catch (err) {
        console.error('Failed to load categories:', err);
      }
    };
    if (open) loadCategories();
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!formData.prod_code || !formData.prod_name || !formData.sku) {
      setError('Product Code, Name, and SKU are required');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await createProduct(formData);

      setSuccess('Product created successfully!');

      // Reset form
      setFormData({
        prod_code: '',
        prod_name: '',
        sku: '',
        sku_name: '',
        current_price: '',
        cost_price: '',
        current_pv: '',
        quantity: 0,
        reorder_level: 10,
        is_active: true,
        category: null,
      });

      // Notify parent
      onSuccess?.();

      // Close after delay
      setTimeout(() => {
        onOpenChange(false);
      }, 1500);
    } catch (err: any) {
      console.error('Create product error:', err.response?.data);
      const errorMsg = err.response?.data
        ? JSON.stringify(err.response.data)
        : err.message || 'Failed to create product';
      setError(errorMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader onClose={() => onOpenChange(false)}>
          <DialogTitle>Add New Product</DialogTitle>
          <DialogDescription>
            Create a new product in the inventory
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
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

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="prod_code">
                  Product Code <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="prod_code"
                  value={formData.prod_code}
                  onChange={(e) => setFormData({ ...formData, prod_code: e.target.value })}
                  placeholder="e.g., AP001E"
                  required
                />
              </div>

              <div>
                <Label htmlFor="sku">
                  SKU <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="sku"
                  value={formData.sku}
                  onChange={(e) => setFormData({ ...formData, sku: e.target.value })}
                  placeholder="e.g., AP001E"
                  required
                />
              </div>

              <div className="col-span-2">
                <Label htmlFor="prod_name">
                  Product Name <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="prod_name"
                  value={formData.prod_name}
                  onChange={(e) => setFormData({ ...formData, prod_name: e.target.value })}
                  placeholder="e.g., Noni Juice"
                  required
                />
              </div>

              <div className="col-span-2">
                <Label htmlFor="sku_name">Package Description</Label>
                <Input
                  id="sku_name"
                  value={formData.sku_name}
                  onChange={(e) => setFormData({ ...formData, sku_name: e.target.value })}
                  placeholder="e.g., 100 tablets"
                />
              </div>

              <div className="col-span-2">
                <Label htmlFor="category">Category</Label>
                <Select
                  id="category"
                  value={formData.category?.toString() || ''}
                  onChange={(e) => setFormData({
                    ...formData,
                    category: e.target.value ? parseInt(e.target.value) : null
                  })}
                >
                  <option value="">Select Category (Optional)</option>
                  {categories.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.name}
                    </option>
                  ))}
                </Select>
              </div>

              <div>
                <Label htmlFor="current_price">Selling Price (KES)</Label>
                <Input
                  id="current_price"
                  type="number"
                  step="0.01"
                  value={formData.current_price}
                  onChange={(e) => setFormData({ ...formData, current_price: e.target.value })}
                  placeholder="0.00"
                />
              </div>

              <div>
                <Label htmlFor="cost_price">Cost Price (KES)</Label>
                <Input
                  id="cost_price"
                  type="number"
                  step="0.01"
                  value={formData.cost_price}
                  onChange={(e) => setFormData({ ...formData, cost_price: e.target.value })}
                  placeholder="0.00"
                />
              </div>

              <div>
                <Label htmlFor="current_pv">Point Value (PV)</Label>
                <Input
                  id="current_pv"
                  type="number"
                  step="0.01"
                  value={formData.current_pv}
                  onChange={(e) => setFormData({ ...formData, current_pv: e.target.value })}
                  placeholder="0.00"
                />
              </div>

              <div>
                <Label htmlFor="quantity">Initial Quantity</Label>
                <Input
                  id="quantity"
                  type="number"
                  min="0"
                  value={formData.quantity}
                  onChange={(e) => setFormData({ ...formData, quantity: parseInt(e.target.value) || 0 })}
                />
              </div>

              <div>
                <Label htmlFor="reorder_level">Reorder Level</Label>
                <Input
                  id="reorder_level"
                  type="number"
                  min="0"
                  value={formData.reorder_level}
                  onChange={(e) => setFormData({ ...formData, reorder_level: parseInt(e.target.value) || 0 })}
                />
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={saving}
                className="flex-1"
              >
                <X className="mr-2 h-4 w-4" />
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={saving}
                className="flex-1 bg-blue-600 hover:bg-blue-700"
              >
                <Plus className="mr-2 h-4 w-4" />
                {saving ? 'Creating...' : 'Create Product'}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
