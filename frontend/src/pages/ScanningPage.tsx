import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, useBeforeUnload } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Html5Qrcode } from 'html5-qrcode';
import {
  Camera,
  Keyboard,
  CheckCircle2,
  XCircle,
  Scan,
  Package,
  ArrowLeft,
  AlertCircle,
  Plus,
  Search,
  Minus,
  Trash2
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import {
  formatCurrency,
  activateIssuance as activateIssuanceAPI,
  getTransactionById,
  scanBarcode as scanBarcodeAPI,
  completeIssuance as completeIssuanceAPI,
  cancelIssuance as cancelIssuanceAPI,
  removeLineItem as removeLineItemAPI,
  getProducts
} from '@/services/api';
import type { Transaction } from '@/types/transaction.types';

interface Product {
  id: number;
  prod_code: string;
  prod_name: string;
  sku: string;
  sku_name: string;
  current_price: string;
  current_pv: string;
  quantity: number;
  is_active: boolean;
}

interface LineItem {
  id: number;
  product_code: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  line_total: string;
}

interface ScanResult {
  success: boolean;
  line_item_id: number;
  product_code: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  transaction_totals: {
    amount_fulfilled: string;
    remaining_amount: string;
    status: string;
  };
}

export default function ScanningPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // State
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [lineItems, setLineItems] = useState<LineItem[]>([]);
  const [inputMode, setInputMode] = useState<'scanner' | 'camera' | 'manual'>('scanner');
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [manualInput, setManualInput] = useState('');
  const [isScanning, setIsScanning] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Manual product selection
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [manualQuantity, setManualQuantity] = useState(1);

  // Refs
  const html5QrCodeRef = useRef<Html5Qrcode | null>(null);
  const manualInputRef = useRef<HTMLInputElement>(null);
  const scanSoundRef = useRef<HTMLAudioElement | null>(null);
  const activationAttemptedRef = useRef(false);

  // Focus manual input when in scanner mode
  useEffect(() => {
    if (inputMode === 'scanner' && manualInputRef.current) {
      manualInputRef.current.focus();
    }
  }, [inputMode]);

  // Load transaction details once when component mounts
  useEffect(() => {
    fetchTransactionDetails();
  }, [id]);

  // Load products only when switching to manual mode
  useEffect(() => {
    if (inputMode === 'manual' && products.length === 0) {
      loadProducts();
    }
  }, [inputMode]);

  // Auto-activate issuance when transaction loads (if not already active)
  useEffect(() => {
    if (transaction && !isActive && !isLoading && !transaction.is_in_issuance && !activationAttemptedRef.current) {
      activationAttemptedRef.current = true;
      activateIssuance();
    }
  }, [transaction, isActive, isLoading]);

  // Create beep sound for successful scans
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

  // Cleanup camera on unmount
  useEffect(() => {
    return () => {
      stopCamera();
    };
  }, []);

  // Prevent accidental navigation/tab close during active issuance
  useBeforeUnload(
    (event) => {
      if (isActive && lineItems.length > 0) {
        event.preventDefault();
        return (event.returnValue = 'You have unsaved scanned items. Are you sure you want to leave?');
      }
    },
    { capture: true }
  );

  const fetchTransactionDetails = async () => {
    try {
      setIsLoading(true);
      const data = await getTransactionById(Number(id));
      setTransaction(data);
      setIsActive(data.is_in_issuance || false);

      // If already in issuance, load existing line items
      if (data.is_in_issuance && data.line_items && data.line_items.length > 0) {
        setLineItems(data.line_items.map((item: any) => ({
          id: item.id,
          product_code: item.scanned_prod_code,
          product_name: item.scanned_prod_name,
          quantity: item.quantity,
          unit_price: item.scanned_price,
          line_total: item.line_total
        })));
      }
    } catch (error) {
      console.error('Error fetching transaction:', error);
      toast.error('Failed to load transaction details');
    } finally {
      setIsLoading(false);
    }
  };

  const loadProducts = async () => {
    try {
      // Use the proper API function which includes JWT authentication
      const data = await getProducts({ is_active: true });
      const productsList = Array.isArray(data) ? data : (data as any).results || [];
      setProducts(productsList);
    } catch (error) {
      console.error('Error loading products:', error);
      toast.error('Failed to load products');
    }
  };

  const activateIssuance = async () => {
    try {
      // Use the proper API function which includes JWT authentication
      await activateIssuanceAPI(Number(id));

      setIsActive(true);
      toast.success('Issuance activated! Start scanning or selecting products.');

      // Auto-focus scanner input
      if (inputMode === 'scanner' && manualInputRef.current) {
        setTimeout(() => manualInputRef.current?.focus(), 100);
      }
    } catch (error: any) {
      console.error('Error activating issuance:', error);

      // Extract error message from axios error
      let errorMessage = 'Failed to activate issuance';

      if (error.response?.data) {
        const errorData = error.response.data;

        // Handle throttling error
        if (errorData.detail && errorData.detail.includes('throttled')) {
          errorMessage = 'Too many requests. Please wait a moment and try again.';
        } else if (errorData.error) {
          if (typeof errorData.error === 'string') {
            errorMessage = errorData.error;
          } else if (errorData.error.is_in_issuance) {
            errorMessage = errorData.error.is_in_issuance[0] || errorData.error.is_in_issuance;
          } else if (typeof errorData.error === 'object') {
            // Get first error from nested object
            const firstError = Object.values(errorData.error)[0];
            errorMessage = Array.isArray(firstError) ? firstError[0] : String(firstError);
          }
        } else if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      }

      toast.error(errorMessage);

      // If activation fails, navigate back
      setTimeout(() => navigate('/transactions'), 2000);
    }
  };

  const scanProduct = async (sku: string, quantity: number = 1) => {
    if (!sku.trim()) {
      toast.error('Please enter a barcode');
      return;
    }

    setIsScanning(true);

    try {
      // Use the proper API function which includes JWT authentication
      const result: ScanResult = await scanBarcodeAPI(Number(id), {
        sku: sku.trim(),
        quantity: quantity,
        scanned_by: 'Scanner'
      });

      // Play success beep
      scanSoundRef.current?.play();

      // Check if product already exists in line items (update quantity)
      const existingIndex = lineItems.findIndex(item => item.id === result.line_item_id);

      if (existingIndex >= 0) {
        // Update existing item
        setLineItems(prev => prev.map((item, index) =>
          index === existingIndex
            ? {
                ...item,
                quantity: result.quantity,
                line_total: result.line_total
              }
            : item
        ));
      } else {
        // Add new item
        setLineItems(prev => [...prev, {
          id: result.line_item_id,
          product_code: result.product_code,
          product_name: result.product_name,
          quantity: result.quantity,
          unit_price: result.unit_price,
          line_total: result.line_total
        }]);
      }

      // Update transaction totals
      if (transaction) {
        setTransaction({
          ...transaction,
          amount_fulfilled: result.transaction_totals.amount_fulfilled,
          remaining_amount: result.transaction_totals.remaining_amount,
          status: result.transaction_totals.status as Transaction['status']
        });
      }

      toast.success(`✓ ${result.product_name} added`);

      // Clear inputs
      setManualInput('');
      setSelectedProduct(null);
      setManualQuantity(1);

      // Re-focus input for next scan
      if (inputMode === 'scanner' && manualInputRef.current) {
        setTimeout(() => manualInputRef.current?.focus(), 100);
      }
    } catch (error: any) {
      console.error('Error scanning product:', error);

      // Extract error message from axios error
      let errorMessage = 'Failed to scan product';
      if (error.response?.data) {
        const errorData = error.response.data;
        if (errorData.error) {
          if (typeof errorData.error === 'string') {
            errorMessage = errorData.error;
          } else if (errorData.error.product) {
            errorMessage = Array.isArray(errorData.error.product)
              ? errorData.error.product[0]
              : errorData.error.product;
          } else if (typeof errorData.error === 'object') {
            const firstError = Object.values(errorData.error)[0];
            errorMessage = Array.isArray(firstError) ? firstError[0] : String(firstError);
          }
        } else if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      }

      toast.error(errorMessage);
    } finally {
      setIsScanning(false);
    }
  };

  const addManualProduct = () => {
    if (!selectedProduct) {
      toast.error('Please select a product');
      return;
    }
    if (manualQuantity < 1) {
      toast.error('Quantity must be at least 1');
      return;
    }

    scanProduct(selectedProduct.sku, manualQuantity);
  };

  const completeIssuance = async () => {
    if (lineItems.length === 0) {
      toast.error('Please scan at least one product before completing');
      return;
    }

    try {
      // Use the proper API function which includes JWT authentication
      const result = await completeIssuanceAPI(Number(id), 'Scanner');

      toast.success(`Issuance completed! ${result.line_items_count} ${result.line_items_count === 1 ? 'item' : 'items'} fulfilled.`);

      // Invalidate transactions cache to show updated data
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      queryClient.invalidateQueries({ queryKey: ['transaction', Number(id)] });

      // Navigate back to transactions
      setTimeout(() => navigate('/transactions'), 1500);
    } catch (error: any) {
      console.error('Error completing issuance:', error);

      // Extract error message from axios error
      let errorMessage = 'Failed to complete issuance';
      if (error.response?.data) {
        const errorData = error.response.data;
        if (errorData.error) {
          errorMessage = typeof errorData.error === 'string' ? errorData.error : JSON.stringify(errorData.error);
        } else if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      }

      toast.error(errorMessage);
    }
  };

  const cancelIssuance = async () => {
    try {
      // Use the proper API function which includes JWT authentication
      await cancelIssuanceAPI(Number(id));

      toast.success('Issuance cancelled');

      // Invalidate transactions cache to show updated data
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      queryClient.invalidateQueries({ queryKey: ['transaction', Number(id)] });

      // Navigate back to transactions
      navigate('/transactions');
    } catch (error: any) {
      console.error('Error cancelling issuance:', error);

      // Extract error message from axios error
      let errorMessage = 'Failed to cancel issuance';
      if (error.response?.data) {
        const errorData = error.response.data;
        if (errorData.error) {
          errorMessage = typeof errorData.error === 'string' ? errorData.error : JSON.stringify(errorData.error);
        } else if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      }

      toast.error(errorMessage);
    }
  };

  const removeLineItem = async (lineItemId: number, productName: string) => {
    try {
      // Use the proper API function which includes JWT authentication
      const result = await removeLineItemAPI(Number(id), lineItemId);

      // Remove from local state
      setLineItems(prev => prev.filter(item => item.id !== lineItemId));

      // Update transaction totals
      if (transaction) {
        setTransaction({
          ...transaction,
          amount_fulfilled: result.transaction_totals.amount_fulfilled,
          remaining_amount: result.transaction_totals.remaining_amount,
          status: result.transaction_totals.status as Transaction['status']
        });
      }

      toast.success(`✓ Removed ${productName}`);
    } catch (error: any) {
      console.error('Error removing line item:', error);

      // Extract error message from axios error
      let errorMessage = 'Failed to remove item';
      if (error.response?.data) {
        const errorData = error.response.data;
        if (typeof errorData.error === 'string') {
          errorMessage = errorData.error;
        } else if (errorData.error && typeof errorData.error === 'object') {
          const firstKey = Object.keys(errorData.error)[0];
          const firstError = errorData.error[firstKey];
          errorMessage = Array.isArray(firstError) ? firstError[0] : String(firstError);
        } else if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      }

      toast.error(errorMessage);
    }
  };

  const startCamera = async () => {
    try {
      // Check if mediaDevices is available (requires HTTPS or localhost)
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        toast.error(
          'Camera not available. This feature requires HTTPS or localhost. ' +
          'Try accessing via: http://localhost:5173 on this device, or use Manual/Scanner input instead.',
          { duration: 6000 }
        );
        return;
      }

      // Request camera permission explicitly
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
        // Stop the test stream immediately - we just needed to trigger permission
        stream.getTracks().forEach(track => track.stop());
      } catch (permError: any) {
        if (permError.name === 'NotAllowedError' || permError.name === 'PermissionDeniedError') {
          toast.error('Camera permission denied. Please allow camera access in browser settings.');
          return;
        }
        if (permError.name === 'NotFoundError') {
          toast.error('No camera found on this device.');
          return;
        }
        throw permError;
      }

      // Now start the QR code scanner
      const html5QrCode = new Html5Qrcode('qr-reader');
      html5QrCodeRef.current = html5QrCode;

      await html5QrCode.start(
        { facingMode: 'environment' },
        {
          fps: 10,
          qrbox: { width: 250, height: 250 },
        },
        (decodedText) => {
          scanProduct(decodedText);
        },
        () => {
          // Scan error - ignore (happens continuously when no QR code in view)
        }
      );

      setIsCameraActive(true);
      toast.success('Camera started - point at barcode');
    } catch (error: any) {
      console.error('Error starting camera:', error);
      if (error.message && error.message.includes('Permission')) {
        toast.error('Camera permission denied. Check your browser settings.');
      } else {
        toast.error(`Failed to start camera: ${error.message || 'Unknown error'}`);
      }
    }
  };

  const stopCamera = async () => {
    try {
      if (html5QrCodeRef.current) {
        await html5QrCodeRef.current.stop();
        html5QrCodeRef.current = null;
      }
      setIsCameraActive(false);
    } catch (error) {
      console.error('Error stopping camera:', error);
    }
  };

  const handleManualInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && manualInput.trim()) {
      e.preventDefault();
      scanProduct(manualInput);
    }
  };

  const filteredProducts = products.filter(product => {
    const search = productSearch.toLowerCase();
    return (
      product.prod_name.toLowerCase().includes(search) ||
      product.sku?.toLowerCase().includes(search) ||
      product.prod_code?.toLowerCase().includes(search)
    );
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading transaction...</p>
        </div>
      </div>
    );
  }

  if (!transaction) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <p className="text-gray-600 dark:text-gray-400">Transaction not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="outline"
            size="icon"
            onClick={() => {
              if (isActive && lineItems.length > 0) {
                const shouldLeave = window.confirm(
                  'You have unsaved scanned items. Are you sure you want to leave? All scanned items will be lost.'
                );
                if (shouldLeave) {
                  cancelIssuance().then(() => navigate('/transactions'));
                }
              } else {
                navigate('/transactions');
              }
            }}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">
              Fulfill Order
            </h1>
            <p className="text-gray-600 dark:text-gray-400">
              Transaction {transaction.tx_id}
            </p>
          </div>
        </div>
      </div>

      {/* Transaction Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Transaction Details</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Total Amount</p>
              <p className="text-2xl font-bold">{formatCurrency(transaction.amount)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Fulfilled</p>
              <p className="text-2xl font-bold text-green-600">
                {formatCurrency(transaction.amount_fulfilled || '0')}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Remaining</p>
              <p className="text-2xl font-bold text-orange-600">
                {formatCurrency(transaction.remaining_amount || transaction.amount)}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Status</p>
              <p className="text-xl font-semibold">
                {isActive ? (
                  <span className="text-blue-600 flex items-center gap-2">
                    <Scan className="h-5 w-5 animate-pulse" />
                    Active
                  </span>
                ) : (
                  <span className="text-gray-500">Inactive</span>
                )}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {!isActive ? (
        /* Loading/Activating Screen */
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-12">
              <Package className="h-16 w-16 text-gray-400 mx-auto mb-4 animate-pulse" />
              <h2 className="text-2xl font-bold mb-2">Activating Issuance...</h2>
              <p className="text-gray-600 dark:text-gray-400 max-w-md mx-auto">
                Preparing to scan products. Please wait...
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        /* Fulfillment Interface */
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Input Methods Card */}
          <Card>
            <CardHeader>
              <CardTitle>Add Products</CardTitle>
              <CardDescription>
                Choose your preferred input method
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Tabs value={inputMode} onValueChange={(value) => {
                setInputMode(value as 'scanner' | 'camera' | 'manual');
                if (value !== 'camera') {
                  stopCamera();
                }
              }}>
                <TabsList className="grid w-full grid-cols-3">
                  <TabsTrigger value="scanner">
                    <Keyboard className="mr-2 h-4 w-4" />
                    Scanner
                  </TabsTrigger>
                  <TabsTrigger value="camera">
                    <Camera className="mr-2 h-4 w-4" />
                    Camera
                  </TabsTrigger>
                  <TabsTrigger value="manual">
                    <Search className="mr-2 h-4 w-4" />
                    Manual
                  </TabsTrigger>
                </TabsList>

                {/* USB/Bluetooth Scanner Tab */}
                <TabsContent value="scanner" className="space-y-4 mt-6">
                  <div className="rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 p-8 text-center">
                    <Keyboard className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                    <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                      Scan barcode with your USB or Bluetooth scanner
                    </p>
                    <div className="max-w-md mx-auto space-y-3">
                      <div className="space-y-2">
                        <Label htmlFor="manualInput">Barcode / SKU</Label>
                        <Input
                          id="manualInput"
                          ref={manualInputRef}
                          type="text"
                          placeholder="Scan or type barcode..."
                          value={manualInput}
                          onChange={(e) => setManualInput(e.target.value)}
                          onKeyDown={handleManualInputKeyDown}
                          disabled={isScanning}
                          className="text-center text-lg font-mono h-12"
                          autoFocus
                        />
                      </div>
                      <Button
                        onClick={() => scanProduct(manualInput)}
                        disabled={isScanning || !manualInput.trim()}
                        className="w-full"
                      >
                        {isScanning ? 'Adding...' : 'Add Product'}
                      </Button>
                    </div>
                  </div>
                </TabsContent>

                {/* Phone Camera Tab */}
                <TabsContent value="camera" className="space-y-4 mt-6">
                  <div className="space-y-4">
                    {!isCameraActive ? (
                      <div className="rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 p-8 text-center">
                        <Camera className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                          Use your phone camera to scan barcodes
                        </p>
                        <Button onClick={startCamera} className="bg-blue-600 hover:bg-blue-700">
                          <Camera className="mr-2 h-4 w-4" />
                          Start Camera
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <div id="qr-reader" className="rounded-lg overflow-hidden"></div>
                        <Button onClick={stopCamera} variant="outline" className="w-full">
                          <XCircle className="mr-2 h-4 w-4" />
                          Stop Camera
                        </Button>
                      </div>
                    )}
                  </div>
                </TabsContent>

                {/* Manual Selection Tab */}
                <TabsContent value="manual" className="space-y-4 mt-6">
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="productSearch">Search Products</Label>
                      <Input
                        id="productSearch"
                        type="text"
                        placeholder="Search by name, SKU, or code..."
                        value={productSearch}
                        onChange={(e) => setProductSearch(e.target.value)}
                        className="h-10"
                      />
                    </div>

                    <div className="max-h-[300px] overflow-y-auto border rounded-lg">
                      {filteredProducts.length === 0 ? (
                        <div className="text-center py-8 text-gray-500">
                          <Search className="h-8 w-8 mx-auto mb-2 opacity-50" />
                          <p className="text-sm">No products found</p>
                        </div>
                      ) : (
                        <div className="divide-y dark:divide-gray-700">
                          {filteredProducts.slice(0, 10).map(product => (
                            <div
                              key={product.id}
                              onClick={() => setSelectedProduct(product)}
                              className={`p-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 ${
                                selectedProduct?.id === product.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                              }`}
                            >
                              <div className="flex justify-between items-start">
                                <div>
                                  <p className="font-semibold text-sm">{product.prod_name}</p>
                                  <p className="text-xs text-gray-500">
                                    {product.prod_code} • Stock: {product.quantity}
                                  </p>
                                </div>
                                <p className="font-bold text-sm">{formatCurrency(product.current_price)}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {selectedProduct && (
                      <div className="border rounded-lg p-4 bg-blue-50 dark:bg-blue-900/20">
                        <p className="text-sm font-semibold mb-3">Selected: {selectedProduct.prod_name}</p>
                        <div className="flex items-center gap-3">
                          <div className="flex items-center gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setManualQuantity(Math.max(1, manualQuantity - 1))}
                            >
                              <Minus className="h-3 w-3" />
                            </Button>
                            <Input
                              type="number"
                              min="1"
                              value={manualQuantity}
                              onChange={(e) => setManualQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                              className="w-20 text-center"
                            />
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setManualQuantity(manualQuantity + 1)}
                            >
                              <Plus className="h-3 w-3" />
                            </Button>
                          </div>
                          <Button
                            onClick={addManualProduct}
                            disabled={isScanning}
                            className="flex-1"
                          >
                            {isScanning ? 'Adding...' : 'Add to Order'}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>

          {/* Scanned Items Card */}
          <Card>
            <CardHeader>
              <CardTitle>Items Added ({lineItems.length})</CardTitle>
              <CardDescription>
                Products in this fulfillment
              </CardDescription>
            </CardHeader>
            <CardContent>
              {lineItems.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <AlertCircle className="h-12 w-12 mx-auto mb-2 opacity-50" />
                  <p>No items added yet</p>
                  <p className="text-sm mt-1">Use scanner, camera, or manual selection</p>
                </div>
              ) : (
                <div className="space-y-3 max-h-[500px] overflow-y-auto">
                  {lineItems.map((item, index) => (
                    <div
                      key={item.id}
                      className="flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 group"
                    >
                      <div className="flex items-center gap-3 flex-1">
                        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center text-blue-600 dark:text-blue-400 font-semibold">
                          {index + 1}
                        </div>
                        <div className="flex-1">
                          <p className="font-semibold text-sm">{item.product_name}</p>
                          <p className="text-xs text-gray-500">{item.product_code}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <p className="font-bold">{formatCurrency(item.line_total)}</p>
                          <p className="text-xs text-gray-500">
                            {item.quantity} × {formatCurrency(item.unit_price)}
                          </p>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => removeLineItem(item.id, item.product_name)}
                          className="opacity-0 group-hover:opacity-100 transition-opacity text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950/30"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700 space-y-3">
                {lineItems.length > 0 ? (
                  <>
                    <Button
                      onClick={completeIssuance}
                      className="w-full bg-green-600 hover:bg-green-700"
                      size="lg"
                    >
                      <CheckCircle2 className="mr-2 h-5 w-5" />
                      Complete Issuance ({lineItems.length} items)
                    </Button>
                    <Button
                      onClick={cancelIssuance}
                      variant="outline"
                      className="w-full border-red-300 text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/30"
                      size="lg"
                    >
                      <XCircle className="mr-2 h-5 w-5" />
                      Cancel Issuance
                    </Button>
                  </>
                ) : (
                  <Button
                    onClick={cancelIssuance}
                    variant="outline"
                    className="w-full border-red-300 text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/30"
                    size="lg"
                  >
                    <XCircle className="mr-2 h-5 w-5" />
                    Cancel & Go Back
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
