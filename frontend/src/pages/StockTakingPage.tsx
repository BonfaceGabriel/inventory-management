import { useState, useEffect, useRef } from 'react';
import { useNavigate, useBeforeUnload } from 'react-router';
import { toast } from 'sonner';
import {
  createStockTakeSession, getStockTakeSession, scanBulkToStockTake,
  completeStockTakeSession, removeStockTakeItem, updateStockTakeItemQuantity,
  listActiveStockTakeSessions, cancelStockTakeSession,
  cancelAllActiveStockTakeSessions, updateStockTakeKitQuantity, getProducts,
  type Product,
} from '../services/api';
import type { StockTakeSession, StockTakeItem } from '../types/transaction.types';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { cn } from '../lib/utils';
import {
  Package, Trash, CheckCircle, Plus, Scan, FloppyDisk,
  ClipboardText, XCircle, WarningCircle, ArrowLeft, Gift, GearSix,
  MagnifyingGlass, Minus,
} from '@phosphor-icons/react';
import BarcodeScanner from '../components/scanner/BarcodeScanner';
import type { ParsedBarcode } from '../utils/barcodeParser';
import { extractApiError } from '../lib/error-utils';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../components/ui/alert-dialog';

interface PendingScan {
  product_id: number;
  quantity: number;
  product: Product;
}

export default function StockTakingPage() {
  const navigate = useNavigate();
  const [session, setSession] = useState<StockTakeSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [activeSessions, setActiveSessions] = useState<StockTakeSession[]>([]);
  const [sessionToCancel, setSessionToCancel] = useState<string | null>(null);
  const [showCancelAllDialog, setShowCancelAllDialog] = useState(false);
  const [showCurrentSessionCancelDialog, setShowCurrentSessionCancelDialog] = useState(false);
  const [activeTab, setActiveTab] = useState<'current' | 'manage'>('current');

  // Manual entry states
  const [inputMode, setInputMode] = useState<'scanner' | 'manual'>('scanner');
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [manualQuantity, setManualQuantity] = useState(1);

  // Pending scans (not yet flushed to backend)
  const [pendingScans, setPendingScans] = useState<Map<number, PendingScan>>(new Map());

  const kitQuantityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const quantityUpdateTimerRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  // Pre-fetch ALL products once on mount (covers scanner lookup + manual picker)
  useEffect(() => {
    if (products.length === 0) {
      getProducts({ page_size: 10000 }).then(data => setProducts(data.results)).catch(() => {});
    }
  }, [products.length]);

  useBeforeUnload((e) => {
    if (session?.status === 'DRAFT' && pendingScans.size > 0) { e.preventDefault(); return 'You have unsaved scans.'; }
    if (session?.status === 'DRAFT') { e.preventDefault(); return 'You have an active stock take session.'; }
  }, { capture: true });

  useEffect(() => () => {
    if (kitQuantityTimerRef.current) clearTimeout(kitQuantityTimerRef.current);
    quantityUpdateTimerRef.current.forEach(t => clearTimeout(t));
  }, []);

  const handleScan = async (barcode: ParsedBarcode) => {
    if (!session) return;
    try {
      setProcessing(true);
      const product = products.find(p =>
        p.sku === barcode.sku || p.prod_code === barcode.prod_code || p.sku === barcode.barcode
      );
      if (!product) {
        toast.error(`Product not found: ${barcode.sku || barcode.prod_code || barcode.barcode}`);
        return;
      }
      setPendingScans(prev => {
        const next = new Map(prev);
        const existing = next.get(product.id);
        if (existing) {
          next.set(product.id, { ...existing, quantity: existing.quantity + barcode.quantity });
        } else {
          next.set(product.id, { product_id: product.id, quantity: barcode.quantity, product });
        }
        return next;
      });
      toast.success(`Scanned ${barcode.quantity}x ${product.prod_name}`);
    } catch (error: any) {
      toast.error(extractApiError(error, 'Failed to scan'));
    } finally {
      setProcessing(false);
    }
  };

  const handleManualAdd = async () => {
    if (!session || !selectedProduct) return;
    setPendingScans(prev => {
      const next = new Map(prev);
      const existing = next.get(selectedProduct.id);
      if (existing) {
        next.set(selectedProduct.id, { ...existing, quantity: existing.quantity + manualQuantity });
      } else {
        next.set(selectedProduct.id, { product_id: selectedProduct.id, quantity: manualQuantity, product: selectedProduct });
      }
      return next;
    });
    toast.success(`Added ${manualQuantity}x ${selectedProduct.prod_name}`);
    setSelectedProduct(null);
    setManualQuantity(1);
    setProductSearch('');
  };

  const flushPendingScans = async () => {
    if (!session || pendingScans.size === 0) return;
    const scans = Array.from(pendingScans.values()).map(s => ({
      product_id: s.product_id,
      quantity: s.quantity,
    }));
    try {
      setProcessing(true);
      const response = await scanBulkToStockTake(session.session_id, scans, 'user');
      setPendingScans(new Map());
      if (response.items) {
        setSession(prev => {
          if (!prev) return prev;
          const savedIds = new Set(response.items.map((i: StockTakeItem) => i.product));
          const merged = [...(prev.items || []).filter((i: StockTakeItem) => !savedIds.has(i.product)), ...response.items];
          return { ...prev, items: merged, items_count: merged.length, total_quantity_added: merged.reduce((s: number, i: StockTakeItem) => s + i.quantity_scanned, 0) };
        });
      }
      await fetchSessionDetails(session.session_id);
      toast.success('Saved all scanned items');
    } catch (error: any) {
      toast.error(extractApiError(error, 'Failed to save scans'));
      await fetchSessionDetails(session.session_id);
    } finally {
      setProcessing(false);
    }
  };

  const removePendingScan = (productId: number) => {
    setPendingScans(prev => {
      const next = new Map(prev);
      next.delete(productId);
      return next;
    });
  };

  const filteredProducts = products.filter(p =>
    p.prod_name.toLowerCase().includes(productSearch.toLowerCase()) ||
    p.prod_code.toLowerCase().includes(productSearch.toLowerCase()) ||
    p.sku?.toLowerCase().includes(productSearch.toLowerCase())
  );

  const handleStartSession = async () => {
    try { setLoading(true); const data = await createStockTakeSession('user', 'Stock taking session'); setSession(data); toast.success(`Session ${data.session_id} started`); } catch { toast.error('Failed to start session'); } finally { setLoading(false); }
  };

  const fetchSessionDetails = async (sessionId: string) => {
    try { setLoading(true); setSession(await getStockTakeSession(sessionId)); } catch { toast.error('Failed to load session'); } finally { setLoading(false); }
  };

  const handleRemoveItem = async (itemId: number) => {
    if (!session) return;
    try { setProcessing(true); await removeStockTakeItem(session.session_id, itemId); toast.success('Item removed'); await fetchSessionDetails(session.session_id); } catch { toast.error('Failed to remove item'); } finally { setProcessing(false); }
  };

  const handleQuantityChange = (itemId: number, newQuantity: number) => {
    if (!session || newQuantity < 0) return;
    setSession({ ...session, items: session.items?.map((item: StockTakeItem) => item.id === itemId ? { ...item, quantity_scanned: newQuantity, quantity_after: item.quantity_before + newQuantity } : item), total_quantity_added: session.items?.reduce((sum: number, item: StockTakeItem) => sum + (item.id === itemId ? newQuantity : item.quantity_scanned), 0) || 0 });
    const existingTimer = quantityUpdateTimerRef.current.get(itemId);
    if (existingTimer) clearTimeout(existingTimer);
    quantityUpdateTimerRef.current.set(itemId, setTimeout(async () => {
      try { await updateStockTakeItemQuantity(session.session_id, itemId, newQuantity); } catch { toast.error('Failed to update quantity'); await fetchSessionDetails(session.session_id); } finally { quantityUpdateTimerRef.current.delete(itemId); }
    }, 1000));
  };

  const handleKitQuantityChange = (newQuantity: number) => {
    if (!session || newQuantity < 0) return;
    setSession({ ...session, kit_quantity: newQuantity });
    if (kitQuantityTimerRef.current) clearTimeout(kitQuantityTimerRef.current);
    kitQuantityTimerRef.current = setTimeout(async () => {
      try { await updateStockTakeKitQuantity(session.session_id, newQuantity); } catch { toast.error('Failed to update kits'); await fetchSessionDetails(session.session_id); }
    }, 1000);
  };

  const handleComplete = async () => {
    if (!session) return;
    const hasScannedItems = Boolean(session.items && session.items.length > 0);
    const hasKitQuantity = Boolean((session.kit_quantity ?? 0) > 0);
    const hasPending = pendingScans.size > 0;
    if (!hasScannedItems && !hasKitQuantity && !hasPending) { toast.error('No products or kits scanned'); return; }
    try {
      setProcessing(true);
      if (hasPending) await flushPendingScans();
      await completeStockTakeSession(session.session_id, 'user');
      toast.success('Session completed! Inventory updated.');
      await fetchSessionDetails(session.session_id);
    } catch (error: any) { toast.error(extractApiError(error, 'Failed to complete')); } finally { setProcessing(false); }
  };

  const handleCancelSession = async (sessionId: string) => {
    try { setProcessing(true); await cancelStockTakeSession(sessionId, 'admin'); toast.success(`Session ${sessionId} cancelled`); if (session?.session_id === sessionId) { setSession(null); setPendingScans(new Map()); } setSessionToCancel(null); setShowCurrentSessionCancelDialog(false); } catch (error: any) { toast.error(extractApiError(error, 'Failed to cancel')); } finally { setProcessing(false); }
  };

  const handleCancelAllSessions = async () => {
    try { setProcessing(true); const response = await cancelAllActiveStockTakeSessions('admin'); toast.success(response.message || 'All cancelled'); setShowCancelAllDialog(false); } catch (error: any) { toast.error(extractApiError(error, 'Failed to cancel all')); } finally { setProcessing(false); }
  };

  useEffect(() => { if (activeTab === 'manage') listActiveStockTakeSessions().then(r => setActiveSessions(r.sessions || [])).catch(() => {}); }, [activeTab]);

  const isDraft = session?.status === 'DRAFT';
  const isCompleted = session?.status === 'COMPLETED';
  const pendingCount = pendingScans.size;

  // Merge pending scans + saved items for display
  const displayItems: Array<{ key: string; type: 'pending' | 'saved'; item: PendingScan | StockTakeItem; id: number; productId: number; productName: string; productCode: string; sku: string; quantityBefore: number; quantityScanned: number; quantityAfter: number }> = [];
  const savedItems = session?.items || [];
  const savedProductIds = new Set(savedItems.map((i: StockTakeItem) => i.product));
  for (const [, ps] of pendingScans) {
    if (savedProductIds.has(ps.product_id)) continue;
    displayItems.push({
      key: `pending-${ps.product_id}`,
      type: 'pending',
      item: ps,
      id: ps.product_id,
      productId: ps.product_id,
      productName: ps.product.prod_name,
      productCode: ps.product.prod_code,
      sku: ps.product.sku || '',
      quantityBefore: ps.product.quantity,
      quantityScanned: ps.quantity,
      quantityAfter: ps.product.quantity + ps.quantity,
    });
  }
  for (const item of savedItems) {
    displayItems.push({
      key: `saved-${item.id}`,
      type: 'saved',
      item,
      id: item.id,
      productId: item.product,
      productName: item.product_name,
      productCode: item.product_code,
      sku: item.sku,
      quantityBefore: item.quantity_before,
      quantityScanned: item.quantity_scanned + (pendingScans.get(item.product)?.quantity || 0),
      quantityAfter: item.quantity_after + (pendingScans.get(item.product)?.quantity || 0),
    });
  }

  const totalQtyAdded = displayItems.reduce((s, d) => s + d.quantityScanned, 0);

  return (
    <div className="space-y-4 pb-4 animate-fade-in">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/')}
          className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-border))] hover:bg-[rgb(var(--color-muted))] transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-xl font-bold">Stock Taking</h1>
          <p className="text-xs text-[rgb(var(--color-muted-foreground))]">Scan products to count inventory</p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-2">
        <button onClick={() => setActiveTab('current')}
          className={cn('flex-1 h-11 rounded-xl text-sm font-semibold transition-all',
            activeTab === 'current' ? 'bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))]' : 'border border-[rgb(var(--color-border))] text-[rgb(var(--color-muted-foreground))] bg-[rgb(var(--color-card))]/85')}>
          Current Session
        </button>
        <button onClick={() => setActiveTab('manage')}
          className={cn('flex-1 h-11 rounded-xl text-sm font-semibold transition-all flex items-center justify-center gap-2',
            activeTab === 'manage' ? 'bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))]' : 'border border-[rgb(var(--color-border))] text-[rgb(var(--color-muted-foreground))] bg-[rgb(var(--color-card))]/85')}>
          <GearSix className="h-4 w-4" />
          Manage
          {activeSessions.length > 0 && <Badge variant="destructive" className="ml-1">{activeSessions.length}</Badge>}
        </button>
      </div>

      {activeTab === 'current' ? (
        !session ? (
          <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 p-12 text-center">
            <Package className="h-12 w-12 text-[rgb(var(--color-muted-foreground))] opacity-40 mx-auto mb-3" />
            <p className="text-[rgb(var(--color-muted-foreground))] mb-4">No active stock take session</p>
            <button onClick={handleStartSession} disabled={loading}
              className="h-12 px-6 rounded-xl bg-[rgb(var(--color-secondary))] text-[rgb(var(--color-secondary-foreground))] font-bold text-sm active:scale-[0.98] transition-all flex items-center gap-2 mx-auto">
              {loading ? <><span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" /> Starting...</>
                : <><Plus className="h-5 w-5" /> Start New Session</>}
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Session header */}
            <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 p-4">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="font-bold">{session.session_id}</p>
                  <p className="text-xs text-[rgb(var(--color-muted-foreground))]">by {session.created_by} · {new Date(session.created_at).toLocaleString()}</p>
                </div>
                <Badge variant={isCompleted ? 'default' : isDraft ? 'secondary' : 'destructive'}>{session.status}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="stat-card"><p className="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">Items Scanned</p><p className="text-2xl font-bold">{displayItems.length || 0}</p></div>
                <div className="stat-card"><p className="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">Total Qty Added</p><p className="text-2xl font-bold text-green-600">+{totalQtyAdded || 0}</p></div>
              </div>
            </div>

            {/* Input Selection */}
            {isDraft && (
              <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-bold text-sm flex items-center gap-2">
                    {inputMode === 'scanner' ? <Scan className="h-4 w-4" /> : <MagnifyingGlass className="h-4 w-4" />}
                    {inputMode === 'scanner' ? 'Scan Products' : 'Manual Entry'}
                  </h3>
                  <div className="flex bg-[rgb(var(--color-muted))]/50 p-1 rounded-xl">
                    <button
                      onClick={() => setInputMode('scanner')}
                      className={cn(
                        "px-3 py-1 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5",
                        inputMode === 'scanner' ? "bg-[rgb(var(--color-card))] text-[rgb(var(--color-primary))] shadow-sm" : "text-[rgb(var(--color-muted-foreground))]"
                      )}
                    >
                      <Scan className="h-3.5 w-3.5" />
                      Scanner
                    </button>
                    <button
                      onClick={() => setInputMode('manual')}
                      className={cn(
                        "px-3 py-1 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5",
                        inputMode === 'manual' ? "bg-[rgb(var(--color-card))] text-[rgb(var(--color-primary))] shadow-sm" : "text-[rgb(var(--color-muted-foreground))]"
                      )}
                    >
                      <MagnifyingGlass className="h-3.5 w-3.5" />
                      Manual
                    </button>
                  </div>
                </div>

                {inputMode === 'scanner' ? (
                  <BarcodeScanner onScan={handleScan} disabled={processing} placeholder="Scan or enter barcode..." autoFocus />
                ) : (
                  <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-300">
                    <Input
                      type="text"
                      placeholder="Search products..."
                      value={productSearch}
                      onChange={e => setProductSearch(e.target.value)}
                      className="h-11 rounded-xl"
                    />
                    <div className="max-h-48 overflow-y-auto rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/50 divide-y divide-[rgb(var(--color-border))]/50">
                      {filteredProducts.length === 0 ? (
                        <div className="text-center py-6 text-[rgb(var(--color-muted-foreground))]">
                          <MagnifyingGlass className="h-6 w-6 mx-auto mb-1.5 opacity-40" />
                          <p className="text-xs">No products found</p>
                        </div>
                      ) : (
                        filteredProducts.slice(0, 10).map(product => (
                          <div
                            key={product.id}
                            onClick={() => setSelectedProduct(product)}
                            className={cn(
                              'p-3 cursor-pointer transition-colors active:bg-[rgb(var(--color-muted))]',
                              selectedProduct?.id === product.id ? 'bg-[rgb(var(--color-primary))]/10 border-l-4 border-[rgb(var(--color-primary))]' : 'hover:bg-[rgb(var(--color-muted))]/30'
                            )}
                          >
                            <div className="flex justify-between items-center">
                              <div>
                                <p className="font-bold text-sm">{product.prod_name}</p>
                                <p className="text-[10px] text-[rgb(var(--color-muted-foreground))] uppercase tracking-wider">{product.prod_code} · {product.sku}</p>
                              </div>
                              <p className="text-xs font-semibold text-[rgb(var(--color-muted-foreground))]">Stock: {product.quantity}</p>
                            </div>
                          </div>
                        ))
                      )}
                    </div>

                    {selectedProduct && (
                      <div className="rounded-xl border border-[rgb(var(--color-primary))]/20 p-3 bg-[rgb(var(--color-primary))]/5 space-y-3 animate-in zoom-in-95 duration-200">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-bold text-[rgb(var(--color-primary))] truncate mr-2">
                            {selectedProduct.prod_name}
                          </p>
                          <button onClick={() => setSelectedProduct(null)} className="text-[rgb(var(--color-muted-foreground))] hover:text-red-500">
                            <XCircle className="h-4 w-4" />
                          </button>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="flex items-center gap-1.5 bg-[rgb(var(--color-card))] p-1 rounded-xl border border-[rgb(var(--color-border))]">
                            <button
                              onClick={() => setManualQuantity(Math.max(1, manualQuantity - 1))}
                              className="h-8 w-8 flex items-center justify-center rounded-lg hover:bg-[rgb(var(--color-muted))] transition-colors"
                            >
                              <Minus className="h-4 w-4" />
                            </button>
                            <span className="w-8 text-center font-bold text-sm">{manualQuantity}</span>
                            <button
                              onClick={() => setManualQuantity(manualQuantity + 1)}
                              className="h-8 w-8 flex items-center justify-center rounded-lg hover:bg-[rgb(var(--color-muted))] transition-colors"
                            >
                              <Plus className="h-4 w-4" />
                            </button>
                          </div>
                          <button
                            onClick={handleManualAdd}
                            className="flex-1 h-10 rounded-xl bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] font-bold text-sm active:scale-[0.98] transition-all flex items-center justify-center gap-2"
                          >
                            <Plus className="h-4 w-4" />
                            Add to Session
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Registration Kits */}
            <div className={cn('rounded-2xl border p-4', isDraft ? 'border-[rgb(var(--color-primary))]/[0.3]' : 'border-[rgb(var(--color-border))]', 'bg-[rgb(var(--color-card))]/85')}>
              <h3 className="font-bold text-sm mb-3 flex items-center gap-2"><Gift className="h-4 w-4 text-[rgb(var(--color-primary))]" /> Registration Kits</h3>
              <div className="flex items-center gap-4">
                {isDraft ? (
                  <input type="number" min="0" value={session.kit_quantity ?? 0}
                    onChange={e => handleKitQuantityChange(parseInt(e.target.value) || 0)} disabled={processing}
                    className="w-24 h-11 text-right rounded-xl border border-[rgb(var(--color-input))] px-3 font-bold text-lg text-[rgb(var(--color-primary))] focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]" />
                ) : <p className="text-2xl font-bold text-[rgb(var(--color-primary))]">{session.kit_quantity ?? 0}</p>}
                {isDraft && <p className="text-xs text-[rgb(var(--color-muted-foreground))]">Updates REG_KIT_001 on completion</p>}
              </div>
            </div>

            {/* Scanned items + Pending scans */}
            {displayItems.length > 0 && (
              <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 overflow-hidden">
                <div className="px-4 py-3 border-b border-[rgb(var(--color-border))]/50 flex items-center justify-between">
                  <h3 className="font-bold text-sm">Items {isDraft && <Badge variant="outline" className="ml-2">DRAFT</Badge>}</h3>
                  {isDraft && pendingCount > 0 && (
                    <Badge className="bg-amber-500/15 text-amber-600 border-amber-300/30 text-[10px]">
                      {pendingCount} unsaved
                    </Badge>
                  )}
                </div>
                <div className="divide-y divide-[rgb(var(--color-border))]/50">
                  {displayItems.map((d) => (
                    <div key={d.key} className={cn('flex items-center gap-3 p-4 text-sm', d.type === 'pending' && 'bg-amber-500/[0.03]')}>
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold truncate flex items-center gap-2">
                          {d.productName}
                          {d.type === 'pending' && <Badge className="bg-amber-500/15 text-amber-600 border-amber-300/30 text-[9px] px-1.5 py-0">NEW</Badge>}
                        </p>
                        <p className="text-xs text-[rgb(var(--color-muted-foreground))]">{d.productCode} · {d.sku}</p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-xs text-[rgb(var(--color-muted-foreground))]">Before: {d.quantityBefore}</p>
                        <div className="flex items-center gap-2 justify-end mt-0.5">
                          {isDraft && d.type === 'saved' ? (
                            <div className="flex items-center gap-1">
                              <button onClick={() => handleQuantityChange(d.id, Math.max(0, d.quantityScanned - 1))}
                                className="touch-target-sm flex items-center justify-center rounded-lg border border-[rgb(var(--color-border))] h-8 w-8">
                                −
                              </button>
                              <span className="w-10 text-center font-bold text-green-600">{d.quantityScanned}</span>
                              <button onClick={() => handleQuantityChange(d.id, d.quantityScanned + 1)}
                                className="touch-target-sm flex items-center justify-center rounded-lg border border-[rgb(var(--color-border))] h-8 w-8">
                                +
                              </button>
                            </div>
                          ) : (
                            <span className="font-bold text-green-600">+{d.quantityScanned}</span>
                          )}
                        </div>
                        <p className="text-xs text-[rgb(var(--color-muted-foreground))]">After: {d.quantityAfter}</p>
                      </div>
                      {isDraft && (
                        d.type === 'pending' ? (
                          <button onClick={() => removePendingScan(d.productId)}
                            className="touch-target-sm flex items-center justify-center rounded-xl text-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/10 transition-colors">
                            <Trash className="h-4 w-4" />
                          </button>
                        ) : (
                          <button onClick={() => handleRemoveItem(d.id)} disabled={processing}
                            className="touch-target-sm flex items-center justify-center rounded-xl text-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/10 transition-colors">
                            <Trash className="h-4 w-4" />
                          </button>
                        )
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            {isDraft && (
              <div className="flex gap-2">
                <button onClick={() => setShowCurrentSessionCancelDialog(true)} disabled={processing}
                  className="flex-1 h-12 rounded-xl border border-[rgb(var(--color-border))] font-semibold text-sm transition-all active:scale-[0.98]">
                  Cancel
                </button>
                {pendingCount > 0 && (
                  <button onClick={flushPendingScans} disabled={processing}
                    className="h-12 px-4 rounded-xl border border-amber-300/30 text-amber-700 bg-amber-50 font-bold text-sm active:scale-[0.98] disabled:opacity-50 transition-all flex items-center justify-center gap-2">
                    {processing ? <span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
                      : <><FloppyDisk className="h-4 w-4" /> Save {pendingCount}</>}
                  </button>
                )}
                <button onClick={handleComplete} disabled={processing || (!displayItems.length && !session.kit_quantity)}
                  className="flex-[2] h-12 rounded-xl bg-[rgb(var(--color-secondary))] text-[rgb(var(--color-secondary-foreground))] font-bold text-sm active:scale-[0.98] disabled:opacity-50 transition-all flex items-center justify-center gap-2">
                  {processing ? <><span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" /> Completing...</>
                    : <><CheckCircle className="h-5 w-5" /> Complete Session</>}
                </button>
              </div>
            )}
          </div>
        )
      ) : (
        /* Manage Sessions Tab */
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-[rgb(var(--color-muted-foreground))]">{activeSessions.length} active session(s)</p>
            <div className="flex gap-2">
              {activeSessions.length > 0 && (
                <button onClick={() => setShowCancelAllDialog(true)} disabled={processing}
                  className="h-9 px-4 rounded-xl border border-[rgb(var(--color-destructive))]/30 text-[rgb(var(--color-destructive))] font-semibold text-xs active:scale-[0.98] transition-all flex items-center gap-1.5">
                  <Trash className="h-3.5 w-3.5" /> Cancel All
                </button>
              )}
            </div>
          </div>

          {activeSessions.length === 0 ? (
            <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 p-12 text-center">
              <ClipboardText className="h-12 w-12 text-[rgb(var(--color-muted-foreground))] opacity-40 mx-auto mb-3" />
              <p className="font-medium">No active sessions</p>
              <p className="text-xs text-[rgb(var(--color-muted-foreground))] mt-1">All sessions completed or cancelled</p>
            </div>
          ) : (
            <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 overflow-hidden">
              <div className="divide-y divide-[rgb(var(--color-border))]/50">
                {activeSessions.map((sess) => (
                  <div key={sess.session_id} className="flex items-center gap-3 p-4">
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-sm">{sess.session_id}</p>
                      <p className="text-xs text-[rgb(var(--color-muted-foreground))]">{sess.created_by} · {new Date(sess.created_at).toLocaleString()}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <Badge variant="secondary">{sess.status}</Badge>
                      <p className="text-xs text-[rgb(var(--color-muted-foreground))] mt-0.5">{sess.items_count || 0} items · +{sess.total_quantity_added || 0}</p>
                    </div>
                    <button onClick={() => setSessionToCancel(sess.session_id)} disabled={processing}
                      className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-destructive))]/30 text-[rgb(var(--color-destructive))] active:scale-[0.95] transition-all">
                      <XCircle className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
              <div className="p-4 bg-[rgb(var(--color-accent))]/50 text-xs text-[rgb(var(--color-accent-foreground))] flex items-start gap-2 border-t border-[rgb(var(--color-border))]/50">
                <WarningCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>Active sessions block combined order creation. Cancel to restore full functionality.</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Dialogs */}
      <AlertDialog open={!!sessionToCancel} onOpenChange={(open) => !open && setSessionToCancel(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel Session?</AlertDialogTitle>
            <AlertDialogDescription>Cancel session <strong>{sessionToCancel}</strong>? All scanned data will be lost.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={processing}>Keep</AlertDialogCancel>
            <AlertDialogAction onClick={() => sessionToCancel && handleCancelSession(sessionToCancel)} disabled={processing}
              className="bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/[0.85]">
              {processing ? 'Cancelling...' : 'Confirm Cancel'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showCancelAllDialog} onOpenChange={setShowCancelAllDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel All Sessions?</AlertDialogTitle>
            <AlertDialogDescription>Cancel all {activeSessions.length} active session(s)? This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={processing}>Keep All</AlertDialogCancel>
            <AlertDialogAction onClick={handleCancelAllSessions} disabled={processing}
              className="bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/[0.85]">
              {processing ? 'Cancelling...' : 'Confirm Cancel All'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showCurrentSessionCancelDialog} onOpenChange={setShowCurrentSessionCancelDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel Current Session?</AlertDialogTitle>
            <AlertDialogDescription>All scanned data will be lost. This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={processing}>Keep Session</AlertDialogCancel>
            <AlertDialogAction onClick={() => session && handleCancelSession(session.session_id)} disabled={processing}
              className="bg-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/[0.85]">
              {processing ? 'Cancelling...' : <><XCircle className="h-4 w-4" /> Cancel Session</>}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
