import { useState, useEffect } from 'react';
import { Plus, Pencil, Trash2, Tag, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogBody,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Label } from '@/components/ui/label';
import {
  getPromotions,
  createPromotion,
  updatePromotion,
  deletePromotion,
  getProducts,
  type Promotion,
  type CreatePromotionRequest,
  type Product,
} from '@/services/api';

interface ProductRow {
  product_id: number;
  min_quantity: number;
}

interface FormState {
  name: string;
  discount_type: 'FIXED' | 'PERCENTAGE';
  discount_value: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
  product_items: ProductRow[];
}

const emptyForm = (): FormState => ({
  name: '',
  discount_type: 'FIXED',
  discount_value: '',
  start_date: '',
  end_date: '',
  is_active: true,
  product_items: [{ product_id: 0, min_quantity: 1 }],
});

function formatLocalDatetime(iso: string): string {
  if (!iso) return '';
  return iso.slice(0, 16); // "YYYY-MM-DDTHH:MM"
}

function getPromotionStatus(promo: Promotion): { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' } {
  if (!promo.is_active) return { label: 'Inactive', variant: 'secondary' };
  if (promo.is_currently_active) return { label: 'Active', variant: 'default' };
  const now = new Date();
  if (new Date(promo.start_date) > now) return { label: 'Scheduled', variant: 'outline' };
  return { label: 'Expired', variant: 'destructive' };
}

export default function PromotionsPage() {
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingPromotion, setEditingPromotion] = useState<Promotion | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Promotion | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [promoData, productData] = await Promise.all([
        getPromotions(),
        getProducts(),
      ]);
      setPromotions(promoData);
      const productsList = Array.isArray(productData) ? productData : (productData as any).results || [];
      setProducts(productsList);
    } catch (err) {
      toast.error('Failed to load promotions');
    } finally {
      setLoading(false);
    }
  };

  const openCreate = () => {
    setEditingPromotion(null);
    setForm(emptyForm());
    setDialogOpen(true);
  };

  const openEdit = (promo: Promotion) => {
    setEditingPromotion(promo);
    setForm({
      name: promo.name,
      discount_type: promo.discount_type,
      discount_value: promo.discount_value,
      start_date: formatLocalDatetime(promo.start_date),
      end_date: formatLocalDatetime(promo.end_date),
      is_active: promo.is_active,
      product_items: promo.products.length > 0
        ? promo.products.map(p => ({ product_id: p.product, min_quantity: p.min_quantity }))
        : [{ product_id: 0, min_quantity: 1 }],
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Name is required'); return; }
    if (!form.discount_value || isNaN(parseFloat(form.discount_value))) { toast.error('Discount value is required'); return; }
    if (!form.start_date || !form.end_date) { toast.error('Start and end dates are required'); return; }
    if (new Date(form.start_date) >= new Date(form.end_date)) { toast.error('End date must be after start date'); return; }
    const validItems = form.product_items.filter(p => p.product_id > 0);
    if (validItems.length === 0) { toast.error('At least one product is required'); return; }

    const payload: CreatePromotionRequest = {
      name: form.name.trim(),
      discount_type: form.discount_type,
      discount_value: form.discount_value,
      start_date: new Date(form.start_date).toISOString(),
      end_date: new Date(form.end_date).toISOString(),
      is_active: form.is_active,
      product_items: validItems,
    };

    try {
      setSaving(true);
      if (editingPromotion) {
        await updatePromotion(editingPromotion.id, payload);
        toast.success('Promotion updated');
      } else {
        await createPromotion(payload);
        toast.success('Promotion created');
      }
      setDialogOpen(false);
      loadData();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to save promotion');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deletePromotion(deleteTarget.id);
      toast.success('Promotion deleted');
      setDeleteTarget(null);
      loadData();
    } catch {
      toast.error('Failed to delete promotion');
    }
  };

  const addProductRow = () => {
    setForm(f => ({ ...f, product_items: [...f.product_items, { product_id: 0, min_quantity: 1 }] }));
  };

  const removeProductRow = (index: number) => {
    setForm(f => ({ ...f, product_items: f.product_items.filter((_, i) => i !== index) }));
  };

  const updateProductRow = (index: number, field: keyof ProductRow, value: number) => {
    setForm(f => ({
      ...f,
      product_items: f.product_items.map((row, i) => i === index ? { ...row, [field]: value } : row),
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Tag className="h-6 w-6" />
            Promotions
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Manage bundle discounts applied automatically during fulfillment
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" />
          New Promotion
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>All Promotions</CardTitle>
          <CardDescription>{promotions.length} promotion{promotions.length !== 1 ? 's' : ''} configured</CardDescription>
        </CardHeader>
        <CardContent>
          {promotions.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Tag className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>No promotions configured yet.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Products</TableHead>
                  <TableHead>Discount</TableHead>
                  <TableHead>Start</TableHead>
                  <TableHead>End</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {promotions.map(promo => {
                  const { label, variant } = getPromotionStatus(promo);
                  return (
                    <TableRow key={promo.id}>
                      <TableCell className="font-medium">{promo.name}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {promo.products.map(p => (
                            <Badge key={p.id} variant="outline" className="text-xs">
                              {p.product_code} ×{p.min_quantity}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        {promo.discount_type === 'FIXED'
                          ? `KES ${parseFloat(promo.discount_value).toLocaleString()}`
                          : `${promo.discount_value}%`}
                      </TableCell>
                      <TableCell className="text-sm">{new Date(promo.start_date).toLocaleDateString()}</TableCell>
                      <TableCell className="text-sm">{new Date(promo.end_date).toLocaleDateString()}</TableCell>
                      <TableCell>
                        <Badge variant={variant}>{label}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" size="sm" onClick={() => openEdit(promo)}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(promo)}>
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle className="text-lg">
              {editingPromotion ? 'Edit Promotion' : 'New Promotion'}
            </DialogTitle>
            <DialogDescription>
              {editingPromotion
                ? 'Update the promotion details below.'
                : 'Configure a new bundle discount promotion.'}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="overflow-y-auto max-h-[70vh]">
            <div className="space-y-5 py-1">

              {/* Promotion Name */}
              <div className="space-y-1.5">
                <Label className="text-sm font-medium">Promotion Name</Label>
                <Input
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Elements Bundle Discount"
                  className="h-10"
                />
              </div>

              {/* Discount */}
              <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Discount</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-sm">Type</Label>
                    <select
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      value={form.discount_type}
                      onChange={e => setForm(f => ({ ...f, discount_type: e.target.value as 'FIXED' | 'PERCENTAGE' }))}
                    >
                      <option value="FIXED">Fixed Amount (KES)</option>
                      <option value="PERCENTAGE">Percentage (%)</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-sm">
                      {form.discount_type === 'FIXED' ? 'Amount (KES)' : 'Percentage (%)'}
                    </Label>
                    <Input
                      type="text"
                      inputMode="decimal"
                      value={form.discount_value}
                      onChange={e => {
                        const val = e.target.value.replace(/[^0-9.]/g, '');
                        setForm(f => ({ ...f, discount_value: val }));
                      }}
                      placeholder={form.discount_type === 'FIXED' ? '1620' : '10'}
                      className="h-10"
                    />
                  </div>
                </div>
              </div>

              {/* Active Period */}
              <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Active Period</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-sm">Start Date & Time</Label>
                    <Input
                      type="datetime-local"
                      value={form.start_date}
                      onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                      className="h-10"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-sm">End Date & Time</Label>
                    <Input
                      type="datetime-local"
                      value={form.end_date}
                      onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
                      className="h-10"
                    />
                  </div>
                </div>
              </div>

              {/* Active toggle */}
              <div className="flex items-center justify-between rounded-lg border px-4 py-3">
                <div>
                  <p className="text-sm font-medium">Active</p>
                  <p className="text-xs text-muted-foreground">Enable for automatic application during fulfillment</p>
                </div>
                <input
                  type="checkbox"
                  id="is_active"
                  checked={form.is_active}
                  onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
                  className="h-5 w-5 accent-primary cursor-pointer"
                />
              </div>

              {/* Required Products */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <Label className="text-sm font-medium">Required Products</Label>
                    <p className="text-xs text-muted-foreground mt-0.5">Products that must be in the order to trigger this promotion</p>
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={addProductRow}>
                    <Plus className="h-3.5 w-3.5 mr-1.5" /> Add Product
                  </Button>
                </div>
                <div className="space-y-2">
                  {form.product_items.map((row, i) => (
                    <div key={i} className="rounded-lg border bg-muted/20 p-3 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-semibold shrink-0">
                            {i + 1}
                          </span>
                          <span className="text-xs font-medium text-muted-foreground">Product {i + 1}</span>
                        </div>
                        {form.product_items.length > 1 && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 text-destructive hover:text-destructive hover:bg-destructive/10 text-xs"
                            onClick={() => removeProductRow(i)}
                          >
                            <Trash2 className="h-3.5 w-3.5 mr-1" /> Remove
                          </Button>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Product</Label>
                        <select
                          className="w-full h-10 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          value={row.product_id || ''}
                          onChange={e => updateProductRow(i, 'product_id', Number(e.target.value))}
                        >
                          <option value="">Select product...</option>
                          {products.map(p => (
                            <option key={p.id} value={p.id}>{p.prod_name} ({p.prod_code})</option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Minimum Quantity</Label>
                        <Input
                          type="text"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          value={row.min_quantity === 0 ? '' : row.min_quantity}
                          onChange={e => {
                            const val = e.target.value.replace(/\D/g, '');
                            updateProductRow(i, 'min_quantity', val === '' ? 0 : Number(val));
                          }}
                          onBlur={() => {
                            if (row.min_quantity < 1) updateProductRow(i, 'min_quantity', 1);
                          }}
                          className="h-10 w-full"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          </DialogBody>

          <DialogFooter className="gap-2 pt-2">
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="flex-1 sm:flex-none">
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving} className="flex-1 sm:flex-none">
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {editingPromotion ? 'Save Changes' : 'Create Promotion'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={open => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Promotion</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deleteTarget?.name}"? This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
