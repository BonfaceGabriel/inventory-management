import { useMemo, useState } from 'react';
import { Pencil, Plus, SpinnerGap, Trash, WarningCircle, X } from '@phosphor-icons/react';
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
import { Select } from '@/components/ui/select';
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

type StockVariantRow = {
  key: string;
  item_code: string;
  item_name: string;
  item_type: 'TSHIRT' | 'HAT' | 'COFFEE';
  color: string;
  size: string;
  quantity: number;
  unit_price: string;
};

type ProductStockGroup = {
  item_code: string;
  item_name: string;
  item_type: 'TSHIRT' | 'HAT' | 'COFFEE';
  unit_price: string;
  variants: StockVariantRow[];
};

export default function MerchandiseFulfillmentPage() {
  const [activeTab, setActiveTab] = useState('stock');
  const [stockDraftQuantities, setStockDraftQuantities] = useState<Record<string, string>>({});
  const [stockSearch, setStockSearch] = useState('');
  const [stockTypeFilter, setStockTypeFilter] = useState<'ALL' | 'TSHIRT' | 'HAT' | 'COFFEE'>('ALL');
  const [reportDate, setReportDate] = useState(new Date().toISOString().split('T')[0]);

  const { data: catalog = [], isLoading: isCatalogLoading } = useMerchandiseCatalog();
  const { data: stockRows = [], isLoading: isStockLoading, refetch: refetchStock } = useMerchandiseStock();
  const adjustStockMutation = useAdjustMerchandiseStock();
  const { data: dailyReport, isLoading: isReportLoading } = useMerchandiseDailyReport(reportDate);

  const displayStockRows = useMemo(() => {
    const rows: StockVariantRow[] = [];

    const stockByVariant = new Map<string, { quantity: number; unit_price: string }>();
    for (const row of stockRows) {
      const key = `${row.item_code}::${row.color || ''}::${row.size || ''}`;
      stockByVariant.set(key, {
        quantity: row.quantity,
        unit_price: row.unit_price,
      });
    }

    for (const item of catalog) {
      const colors = item.options.filter((o) => o.option_type === 'COLOR').map((o) => o.value);
      const sizes = item.options.filter((o) => o.option_type === 'SIZE').map((o) => o.value);

      if (item.item_type === 'TSHIRT') {
        for (const color of colors) {
          for (const size of sizes) {
            const key = `${item.code}::${color}::${size}`;
            const existing = stockByVariant.get(key);
            rows.push({
              key,
              item_code: item.code,
              item_name: item.name,
              item_type: item.item_type,
              color,
              size,
              quantity: existing?.quantity ?? 0,
              unit_price: existing?.unit_price ?? item.unit_price,
            });
          }
        }
      } else if (item.item_type === 'HAT') {
        for (const color of colors) {
          const key = `${item.code}::${color}::`;
          const existing = stockByVariant.get(key);
          rows.push({
            key,
            item_code: item.code,
            item_name: item.name,
            item_type: item.item_type,
            color,
            size: '',
            quantity: existing?.quantity ?? 0,
            unit_price: existing?.unit_price ?? item.unit_price,
          });
        }
      } else {
        const key = `${item.code}::::`;
        const existing = stockByVariant.get(key);
        rows.push({
          key,
          item_code: item.code,
          item_name: item.name,
          item_type: item.item_type,
          color: '',
          size: '',
          quantity: existing?.quantity ?? 0,
          unit_price: existing?.unit_price ?? item.unit_price,
        });
      }
    }

    return rows;
  }, [catalog, stockRows]);

  const groupedStock = useMemo(() => {
    const grouped = new Map<string, ProductStockGroup>();
    for (const row of displayStockRows) {
      const existing = grouped.get(row.item_code);
      if (existing) {
        existing.variants.push(row);
      } else {
        grouped.set(row.item_code, {
          item_code: row.item_code,
          item_name: row.item_name,
          item_type: row.item_type,
          unit_price: row.unit_price,
          variants: [row],
        });
      }
    }
    return Array.from(grouped.values()).sort((a, b) => a.item_name.localeCompare(b.item_name));
  }, [displayStockRows]);

  const filteredGroupedStock = useMemo(() => {
    const search = stockSearch.trim().toLowerCase();
    return groupedStock
      .filter((group) => stockTypeFilter === 'ALL' || group.item_type === stockTypeFilter)
      .map((group) => {
        if (!search) return group;
        const variants = group.variants.filter((variant) => {
          const variantLabel = `${variant.color} ${variant.size}`.toLowerCase();
          return (
            group.item_name.toLowerCase().includes(search) ||
            group.item_code.toLowerCase().includes(search) ||
            variantLabel.includes(search)
          );
        });
        return { ...group, variants };
      })
      .filter((group) => group.variants.length > 0);
  }, [groupedStock, stockSearch, stockTypeFilter]);

  const stockSummary = useMemo(() => {
    const totalVariants = displayStockRows.length;
    const totalUnits = displayStockRows.reduce((sum, row) => sum + row.quantity, 0);
    const totalValue = displayStockRows.reduce(
      (sum, row) => sum + row.quantity * Number(row.unit_price),
      0
    );
    return { totalVariants, totalUnits, totalValue };
  }, [displayStockRows]);

  const parseStockDraft = (raw: string, fallback: number): number => {
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isInteger(parsed) || parsed < 0) {
      return fallback;
    }
    return parsed;
  };

  const getDraftQuantity = (row: StockVariantRow): number => {
    const raw = stockDraftQuantities[row.key];
    if (raw === undefined) {
      return row.quantity;
    }
    return parseStockDraft(raw, row.quantity);
  };

  const setDraftQuantity = (rowKey: string, value: string) => {
    setStockDraftQuantities((current) => ({
      ...current,
      [rowKey]: value,
    }));
  };

  const getVariantLabel = (row: StockVariantRow): string => {
    if (row.item_type === 'TSHIRT') return `${row.color} / ${row.size}`;
    if (row.item_type === 'HAT') return row.color || 'n/a';
    return 'Standard';
  };

  const saveVariantQuantity = async (row: StockVariantRow) => {
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

  // ── Catalog management state ──────────────────────────────────────────
  const createMutation = useCreateMerchandiseCatalogItem();
  const updateMutation = useUpdateMerchandiseCatalogItem();
  const deleteMutation = useDeleteMerchandiseCatalogItem();

  const [catalogDialogOpen, setCatalogDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<MerchandiseCatalogItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MerchandiseCatalogItem | null>(null);
  const [catalogForm, setCatalogForm] = useState<{
    code: string;
    name: string;
    item_type: 'TSHIRT' | 'HAT' | 'COFFEE';
    unit_price: string;
    colours: string;
    sizes: string;
  }>({ code: '', name: '', item_type: 'TSHIRT', unit_price: '', colours: '', sizes: '' });
  const [catalogFormError, setCatalogFormError] = useState<string | null>(null);
  const [catalogSaving, setCatalogSaving] = useState(false);

  const openCreateDialog = () => {
    setEditingItem(null);
    setCatalogForm({ code: '', name: '', item_type: 'TSHIRT', unit_price: '', colours: '', sizes: '' });
    setCatalogFormError(null);
    setCatalogDialogOpen(true);
  };

  const openEditDialog = (item: MerchandiseCatalogItem) => {
    setEditingItem(item);
    const colours = item.options.filter((o) => o.option_type === 'COLOR').map((o) => o.value).join(', ');
    const sizes = item.options.filter((o) => o.option_type === 'SIZE').map((o) => o.value).join(', ');
    setCatalogForm({
      code: item.code,
      name: item.name,
      item_type: item.item_type,
      unit_price: item.unit_price,
      colours,
      sizes,
    });
    setCatalogFormError(null);
    setCatalogDialogOpen(true);
  };

  const handleCatalogSave = async () => {
    if (!catalogForm.code || !catalogForm.name || !catalogForm.unit_price) {
      setCatalogFormError('Code, Name, and Unit Price are required');
      return;
    }
    setCatalogSaving(true);
    setCatalogFormError(null);

    const options: { option_type: 'COLOR' | 'SIZE'; value: string }[] = [];
    const colours = catalogForm.colours.split(',').map((s) => s.trim()).filter(Boolean);
    const sizes = catalogForm.sizes.split(',').map((s) => s.trim()).filter(Boolean);
    for (const colour of colours) options.push({ option_type: 'COLOR', value: colour });
    for (const size of sizes) options.push({ option_type: 'SIZE', value: size });

    const payload = {
      code: catalogForm.code,
      name: catalogForm.name,
      item_type: catalogForm.item_type,
      unit_price: catalogForm.unit_price,
      options,
    };

    try {
      if (editingItem) {
        await updateMutation.mutateAsync({ itemId: editingItem.id, payload });
        toast.success('Catalog item updated');
      } else {
        await createMutation.mutateAsync(payload);
        toast.success('Catalog item created');
      }
      setCatalogDialogOpen(false);
    } catch (error: unknown) {
      setCatalogFormError(extractApiError(error, 'Failed to save catalog item'));
    } finally {
      setCatalogSaving(false);
    }
  };

  const handleCatalogDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      toast.success(`"${deleteTarget.name}" deleted`);
      setDeleteTarget(null);
    } catch (error: unknown) {
      toast.error(extractApiError(error, 'Failed to delete catalog item'));
      setDeleteTarget(null);
    }
  };

  const itemTypeLabel = (t: string) =>
    ({ TSHIRT: 'Tshirt', HAT: 'Hat', COFFEE: 'Coffee' })[t] || t;

  // ── Filter state for catalog tab ──────────────────────────────────────
  const [catalogSearch, setCatalogSearch] = useState('');
  const [catalogTypeFilter, setCatalogTypeFilter] = useState<'ALL' | 'TSHIRT' | 'HAT' | 'COFFEE'>('ALL');

  const filteredCatalog = useMemo(() => {
    const search = catalogSearch.trim().toLowerCase();
    return (catalog ?? []).filter((item) => {
      if (catalogTypeFilter !== 'ALL' && item.item_type !== catalogTypeFilter) return false;
      if (!search) return true;
      return (
        item.name.toLowerCase().includes(search) ||
        item.code.toLowerCase().includes(search)
      );
    });
  }, [catalog, catalogSearch, catalogTypeFilter]);

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
          Manage merchandise catalog, stock, and reports.
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="catalog">Catalog</TabsTrigger>
          <TabsTrigger value="stock">Stock</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        {/* ════════════════════════════════════════════════════════════
            CATALOG TAB
            ════════════════════════════════════════════════════════════ */}
        <TabsContent value="catalog" className="mt-4 space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Merchandise Catalog</CardTitle>
                  <CardDescription>
                    Manage product types, prices, and colour/size options.
                  </CardDescription>
                </div>
                <Button onClick={openCreateDialog}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Item
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <Input
                  placeholder="Search by name or code..."
                  value={catalogSearch}
                  onChange={(e) => setCatalogSearch(e.target.value)}
                />
                <Select
                  value={catalogTypeFilter}
                  onChange={(e) =>
                    setCatalogTypeFilter(e.target.value as 'ALL' | 'TSHIRT' | 'HAT' | 'COFFEE')
                  }
                >
                  <option value="ALL">All Types</option>
                  <option value="TSHIRT">Tshirt</option>
                  <option value="HAT">Hat</option>
                  <option value="COFFEE">Coffee</option>
                </Select>
              </div>

              {filteredCatalog.length === 0 ? (
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No catalog items found. Add one to get started.
                </p>
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Code</TableHead>
                        <TableHead>Name</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead className="text-right">Unit Price</TableHead>
                        <TableHead>Colours</TableHead>
                        <TableHead>Sizes</TableHead>
                        <TableHead className="w-[100px]">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredCatalog.map((item) => {
                        const colours = item.options
                          .filter((o) => o.option_type === 'COLOR')
                          .map((o) => o.value);
                        const sizes = item.options
                          .filter((o) => o.option_type === 'SIZE')
                          .map((o) => o.value);
                        return (
                          <TableRow key={item.id}>
                            <TableCell className="font-mono text-sm font-medium">
                              {item.code}
                            </TableCell>
                            <TableCell className="font-medium">{item.name}</TableCell>
                            <TableCell>
                              <Badge variant="outline">{itemTypeLabel(item.item_type)}</Badge>
                            </TableCell>
                            <TableCell className="text-right font-medium">
                              {formatCurrency(item.unit_price)}
                            </TableCell>
                            <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                              {colours.join(', ') || '—'}
                            </TableCell>
                            <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                              {sizes.join(', ') || '—'}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-1">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => openEditDialog(item)}
                                  title="Edit"
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => setDeleteTarget(item)}
                                  title="Delete"
                                >
                                  <Trash className="h-4 w-4 text-red-500" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="stock" className="mt-4 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Merchandise Stock</CardTitle>
              <CardDescription>
                Set target quantity per variant. Review quantity and value impact before saving.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isStockLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                  <SpinnerGap className="h-4 w-4 animate-spin" />
                  Loading stock...
                </div>
              ) : groupedStock.length === 0 ? (
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No merchandise catalog found. Seed catalog first.
                </p>
              ) : (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <Card>
                      <CardContent className="pt-4">
                        <p className="text-xs text-gray-500 dark:text-gray-400">Total Variants</p>
                        <p className="text-xl font-semibold">{stockSummary.totalVariants}</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-4">
                        <p className="text-xs text-gray-500 dark:text-gray-400">Total Units</p>
                        <p className="text-xl font-semibold">{stockSummary.totalUnits}</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-4">
                        <p className="text-xs text-gray-500 dark:text-gray-400">Stock Value</p>
                        <p className="text-xl font-semibold">{formatCurrency(stockSummary.totalValue)}</p>
                      </CardContent>
                    </Card>
                  </div>

                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="md:col-span-2">
                      <Input
                        placeholder="Search product, code, color, size..."
                        value={stockSearch}
                        onChange={(e) => setStockSearch(e.target.value)}
                      />
                    </div>
                    <Select
                      value={stockTypeFilter}
                      onChange={(e) =>
                        setStockTypeFilter(e.target.value as 'ALL' | 'TSHIRT' | 'HAT' | 'COFFEE')
                      }
                    >
                      <option value="ALL">All Types</option>
                      <option value="TSHIRT">Tshirt</option>
                      <option value="HAT">Hat</option>
                      <option value="COFFEE">Coffee</option>
                    </Select>
                  </div>

                  {filteredGroupedStock.length === 0 ? (
                    <Card>
                      <CardContent className="py-6 text-sm text-gray-600 dark:text-gray-400">
                        No variants match the current filter.
                      </CardContent>
                    </Card>
                  ) : null}

                  {filteredGroupedStock.map((group) => {
                    const groupUnits = group.variants.reduce((sum, variant) => sum + variant.quantity, 0);
                    const groupValue = group.variants.reduce(
                      (sum, variant) => sum + variant.quantity * Number(variant.unit_price),
                      0
                    );

                    return (
                      <Card key={group.item_code}>
                        <CardHeader className="pb-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <CardTitle className="text-base">{group.item_name}</CardTitle>
                            <Badge variant="outline">{group.item_type}</Badge>
                          </div>
                          <CardDescription>
                            {group.item_code} • Unit {formatCurrency(group.unit_price)} • {groupUnits} units •{' '}
                            {formatCurrency(groupValue)}
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <div className="rounded-md border">
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead>Variant</TableHead>
                                  <TableHead className="text-right">Current Qty</TableHead>
                                  <TableHead className="text-right">Current Value</TableHead>
                                  <TableHead className="w-[140px]">Set Qty</TableHead>
                                  <TableHead className="text-right">Delta Qty</TableHead>
                                  <TableHead className="text-right">Delta Value</TableHead>
                                  <TableHead className="text-right">New Value</TableHead>
                                  <TableHead className="w-[96px]">Action</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {group.variants
                                  .slice()
                                  .sort((a, b) => getVariantLabel(a).localeCompare(getVariantLabel(b)))
                                  .map((variant) => {
                                    const draftQty = getDraftQuantity(variant);
                                    const changed = draftQty !== variant.quantity;
                                    const deltaQty = draftQty - variant.quantity;
                                    const unit = Number(variant.unit_price);
                                    const currentValue = variant.quantity * unit;
                                    const deltaValue = deltaQty * unit;
                                    const newValue = draftQty * unit;

                                    return (
                                      <TableRow key={variant.key}>
                                        <TableCell className="font-medium">{getVariantLabel(variant)}</TableCell>
                                        <TableCell className="text-right">{variant.quantity}</TableCell>
                                        <TableCell className="text-right">{formatCurrency(currentValue)}</TableCell>
                                        <TableCell>
                                          <Input
                                            type="number"
                                            min={0}
                                            value={stockDraftQuantities[variant.key] ?? String(variant.quantity)}
                                            onChange={(e) => setDraftQuantity(variant.key, e.target.value)}
                                            className="h-8"
                                          />
                                        </TableCell>
                                        <TableCell className={`text-right ${deltaQty > 0 ? 'text-green-700 dark:text-green-300' : deltaQty < 0 ? 'text-red-700 dark:text-red-300' : 'text-gray-600 dark:text-gray-400'}`}>
                                          {deltaQty > 0 ? `+${deltaQty}` : deltaQty}
                                        </TableCell>
                                        <TableCell className={`text-right ${deltaValue > 0 ? 'text-green-700 dark:text-green-300' : deltaValue < 0 ? 'text-red-700 dark:text-red-300' : 'text-gray-600 dark:text-gray-400'}`}>
                                          {deltaValue > 0 ? `+${formatCurrency(deltaValue)}` : formatCurrency(deltaValue)}
                                        </TableCell>
                                        <TableCell className="text-right font-medium">{formatCurrency(newValue)}</TableCell>
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
                        <TableRow key={`${row.product}-${row.size}-${row.colour}-${index}`}>
                          <TableCell className="font-medium">{row.product}</TableCell>
                          <TableCell className="text-right">{row.quantity}</TableCell>
                          <TableCell>{row.size || 'n/a'}</TableCell>
                          <TableCell>{row.colour || 'n/a'}</TableCell>
                          <TableCell className="text-right">{formatCurrency(row.total_amount)}</TableCell>
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

      {/* ── Create / Edit Catalog Item Dialog ────────────────────────── */}
      <Dialog open={catalogDialogOpen} onOpenChange={setCatalogDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader onClose={() => setCatalogDialogOpen(false)}>
            <DialogTitle>{editingItem ? 'Edit Catalog Item' : 'Add Catalog Item'}</DialogTitle>
            <DialogDescription>
              {editingItem
                ? 'Update the product details and options.'
                : 'Add a new product to the merchandise catalog.'}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {catalogFormError && (
              <Alert variant="destructive" className="mb-4">
                <WarningCircle className="h-4 w-4" />
                <AlertDescription>{catalogFormError}</AlertDescription>
              </Alert>
            )}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="item-code">
                    Code <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    id="item-code"
                    value={catalogForm.code}
                    onChange={(e) => setCatalogForm({ ...catalogForm, code: e.target.value })}
                    placeholder="e.g., TSH-BLACK"
                    required
                  />
                </div>
                <div>
                  <Label htmlFor="item-type">Type</Label>
                  <Select
                    id="item-type"
                    value={catalogForm.item_type}
                    onChange={(e) =>
                      setCatalogForm({
                        ...catalogForm,
                        item_type: e.target.value as 'TSHIRT' | 'HAT' | 'COFFEE',
                        colours: e.target.value === 'COFFEE' ? '' : catalogForm.colours,
                        sizes: e.target.value === 'COFFEE' || e.target.value === 'HAT' ? '' : catalogForm.sizes,
                      })
                    }
                  >
                    <option value="TSHIRT">Tshirt</option>
                    <option value="HAT">Hat</option>
                    <option value="COFFEE">Coffee</option>
                  </Select>
                </div>
              </div>
              <div>
                <Label htmlFor="item-name">
                  Name <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="item-name"
                  value={catalogForm.name}
                  onChange={(e) => setCatalogForm({ ...catalogForm, name: e.target.value })}
                  placeholder="e.g., Premium Cotton Tshirt"
                  required
                />
              </div>
              <div>
                <Label htmlFor="item-price">
                  Unit Price (KES) <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="item-price"
                  type="number"
                  step="0.01"
                  min="0"
                  value={catalogForm.unit_price}
                  onChange={(e) => setCatalogForm({ ...catalogForm, unit_price: e.target.value })}
                  placeholder="0.00"
                  required
                />
              </div>
              {(catalogForm.item_type === 'TSHIRT' || catalogForm.item_type === 'HAT') && (
                <div>
                  <Label htmlFor="item-colours">
                    Colours <span className="text-xs text-gray-500">(comma-separated)</span>
                  </Label>
                  <Input
                    id="item-colours"
                    value={catalogForm.colours}
                    onChange={(e) => setCatalogForm({ ...catalogForm, colours: e.target.value })}
                    placeholder="e.g., Black, White, Red"
                  />
                </div>
              )}
              {catalogForm.item_type === 'TSHIRT' && (
                <div>
                  <Label htmlFor="item-sizes">
                    Sizes <span className="text-xs text-gray-500">(comma-separated)</span>
                  </Label>
                  <Input
                    id="item-sizes"
                    value={catalogForm.sizes}
                    onChange={(e) => setCatalogForm({ ...catalogForm, sizes: e.target.value })}
                    placeholder="e.g., S, M, L, XL"
                  />
                </div>
              )}
            </div>
          </DialogBody>
          <DialogFooter>
            <div className="flex gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => setCatalogDialogOpen(false)}
                disabled={catalogSaving}
                className="flex-1"
              >
                <X className="mr-2 h-4 w-4" />
                Cancel
              </Button>
              <Button
                onClick={handleCatalogSave}
                disabled={catalogSaving}
                className="flex-1 bg-[rgb(var(--color-primary))] hover:bg-[rgb(var(--color-primary))]/[0.85]"
              >
                <Plus className="mr-2 h-4 w-4" />
                {catalogSaving ? 'Saving...' : editingItem ? 'Save Changes' : 'Add Item'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete Confirmation Dialog ───────────────────────────────── */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Catalog Item</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{deleteTarget?.name}</strong> ({deleteTarget?.code})?
              This action cannot be undone. Items referenced in existing orders will be protected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleCatalogDelete}
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
