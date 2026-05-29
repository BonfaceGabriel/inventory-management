import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, useBeforeUnload } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Html5Qrcode } from 'html5-qrcode';
import {
  Camera, Keyboard, CheckCircle, XCircle,
  ArrowLeft, WarningCircle, Plus, MagnifyingGlass,
  Minus, Trash, Barcode
} from '@phosphor-icons/react';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import {
  formatCurrency, activateIssuance as activateIssuanceAPI,
  getTransactionById, scanBarcode as scanBarcodeAPI,
  completeIssuance as completeIssuanceAPI,
  cancelIssuance as cancelIssuanceAPI,
  removeLineItem as removeLineItemAPI,
  getProducts, getCombinedOrderDetails,
  activateCombinedOrder, scanProductToCombinedOrder,
  completeCombinedOrder, searchProductBySku,
  removeCombinedOrderLineItem, cancelCombinedOrderIssuance
} from '@/services/api';
import type { Transaction } from '@/types/transaction.types';
import { extractApiError } from '@/lib/error-utils';
import { cn } from '@/lib/utils';

interface Product { id: number; prod_code: string; prod_name: string; sku: string; sku_name: string; current_price: string; current_pv: string; quantity: number; is_active: boolean; }
interface LineItem { id: number; product_code: string; product_name: string; quantity: number; unit_price: string; line_total: string; }

export default function ScanningPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const isCombined = id?.startsWith('CMB-');
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [lineItems, setLineItems] = useState<LineItem[]>([]);
  const [inputMode, setInputMode] = useState<'scanner' | 'camera' | 'manual'>('scanner');
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [manualInput, setManualInput] = useState('');
  const [isScanning, setIsScanning] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [manualQuantity, setManualQuantity] = useState(1);

  const html5QrCodeRef = useRef<Html5Qrcode | null>(null);
  const manualInputRef = useRef<HTMLInputElement>(null);
  const scanSoundRef = useRef<HTMLAudioElement | null>(null);
  const activationAttemptedRef = useRef(false);

  useEffect(() => { if (inputMode === 'scanner') manualInputRef.current?.focus(); }, [inputMode]);
  useEffect(() => { fetchTransactionDetails(); }, [id]);
  useEffect(() => { if (inputMode === 'manual' && products.length === 0) loadProducts(); }, [inputMode]);

  useEffect(() => {
    if (transaction && !isActive && !isLoading && !transaction.is_in_issuance && !activationAttemptedRef.current) {
      activationAttemptedRef.current = true;
      activateIssuance();
    }
  }, [transaction, isActive, isLoading]);

  useEffect(() => {
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    const createBeep = () => {
      const oscillator = audioContext.createOscillator();
      const gainNode = audioContext.createGain();
      oscillator.connect(gainNode);
      gainNode.connect(audioContext.destination);
      oscillator.frequency.value = 800;
      oscillator.type = 'sine';
      gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.1);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.1);
    };
    scanSoundRef.current = { play: createBeep } as any;
  }, []);

  useEffect(() => () => { stopCamera(); }, []);

  useBeforeUnload((event) => {
    if (isActive && lineItems.length > 0) {
      event.preventDefault();
      return (event.returnValue = 'You have unsaved scanned items. Are you sure you want to leave?');
    }
  }, { capture: true });

  const fetchTransactionDetails = async () => {
    if (!id) return;
    try {
      setIsLoading(true);
      if (isCombined) {
        const data = await getCombinedOrderDetails(id);
        const mapped: any = {
          id: data.combined_order_id, tx_id: data.combined_order_id,
          amount: data.total_amount, amount_fulfilled: data.amount_fulfilled,
          remaining_amount: data.remaining_amount, status: data.status,
          is_in_issuance: data.status === 'IN_PROGRESS' || data.status === 'PARTIALLY_FULFILLED',
          line_items: data.line_items || []
        };
        setTransaction(mapped);
        setIsActive(mapped.is_in_issuance);
        if (data.line_items?.length > 0) setLineItems(data.line_items.map((item: any) => ({ id: item.id, product_code: item.product_code, product_name: item.product_name, quantity: item.quantity, unit_price: item.unit_price, line_total: item.line_total })));
      } else {
        const data = await getTransactionById(Number(id));
        setTransaction(data);
        setIsActive(data.is_in_issuance || false);
        if (data.is_in_issuance && data.line_items) {
          const items = data.line_items;
          if (items.length > 0) setLineItems(items.map((item: any) => ({ id: item.id, product_code: item.product_code, product_name: item.product_name, quantity: item.quantity, unit_price: item.unit_price, line_total: item.line_total })));
        }
      }
    } catch { toast.error('Failed to load transaction'); } finally { setIsLoading(false); }
  };

  const loadProducts = async () => {
    try {
      const data: any = await getProducts({ is_active: true });
      setProducts(Array.isArray(data) ? data : (data.results || []));
    } catch { toast.error('Failed to load products'); }
  };

  const activateIssuance = async () => {
    if (!id) return;
    try {
      if (isCombined) await activateCombinedOrder(id, 'Scanner');
      else await activateIssuanceAPI(Number(id));
      setIsActive(true);
      toast.success('Issuance activated! Start scanning.');
      if (inputMode === 'scanner') setTimeout(() => manualInputRef.current?.focus(), 100);
    } catch (error: any) {
      if (error.response?.data?.detail?.includes('throttled')) toast.error('Too many requests. Please wait.');
      else toast.error(extractApiError(error, 'Failed to activate issuance'));
      setTimeout(() => navigate('/transactions'), 2000);
    }
  };

  const scanProduct = async (sku: string, quantity: number = 1) => {
    if (!sku.trim()) { toast.error('Please enter a barcode'); return; }
    setIsScanning(true);
    try {
      const trimmed = sku.trim();
      const isNumeric = /^\d+$/.test(trimmed);
      let result: any;

      if (isCombined) {
        const product = await searchProductBySku(!isNumeric ? trimmed : undefined, undefined, isNumeric ? trimmed : undefined);
        if (!product) { toast.error('Product not found'); return; }
        const scanResponse = await scanProductToCombinedOrder(id!, product.id, quantity, 'Scanner');
        result = {
          line_item_id: scanResponse.line_item.id, product_code: scanResponse.line_item.product_code,
          product_name: scanResponse.line_item.product_name, quantity: scanResponse.line_item.quantity,
          unit_price: scanResponse.line_item.unit_price, line_total: scanResponse.line_item.line_total,
          transaction_totals: {
            amount_fulfilled: scanResponse.order_totals?.amount_fulfilled || scanResponse.amount_fulfilled,
            remaining_amount: scanResponse.order_totals?.remaining_amount || scanResponse.remaining_amount,
            status: scanResponse.order_totals?.status || scanResponse.status
          }
        };
      } else {
        result = await scanBarcodeAPI(Number(id), {
          ...(isNumeric ? { barcode: trimmed } : { sku: trimmed }), quantity, scanned_by: 'Scanner'
        });
      }

      scanSoundRef.current?.play();

      if (result.all_line_items?.length > 0) {
        setLineItems(result.all_line_items);
      } else {
        setLineItems(prev => {
          const idx = prev.findIndex(item => item.id === result.line_item_id);
          if (idx >= 0) return prev.map((item, i) => i === idx ? { ...item, quantity: result.quantity, line_total: result.line_total } : item);
          return [...prev, { id: result.line_item_id, product_code: result.product_code, product_name: result.product_name, quantity: result.quantity, unit_price: result.unit_price, line_total: result.line_total }];
        });
      }

      if (transaction) setTransaction({ ...transaction, amount_fulfilled: result.transaction_totals.amount_fulfilled, remaining_amount: result.transaction_totals.remaining_amount, status: result.transaction_totals.status as Transaction['status'] });

      toast.success(`✓ ${result.product_name} added`);
      if (!isCombined && result.applied_promotions?.length > 0) {
        result.applied_promotions.forEach((promo: any) => toast.success(`🏷️ ${promo.promotion_name}: -KES ${parseFloat(promo.discount_applied).toFixed(2)}`, { duration: 4000 }));
      }
      setManualInput('');
      setSelectedProduct(null);
      setManualQuantity(1);
      if (inputMode === 'scanner') setTimeout(() => manualInputRef.current?.focus(), 100);
    } catch (error: any) { toast.error(extractApiError(error, 'Failed to scan product')); } finally { setIsScanning(false); }
  };

  const addManualProduct = () => {
    if (!selectedProduct) { toast.error('Please select a product'); return; }
    if (manualQuantity < 1) { toast.error('Quantity must be at least 1'); return; }
    scanProduct(selectedProduct.sku, manualQuantity);
  };

  const completeIssuance = async () => {
    if (lineItems.length === 0) { toast.error('Please scan at least one product'); return; }
    try {
      if (isCombined) await completeCombinedOrder(id!, 'Scanner');
      else await completeIssuanceAPI(Number(id), 'Scanner');
      toast.success('Issuance completed!');
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      if (!isCombined) queryClient.invalidateQueries({ queryKey: ['transaction', Number(id)] });
      setTimeout(() => navigate('/transactions'), 1500);
    } catch (error: any) { toast.error(extractApiError(error, 'Failed to complete issuance')); }
  };

  const cancelIssuance = async () => {
    try {
      if (isCombined) await cancelCombinedOrderIssuance(id!);
      else await cancelIssuanceAPI(Number(id));
      toast.success('Issuance cancelled');
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      if (!isCombined) queryClient.invalidateQueries({ queryKey: ['transaction', Number(id)] });
      navigate('/transactions');
    } catch (error: any) { toast.error(extractApiError(error, 'Failed to cancel issuance')); }
  };

  const removeLineItem = async (lineItemId: number, productName: string) => {
    try {
      let result: any;
      if (isCombined) result = await removeCombinedOrderLineItem(id!, lineItemId);
      else result = await removeLineItemAPI(Number(id), lineItemId);
      if (!isCombined && result.all_line_items !== undefined) setLineItems(result.all_line_items);
      else setLineItems(prev => prev.filter(item => item.id !== lineItemId));
      if (transaction) setTransaction({ ...transaction, amount_fulfilled: isCombined ? result.amount_fulfilled : result.transaction_totals.amount_fulfilled, remaining_amount: isCombined ? result.remaining_amount : result.transaction_totals.remaining_amount, status: (isCombined ? result.status : result.transaction_totals.status) as Transaction['status'] });
      toast.success(`✓ Removed ${productName}`);
    } catch (error: any) { toast.error(extractApiError(error, 'Failed to remove item')); }
  };

  const startCamera = async () => {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        toast.error('Camera requires HTTPS or localhost. Try Scanner input instead.', { duration: 5000 }); return;
      }
      const html5QrCode = new Html5Qrcode('qr-reader');
      html5QrCodeRef.current = html5QrCode;
      await html5QrCode.start({ facingMode: 'environment' }, { fps: 10, qrbox: { width: 250, height: 250 } }, (decodedText) => scanProduct(decodedText), () => {});
      setIsCameraActive(true);
      toast.success('Camera started — point at barcode');
    } catch (error: any) { toast.error(`Failed to start camera: ${error.message || ''}`); }
  };

  const stopCamera = async () => {
    try { if (html5QrCodeRef.current) { await html5QrCodeRef.current.stop(); html5QrCodeRef.current = null; } setIsCameraActive(false); } catch {}
  };

  const filteredProducts = products.filter(p => { const s = productSearch.toLowerCase(); return p.prod_name.toLowerCase().includes(s) || p.sku?.toLowerCase().includes(s) || p.prod_code?.toLowerCase().includes(s); });

  if (isLoading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center animate-fade-in">
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-[rgb(var(--color-primary))] border-t-transparent mx-auto" />
        <p className="mt-4 text-sm text-[rgb(var(--color-muted-foreground))]">Loading transaction...</p>
      </div>
    </div>
  );

  if (!transaction) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center"><WarningCircle className="h-12 w-12 text-[rgb(var(--color-destructive))] mx-auto mb-3" /><p className="text-[rgb(var(--color-muted-foreground))]">Transaction not found</p></div>
    </div>
  );

  return (
    <div className="space-y-4 pb-4 animate-fade-in">
      {/* Header bar */}
      <div className="flex items-center gap-3">
        <button onClick={() => { if (isActive && lineItems.length > 0) { if (window.confirm('Leave? Scanned items will be lost.')) cancelIssuance().then(() => navigate('/transactions')); } else navigate('/transactions'); }}
          className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-border))] hover:bg-[rgb(var(--color-muted))] transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="min-w-0">
          <h1 className="text-xl font-bold truncate">Fulfill Order</h1>
          <p className="text-xs text-[rgb(var(--color-muted-foreground))] truncate">{transaction.tx_id}</p>
        </div>
      </div>

      {/* Transaction snapshot */}
      <div className="grid grid-cols-4 gap-2">
        {[
          { label: 'Total', value: formatCurrency(transaction.amount), color: '' },
          { label: 'Fulfilled', value: formatCurrency(transaction.amount_fulfilled || '0'), color: 'text-green-600 dark:text-green-400' },
          { label: 'Remaining', value: formatCurrency(transaction.remaining_amount || transaction.amount), color: 'text-[rgb(var(--color-primary))]' },
          { label: 'Status', value: isActive ? 'Active' : 'Inactive', color: isActive ? 'text-[rgb(var(--color-primary))]' : 'text-[rgb(var(--color-muted-foreground))]' },
        ].map((item, i) => (
          <div key={i} className="stat-card">
            <p className="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--color-muted-foreground))]">{item.label}</p>
            <p className={`text-lg font-bold mt-0.5 ${item.color}`}>{item.value}</p>
          </div>
        ))}
      </div>

      {!isActive ? (
        /* Activating state */
        <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 p-12 text-center animate-fade-in">
          <div className="animate-spin rounded-full h-10 w-10 border-2 border-[rgb(var(--color-primary))] border-t-transparent mx-auto mb-4" />
          <h2 className="text-lg font-bold mb-1">Activating Fulfillment</h2>
          <p className="text-sm text-[rgb(var(--color-muted-foreground))]">Preparing scanner and securing transaction lock...</p>
        </div>
      ) : (
        /* Fulfillment interface */
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Left: Input methods */}
          <div className="space-y-4">
            {/* Mode selector */}
            <div className="flex gap-2">
              {(['scanner', 'camera', 'manual'] as const).map(mode => (
                <button key={mode} onClick={() => { setInputMode(mode); if (mode !== 'camera') stopCamera(); }}
                  className={cn('flex-1 h-11 rounded-xl text-sm font-semibold transition-all active:scale-[0.98] gap-1.5 flex items-center justify-center',
                    inputMode === mode
                      ? 'bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))]'
                      : 'border border-[rgb(var(--color-border))] text-[rgb(var(--color-muted-foreground))] bg-[rgb(var(--color-card))]/85'
                  )}>
                  {mode === 'scanner' && <Keyboard className="h-4 w-4" />}
                  {mode === 'camera' && <Camera className="h-4 w-4" />}
                  {mode === 'manual' && <MagnifyingGlass className="h-4 w-4" />}
                  {mode === 'scanner' ? 'Scanner' : mode === 'camera' ? 'Camera' : 'Browse'}
                </button>
              ))}
            </div>

            {/* Scanner Input */}
            {inputMode === 'scanner' && (
              <div className="rounded-2xl border-2 border-dashed border-[rgb(var(--color-border))] p-6 text-center bg-[rgb(var(--color-card))]/60 space-y-4">
                <Keyboard className="h-10 w-10 text-[rgb(var(--color-muted-foreground))] mx-auto" />
                <p className="text-sm text-[rgb(var(--color-muted-foreground))]">Scan with USB or Bluetooth scanner</p>
                <div className="max-w-sm mx-auto space-y-3">
                  <Input ref={manualInputRef} type="text" placeholder="Barcode or SKU..." value={manualInput}
                    onChange={e => setManualInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && scanProduct(manualInput)}
                    disabled={isScanning} className="text-center text-lg font-mono h-12" autoFocus />
                  <button onClick={() => scanProduct(manualInput)} disabled={isScanning || !manualInput.trim()}
                    className="w-full h-12 rounded-xl bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] font-bold text-sm active:scale-[0.98] disabled:opacity-50 transition-all flex items-center justify-center gap-2">
                    {isScanning ? <><span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" /> Adding...</> : <><Barcode className="h-4 w-4" /> Add Product</>}
                  </button>
                </div>
              </div>
            )}

            {/* Camera */}
            {inputMode === 'camera' && (
              <div className="rounded-2xl border-2 border-dashed border-[rgb(var(--color-border))] p-6 text-center bg-[rgb(var(--color-card))]/60 space-y-4">
                {!isCameraActive ? (
                  <>
                    <Camera className="h-10 w-10 text-[rgb(var(--color-muted-foreground))] mx-auto" />
                    <p className="text-sm text-[rgb(var(--color-muted-foreground))]">Use device camera to scan barcodes</p>
                    <button onClick={startCamera} className="h-11 px-6 rounded-xl bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] font-bold text-sm active:scale-[0.98] transition-all flex items-center gap-2 mx-auto">
                      <Camera className="h-4 w-4" /> Start Camera
                    </button>
                  </>
                ) : (
                  <div className="space-y-3">
                    <div id="qr-reader" className="rounded-xl overflow-hidden" />
                    <button onClick={stopCamera} className="h-11 px-6 rounded-xl border border-[rgb(var(--color-border))] font-semibold text-sm active:scale-[0.98] transition-all flex items-center gap-2 mx-auto">
                      <XCircle className="h-4 w-4" /> Stop Camera
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Manual Selection */}
            {inputMode === 'manual' && (
              <div className="space-y-3">
                <Input type="text" placeholder="Search products..." value={productSearch} onChange={e => setProductSearch(e.target.value)} className="h-12" />
                <div className="max-h-64 overflow-y-auto rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/70 divide-y divide-[rgb(var(--color-border))]/50">
                  {filteredProducts.length === 0 ? (
                    <div className="text-center py-8 text-[rgb(var(--color-muted-foreground))]"><MagnifyingGlass className="h-8 w-8 mx-auto mb-2 opacity-50" /><p className="text-sm">No products found</p></div>
                  ) : filteredProducts.slice(0, 10).map(product => (
                    <div key={product.id} onClick={() => setSelectedProduct(product)}
                      className={cn('p-3.5 cursor-pointer transition-colors active:bg-[rgb(var(--color-muted))]',
                        selectedProduct?.id === product.id ? 'bg-[rgb(var(--color-accent))]/60' : '')}>
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="font-semibold text-sm">{product.prod_name}</p>
                          <p className="text-xs text-[rgb(var(--color-muted-foreground))]">{product.prod_code} • Stock: {product.quantity}</p>
                        </div>
                        <p className="font-bold text-sm">{formatCurrency(product.current_price)}</p>
                      </div>
                    </div>
                  ))}
                </div>
                {selectedProduct && (
                  <div className="rounded-2xl border border-[rgb(var(--color-border))] p-4 bg-[rgb(var(--color-accent))]/35 space-y-3">
                    <p className="text-sm font-semibold">Selected: {selectedProduct.prod_name}</p>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        <button onClick={() => setManualQuantity(Math.max(1, manualQuantity - 1))}
                          className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]">
                          <Minus className="h-4 w-4" />
                        </button>
                        <span className="w-12 text-center font-bold text-lg">{manualQuantity}</span>
                        <button onClick={() => setManualQuantity(manualQuantity + 1)}
                          className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]">
                          <Plus className="h-4 w-4" />
                        </button>
                      </div>
                      <button onClick={addManualProduct} disabled={isScanning}
                        className="flex-1 h-11 rounded-xl bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] font-bold text-sm active:scale-[0.98] disabled:opacity-50 transition-all">
                        {isScanning ? 'Adding...' : 'Add to Order'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right: Scanned Items */}
          <div className="rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/85 flex flex-col">
            <div className="p-4 border-b border-[rgb(var(--color-border))]/50">
              <h2 className="font-bold flex items-center gap-2">
                Items <span className="text-[rgb(var(--color-muted-foreground))]">({lineItems.length})</span>
              </h2>
            </div>

            <div className="flex-1 overflow-y-auto max-h-[400px]">
              {lineItems.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-[rgb(var(--color-muted-foreground))]">
                  <WarningCircle className="h-10 w-10 mb-2 opacity-40" />
                  <p className="text-sm font-medium">No items added yet</p>
                  <p className="text-xs mt-1">Use scanner, camera, or browse to add products</p>
                </div>
              ) : (
                <div className="divide-y divide-[rgb(var(--color-border))]/50">
                  {lineItems.map((item, index) => (
                    <div key={item.id} className="flex items-center gap-3 p-4 group active:bg-[rgb(var(--color-muted))]/50 transition-colors">
                      <div className="w-8 h-8 rounded-full bg-[rgb(var(--color-accent))] flex items-center justify-center text-[rgb(var(--color-primary))] font-bold text-sm shrink-0">
                        {index + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-sm truncate">{item.product_name}</p>
                        <p className="text-xs text-[rgb(var(--color-muted-foreground))]">{item.product_code}</p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="font-bold text-sm">{formatCurrency(item.line_total)}</p>
                        <p className="text-xs text-[rgb(var(--color-muted-foreground))]">{item.quantity} × {formatCurrency(item.unit_price)}</p>
                      </div>
                      <button onClick={() => removeLineItem(item.id, item.product_name)}
                        className="touch-target-sm flex items-center justify-center rounded-xl text-[rgb(var(--color-destructive))] opacity-0 group-hover:opacity-100 transition-all">
                        <Trash className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Totals & Actions */}
            <div className="p-4 border-t border-[rgb(var(--color-border))]/50 space-y-2">
              {lineItems.length > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-[rgb(var(--color-muted-foreground))]">Subtotal</span>
                  <span className="font-bold">{formatCurrency(lineItems.reduce((s, item) => s + parseFloat(item.line_total || '0'), 0))}</span>
                </div>
              )}
              {lineItems.length > 0 && (
                <button onClick={completeIssuance}
                  className="w-full h-12 rounded-xl bg-[rgb(var(--color-secondary))] text-[rgb(var(--color-secondary-foreground))] font-bold text-sm active:scale-[0.98] transition-all flex items-center justify-center gap-2">
                  <CheckCircle className="h-5 w-5" /> Complete ({lineItems.length} items)
                </button>
              )}
              <button onClick={cancelIssuance}
                className="w-full h-11 rounded-xl border border-[rgb(var(--color-destructive))]/30 text-[rgb(var(--color-destructive))] font-semibold text-sm active:scale-[0.98] transition-all flex items-center justify-center gap-2">
                <XCircle className="h-4 w-4" /> Cancel Issuance
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
