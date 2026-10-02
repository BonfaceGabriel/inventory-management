import { useMemo, useState } from 'react';
import { Archive, Pencil, Plus, SpinnerGap, Trash, WarningCircle, X } from '@phosphor-icons/react';
import { toast } from 'sonner';
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { formatCurrency } from '@/services/api';
import { extractApiError } from '@/lib/error-utils';
import {
  useAdjustMerchandiseStock,
  useCreateMerchandiseCatalogItem,
  useDeleteMerchandiseCatalogItem,
  useMerchandiseCatalog,
  useMerchandiseDailyReport,
  useMerchandiseStock,
  useUpdateMerchandiseCatalogItem,
} from '@/services/queries/merchandise';
import type { MerchandiseCatalogItem } from '@/services/api';

/** One row per purchasable variant of a product. */
type VariantRow = {
  key: string;
  item_id: number;
  item_code: string;
  item_name: string;
  color: string;
  size: string;
  quantity: number;
  unit_price: string;
};

type ProductGroup = {
  item_id: number;
  item_code: string;
  item_name: string;
  unit_price: string;
  is_used: boolean;
  has_variants: boolean;
  variants: VariantRow[];
};

/**
 * Variants come from the colours/sizes declared on the product, matching the
 * backend rule: no options = one standard row, colours only = one row per
 * colour, sizes only = one row per size, both = full colour/size matrix.
 */
const variantLabel = (row: VariantRow): string => {
  if (row.color && row.size) return `${row.color} / ${row.size}`;
  if (row.color) return row.color;
  if (row.size) return row.size;
  return 'Standard';
};

const parseOptionList = (raw: string): string[] =>
  raw
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

/** Sizes offered as ready-made choices when creating a product. */
const STANDARD_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL'];

/**
 * Standard sizes first, then any size this product already declares that isn't
 * standard, so editing a product never silently drops an existing variant.
 */
const availableSizes = (declared: string[]): string[] => {
  const extras = declared.filter((size) => !STANDARD_SIZES.includes(size));
  return [...STANDARD_SIZES, ...extras.sort((a, b) => a.localeCompare(b))];
};

export default function MerchandiseFulfillmentPage() {
  const [activeTab, setActiveTab] = useState('products');
  const [stockDraftQuantities, setStockDraftQuantities] = useState<Record<string, string>>({});
  const [search, setSearch] = useState('');
  const [reportDate, setReportDate] = useState(new Date().toISOString().split('T')[0]);

  const { data: catalog = [], isLoading: isCatalogLoading } = useMerchandiseCatalog();
  const { data: stockRows = [], isLoading: isStockLoading, refetch: refetchStock } = useMerchandiseStock();
  const adjustStockMutation = useAdjustMerchandiseStock();
  const { data: dailyReport, isLoading: isReportLoading } = useMerchandiseDailyReport(reportDate);

  const stockByVariant = useMemo(() => {
    const map = new Map<string, { quantity: number; unit_price: string }>();
    for (const row of stockRows) {
      map.set(`${row.item_code}::${row.color || ''}::${row.size || ''}`, {
        quantity: row.quantity,
        unit_price: row.unit_price,
      });
    }
    return map;
  }, [stockRows]);

  /** Build one row per product variant, filling quantities from stock. */
  const variantRows = useMemo<VariantRow[]>(() => {
    const rows: VariantRow[] = [];

    for (const item of catalog) {
      const colors = item.options.filter((o) => o.option_type === 'COLOR').map((o) => o.value);
      const sizes = item.options.filter((o) => o.option_type === 'SIZE').map((o) => o.value);
      const colorAxis = colors.length ? colors : [''];
      const sizeAxis = sizes.length ? sizes : [''];

      for (const color of colorAxis) {
        for (const size of sizeAxis) {
          const key = `${item.code}::${color}::${size}`;
          const existing = stockByVariant.get(key);
          rows.push({
            key,
            item_id: item.id,
            item_code: item.code,
            item_name: item.name,
            color,
            size,
            quantity: existing?.quantity ?? 0,
            unit_price: existing?.unit_price ?? item.unit_price,
          });
        }
      }
    }

    return rows;
  }, [catalog, stockByVariant]);

  /** Group variants under their product so catalog and stock live together. */
  const productGroups = useMemo<ProductGroup[]>(() => {
    const groups = new Map<number, ProductGroup>();

    for (const row of variantRows) {
      const existing = groups.get(row.item_id);
      if (existing) {
        existing.variants.push(row);
      } else {
        const item = catalog.find((entry) => entry.id === row.item_id);
        groups.set(row.item_id, {
          item_id: row.item_id,
          item_code: row.item_code,
          item_name: row.item_name,
          unit_price: row.unit_price,
          is_used: item?.is_used ?? false,
          has_variants: item?.has_variants ?? false,
          variants: [row],
        });
      }
    }

    return Array.from(groups.values()).sort((a, b) => a.item_name.localeCompare(b.item_name));
  }, [variantRows, catalog]);

  const filteredGroups = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return productGroups;

    return productGroups
      .map((group) => {
        if (
          group.item_name.toLowerCase().includes(term) ||
          group.item_code.toLowerCase().includes(term)
        ) {
          return group;
        }
        const variants = group.variants.filter((variant) =>
          `${variant.color} ${variant.size}`.toLowerCase().includes(term)
        );
        return variants.length ? { ...group, variants } : null;
      })
      .filter((group): group is ProductGroup => group !== null);
  }, [productGroups, search]);

  const summary = useMemo(() => {
    const totalUnits = variantRows.reduce((sum, row) => sum + row.quantity, 0);
    const totalValue = variantRows.reduce(
      (sum, row) => sum + row.quantity * Number(row.unit_price),
      0
    );
    return { products: productGroups.length, totalUnits, totalValue };
  }, [variantRows, productGroups]);

  const getDraftQuantity = (row: VariantRow): number => {
    const raw = stockDraftQuantities[row.key];
    if (raw === undefined) return row.quantity;
    const parsed = Number.parseInt(raw, 10);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : row.quantity;
  };

  const setDraftQuantity = (rowKey: string, value: string) => {
    setStockDraftQuantities((current) => ({ ...current, [rowKey]: value }));
  };

  const saveVariantQuantity = async (row: VariantRow) => {
    const target = getDraftQuantity(row);
    const quantityChange = target - row.quantity;
    if (quantityChange === 0) {
      toast.info('No stock change for this variant');
      return;
    }

    try {
      await adjustStockMutation.mutateAsync({
        adjustments: [
          {
            item_code: row.item_code,
            quantity_change: quantityChange,
            color: row.color || undefined,
            size: row.size || undefined,
          },
        ],
      });
      toast.success('Stock updated');
      setStockDraftQuantities((current) => {
        const next = { ...current };
        delete next[row.key];
        return next;
      });
      await refetchStock();
    } catch (error: unknown) {
      toast.error(extractApiError(error, 'Failed to adjust stock'));
    }
  };

  // ── Product management state ──────────────────────────────────────────
  const createMutation = useCreateMerchandiseCatalogItem();
  const updateMutation = useUpdateMerchandiseCatalogItem();
  const deleteMutation = useDeleteMerchandiseCatalogItem();

  const [productDialogOpen, setProductDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<MerchandiseCatalogItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MerchandiseCatalogItem | null>(null);
  const [productForm, setProductForm] = useState({
    code: '',
    name: '',
    unit_price: '',
    colours: '',
    sizes: [] as string[],
  });
  const [productFormError, setProductFormError] = useState<string | null>(null);
  const [productSaving, setProductSaving] = useState(false);

  const openCreateDialog = () => {
    setEditingItem(null);
    setProductForm({ code: '', name: '', unit_price: '', colours: '', sizes: [] });
    setProductFormError(null);
    setProductDialogOpen(true);
  };

  const openEditDialog = (item: MerchandiseCatalogItem) => {
    setEditingItem(item);
    setProductForm({
      code: item.code,
      name: item.name,
      unit_price: item.unit_price,
      colours: item.options
        .filter((o) => o.option_type === 'COLOR')
        .map((o) => o.value)
        .join(', '),
      sizes: item.options.filter((o) => o.option_type === 'SIZE').map((o) => o.value),
    });
    setProductFormError(null);
    setProductDialogOpen(true);
  };

  const toggleSize = (size: string) => {
    setProductForm((current) => ({
      ...current,
      sizes: current.sizes.includes(size)
        ? current.sizes.filter((value) => value !== size)
        : [...current.sizes, size],
    }));
  };

  const handleProductSave = async () => {
    if (!productForm.code.trim() || !productForm.name.trim() || !productForm.unit_price) {
      setProductFormError('Code, Name, and Unit Price are required');
      return;
    }

    const options = [
      ...parseOptionList(productForm.colours).map((value) => ({
        option_type: 'COLOR' as const,
        value,
      })),
      ...productForm.sizes.map((value) => ({
        option_type: 'SIZE' as const,
        value,
      })),
    ];

    setProductSaving(true);
    setProductFormError(null);

    try {
      if (editingItem) {
        await updateMutation.mutateAsync({
          itemId: editingItem.id,
          payload: {
            code: productForm.code.trim(),
            name: productForm.name.trim(),
            unit_price: productForm.unit_price,
            options,
          },
        });
        toast.success('Product updated');
      } else {
        await createMutation.mutateAsync({
          code: productForm.code.trim(),
          name: productForm.name.trim(),
          unit_price: productForm.unit_price,
          options,
        });
        toast.success('Product added');
      }
      setProductDialogOpen(false);
      await refetchStock();
    } catch (error: unknown) {
      setProductFormError(extractApiError(error, 'Failed to save product'));
    } finally {
      setProductSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    try {
      const result = await deleteMutation.mutateAsync(target.id);
      if (result && 'archived' in result && result.archived) {
        toast.info(
          `"${target.name}" was used in past orders, so it was archived instead of deleted.`
        );
      } else {
        toast.success(`"${target.name}" deleted`);
      }
      setStockDraftQuantities({});
      await refetchStock();
    } catch (error: unknown) {
      toast.error(extractApiError(error, 'Failed to delete product'));
    }
  };

  if (isCatalogLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <SpinnerGap className="h-8 w-8 animate-spin text-[rgb(var(--color-primary))]" />
        <span className="ml-2 text-gray-600 dark:text-gray-400">Loading merchandise...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Merchandise</h1>
        <p className="text-gray-600 dark:text-gray-400">
          Manage merchandise products, stock, and reports.
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="products">Products &amp; Stock</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        {/* ════════════════════════════════════════════════════════════
            PRODUCTS & STOCK TAB
            ════════════════════════════════════════════════════════════ */}
        <TabsContent value="products" className="mt-4 space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card>
              <CardContent className="pt-4">
                <p className="text-xs text-gray-500 dark:text-gray-400">Products</p>
                <p className="text-xl font-semibold">{summary.products}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <p className="text-xs text-gray-500 dark:text-gray-400">Total Units</p>
                <p className="text-xl font-semibold">{summary.totalUnits}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <p className="text-xs text-gray-500 dark:text-gray-400">Stock Value</p>
                <p className="text-xl font-semibold">{formatCurrency(summary.totalValue)}</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle>Products &amp; Stock</CardTitle>
                  <CardDescription>
                    Add products, set colours and sizes to create variants, then type the
                    quantity you have on hand.
                  </CardDescription>
                </div>
                <div className="flex w-full gap-3 md:w-auto">
                  <Input
                    placeholder="Search product, code, colour, size..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="md:w-72"
                  />
                  <Button onClick={openCreateDialog}>
                    <Plus className="mr-2 h-4 w-4" />
                    Add Product
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {isStockLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                  <SpinnerGap className="h-4 w-4 animate-spin" />
                  Loading stock...
                </div>
              ) : productGroups.length === 0 ? (
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No merchandise products yet. Use Add Product to create one.
                </p>
              ) : filteredGroups.length === 0 ? (
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No products match &quot;{search}&quot;.
                </p>
              ) : (
                <div className="space-y-4">
                  {filteredGroups.map((group) => {
                    const groupUnits = group.variants.reduce(
                      (sum, variant) => sum + variant.quantity,
                      0
                    );
                    const groupValue = group.variants.reduce(
                      (sum, variant) => sum + variant.quantity * Number(variant.unit_price),
                      0
                    );
                    const item = catalog.find((entry) => entry.id === group.item_id);

                    return (
                      <Card key={group.item_id}>
                        <CardHeader className="pb-3">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                              <CardTitle className="flex items-center gap-2 text-base">
                                {group.item_name}
                                {group.has_variants && <Badge variant="outline">Variants</Badge>}
                              </CardTitle>
                              <CardDescription>
                                {group.item_code} • Unit {formatCurrency(group.unit_price)} •{' '}
                                {groupUnits} units • {formatCurrency(groupValue)}
                              </CardDescription>
                            </div>
                            <div className="flex gap-1">
                              {item && (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => openEditDialog(item)}
                                    title="Edit product"
                                  >
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => setDeleteTarget(item)}
                                    title={item.is_used ? 'Archive product' : 'Delete product'}
                                  >
                                    {item.is_used ? (
                                      <Archive className="h-4 w-4 text-amber-500" />
                                    ) : (
                                      <Trash className="h-4 w-4 text-red-500" />
                                    )}
                                  </Button>
                                </>
                              )}
                            </div>
                          </div>
                        </CardHeader>
                        <CardContent>
                          <div className="rounded-md border">
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead>Variant</TableHead>
                                  <TableHead className="text-right">In Stock</TableHead>
                                  <TableHead className="text-right">Stock Value</TableHead>
                                  <TableHead className="w-[140px]">Set Quantity</TableHead>
                                  <TableHead className="text-right">Change</TableHead>
                                  <TableHead className="text-right">New Value</TableHead>
                                  <TableHead className="w-[96px]">Action</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {group.variants
                                  .slice()
                                  .sort((a, b) => variantLabel(a).localeCompare(variantLabel(b)))
                                  .map((variant) => {
                                    const draftQty = getDraftQuantity(variant);
                                    const changed = draftQty !== variant.quantity;
                                    const deltaQty = draftQty - variant.quantity;
                                    const unit = Number(variant.unit_price);

                                    return (
                                      <TableRow key={variant.key}>
                                        <TableCell className="font-medium">
                                          {variantLabel(variant)}
                                        </TableCell>
                                        <TableCell className="text-right">
                                          {variant.quantity}
                                        </TableCell>
                                        <TableCell className="text-right">
                                          {formatCurrency(variant.quantity * unit)}
                                        </TableCell>
                                        <TableCell>
                                          <Input
                                            type="number"
                                            min={0}
                                            value={
                                              stockDraftQuantities[variant.key] ??
                                              String(variant.quantity)
                                            }
                                            onChange={(e) =>
                                              setDraftQuantity(variant.key, e.target.value)
                                            }
                                            className="h-8"
                                          />
                                        </TableCell>
                                        <TableCell
                                          className={`text-right ${
                                            deltaQty > 0
                                              ? 'text-green-700 dark:text-green-300'
                                              : deltaQty < 0
                                                ? 'text-red-700 dark:text-red-300'
                                                : 'text-gray-600 dark:text-gray-400'
                                          }`}
                                        >
                                          {deltaQty > 0 ? `+${deltaQty}` : deltaQty}
                                        </TableCell>
                                        <TableCell className="text-right font-medium">
                                          {formatCurrency(draftQty * unit)}
                                        </TableCell>
                                        <TableCell>
                                          <Button
                                            type="button"
                                            size="sm"
                                            variant={changed ? 'default' : 'outline'}
                                            disabled={adjustStockMutation.isPending || !changed}
                                            onClick={() => saveVariantQuantity(variant)}
                                          >
                                            Save
                                          </Button>
                                        </TableCell>
                                      </TableRow>
                                    );
                                  })}
                              </TableBody>
                            </Table>
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reports" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Merchandise Daily Report</CardTitle>
              <CardDescription>Daily quantities sold by product attributes.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="max-w-xs">
                <Input
                  type="date"
                  value={reportDate}
                  onChange={(e) => setReportDate(e.target.value)}
                  max={new Date().toISOString().split('T')[0]}
                />
              </div>

              {isReportLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                  <SpinnerGap className="h-4 w-4 animate-spin" />
                  Loading merchandise report...
                </div>
              ) : !dailyReport || dailyReport.rows.length === 0 ? (
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No merchandise sales found for selected date.
                </p>
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Product</TableHead>
                        <TableHead className="text-right">Quantity</TableHead>
                        <TableHead>Size</TableHead>
                        <TableHead>Colour</TableHead>
                        <TableHead className="text-right">Total Amount</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {dailyReport.rows.map((row, index) => (
                        <TableRow
                          key={`${row.product}-${row.size}-${row.colour}-${index}`}
                        >
                          <TableCell className="font-medium">{row.product}</TableCell>
                          <TableCell className="text-right">{row.quantity}</TableCell>
                          <TableCell>{row.size || 'n/a'}</TableCell>
                          <TableCell>{row.colour || 'n/a'}</TableCell>
                          <TableCell className="text-right">
                            {formatCurrency(row.total_amount)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ── Create / Edit Product Dialog ─────────────────────────────── */}
      <Dialog open={productDialogOpen} onOpenChange={setProductDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader onClose={() => setProductDialogOpen(false)}>
            <DialogTitle>{editingItem ? 'Edit Product' : 'Add Product'}</DialogTitle>
            <DialogDescription>
              {editingItem
                ? 'Update the product details and its variants.'
                : 'Add a merchandise product and optionally give it variants.'}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {productFormError && (
              <Alert variant="destructive" className="mb-4">
                <WarningCircle className="h-4 w-4" />
                <AlertDescription>{productFormError}</AlertDescription>
              </Alert>
            )}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="product-code">
                    Code <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    id="product-code"
                    value={productForm.code}
                    onChange={(e) =>
                      setProductForm({ ...productForm, code: e.target.value })
                    }
                    placeholder="e.g. TSHIRT-BLUE"
                    required
                  />
                </div>
                <div>
                  <Label htmlFor="product-price">
                    Unit Price (KES) <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    id="product-price"
                    type="number"
                    step="0.01"
                    min="0"
                    value={productForm.unit_price}
                    onChange={(e) =>
                      setProductForm({ ...productForm, unit_price: e.target.value })
                    }
                    placeholder="0.00"
                    required
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="product-name">
                  Name <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="product-name"
                  value={productForm.name}
                  onChange={(e) =>
                    setProductForm({ ...productForm, name: e.target.value })
                  }
                  placeholder="e.g. Premium Cotton T-Shirt"
                  required
                />
              </div>
              <div>
                <Label htmlFor="product-colours">
                  Colours <span className="text-xs text-gray-500">(comma-separated)</span>
                </Label>
                <Input
                  id="product-colours"
                  value={productForm.colours}
                  onChange={(e) =>
                    setProductForm({ ...productForm, colours: e.target.value })
                  }
                  placeholder="e.g. Black, White, Red"
                />
              </div>
              <div>
                <Label>Sizes <span className="text-xs text-gray-500">(tap to select)</span></Label>
                <div className="flex flex-wrap gap-2">
                  {availableSizes(productForm.sizes).map((size) => {
                    const selected = productForm.sizes.includes(size);
                    return (
                      <Button
                        key={size}
                        type="button"
                        size="sm"
                        variant={selected ? 'default' : 'outline'}
                        aria-pressed={selected}
                        className={
                          selected
                            ? 'bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]'
                            : undefined
                        }
                        onClick={() => toggleSize(size)}
                      >
                        {size}
                      </Button>
                    );
                  })}
                </div>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Select no sizes for a single product with one quantity. Pick sizes only for
                size variants, add colours for colour variants, or use both to get every
                colour/size combination.
              </p>
            </div>
          </DialogBody>
          <DialogFooter>
            <div className="flex w-full gap-2">
              <Button
                variant="outline"
                onClick={() => setProductDialogOpen(false)}
                disabled={productSaving}
                className="flex-1"
              >
                <X className="mr-2 h-4 w-4" />
                Cancel
              </Button>
              <Button
                onClick={handleProductSave}
                disabled={productSaving}
                className="flex-1 bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]"
              >
                <Plus className="mr-2 h-4 w-4" />
                {productSaving ? 'Saving...' : editingItem ? 'Save Changes' : 'Add Product'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete / Archive Confirmation Dialog ─────────────────────── */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {deleteTarget?.is_used ? 'Archive Product' : 'Delete Product'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget?.is_used ? (
                <>
                  <strong>{deleteTarget?.name}</strong> ({deleteTarget?.code}) has been used in
                  past merchandise orders, so it will be archived instead of deleted. It will
                  disappear from the catalog and can no longer be fulfilled, but past orders and
                  reports stay intact.
                </>
              ) : (
                <>
                  Are you sure you want to delete{' '}
                  <strong>{deleteTarget?.name}</strong> ({deleteTarget?.code})? This has never
                  been ordered, so it will be removed permanently along with its stock.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className={
                deleteTarget?.is_used
                  ? 'bg-amber-600 hover:bg-amber-700'
                  : 'bg-red-600 hover:bg-red-700'
              }
            >
              {deleteTarget?.is_used ? 'Archive' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}