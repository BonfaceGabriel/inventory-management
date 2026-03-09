import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useBeforeUnload } from 'react-router';
import { toast } from 'sonner';
import {
  createStockTakeSession,
  getStockTakeSession,
  scanProductToStockTake,
  completeStockTakeSession,
  removeStockTakeItem,
  updateStockTakeItemQuantity,
  searchProductBySku,
  listActiveStockTakeSessions,
  cancelStockTakeSession,
  cancelAllActiveStockTakeSessions,
  updateStockTakeKitQuantity,
} from '../services/api';
import type { StockTakeSession, StockTakeItem } from '../types/transaction.types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  Loader2,
  Package,
  Trash2,
  CheckCircle,
  Plus,
  Scan,
  ClipboardList,
  XCircle,
  AlertCircle,
  RefreshCw,
  Settings,
  ArrowLeft,
  Gift,
} from 'lucide-react';
import BarcodeScanner from '../components/scanner/BarcodeScanner';
import type { ParsedBarcode } from '../utils/barcodeParser';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/ui/alert-dialog';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '../components/ui/tabs';

export default function StockTakingPage() {
  const navigate = useNavigate();
  const [session, setSession] = useState<StockTakeSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [activeSessions, setActiveSessions] = useState<StockTakeSession[]>([]);
  const [loadingActiveSessions, setLoadingActiveSessions] = useState(false);
  const [sessionToCancel, setSessionToCancel] = useState<string | null>(null);
  const [showCancelAllDialog, setShowCancelAllDialog] = useState(false);
  const [showCurrentSessionCancelDialog, setShowCurrentSessionCancelDialog] = useState(false);
  const [showNavigationDialog, setShowNavigationDialog] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'current' | 'manage'>('current');

  // Debounce timer ref for kit quantity update
  const kitQuantityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce timer ref for session refetch
  const refetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce timer ref for quantity updates
  const quantityUpdateTimerRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  // Warn user before closing browser tab if session is active
  useBeforeUnload(
    (e) => {
      if (session && session.status === 'DRAFT') {
        e.preventDefault();
        return 'You have an active stock take session. Are you sure you want to leave?';
      }
    },
    { capture: true }
  );

  const handleStartSession = async () => {
    try {
      setLoading(true);
      const data = await createStockTakeSession('user', 'Stock taking session');
      setSession(data);
      toast.success(`Session ${data.session_id} started`);
    } catch (error: any) {
      toast.error('Failed to start stock take session');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const fetchSessionDetails = async (sessionId: string) => {
    try {
      setLoading(true);
      const data = await getStockTakeSession(sessionId);
      setSession(data);
    } catch (error: any) {
      toast.error('Failed to load session details');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // Debounced session refetch - only refetch after 500ms of inactivity
  const debouncedRefetch = useCallback((sessionId: string) => {
    // Clear existing timer
    if (refetchTimerRef.current) {
      clearTimeout(refetchTimerRef.current);
    }

    // Set new timer
    refetchTimerRef.current = setTimeout(() => {
      fetchSessionDetails(sessionId);
    }, 500); // Wait 500ms after last scan before refetching
  }, []);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (refetchTimerRef.current) {
        clearTimeout(refetchTimerRef.current);
      }
      if (kitQuantityTimerRef.current) {
        clearTimeout(kitQuantityTimerRef.current);
      }
      // Clear all quantity update timers
      quantityUpdateTimerRef.current.forEach((timer) => clearTimeout(timer));
      quantityUpdateTimerRef.current.clear();
    };
  }, []);

  const handleScan = async (barcode: ParsedBarcode) => {
    if (!session) return;

    try {
      setProcessing(true);

      // Search for product by SKU, prod_code, or barcode
      const productData = await searchProductBySku(barcode.sku, barcode.prod_code, barcode.barcode);

      if (!productData) {
        const identifier = barcode.sku || barcode.prod_code || barcode.barcode;
        toast.error(`Product not found: ${identifier}`);
        return;
      }

      // Scan product to stock take (staged)
      const response = await scanProductToStockTake(
        session.session_id,
        productData.id,
        barcode.quantity,
        'user'
      );

      toast.success(`Scanned ${barcode.quantity}x ${productData.prod_name}`);

      // Optimistic UI update - update session immediately with returned item
      if (response.item) {
        setSession((prevSession) => {
          if (!prevSession) return prevSession;

          // Check if item already exists in session (using product field, not product_id)
          const existingItemIndex = prevSession.items?.findIndex(
            (item: StockTakeItem) => item.product === response.item.product
          );

          let updatedItems;
          if (existingItemIndex !== undefined && existingItemIndex !== -1) {
            // Update existing item
            updatedItems = [...(prevSession.items || [])];
            updatedItems[existingItemIndex] = response.item;
          } else {
            // Add new item
            updatedItems = [...(prevSession.items || []), response.item];
          }

          return {
            ...prevSession,
            items: updatedItems,
            items_count: updatedItems.length,
            total_quantity_added: updatedItems.reduce(
              (sum: number, item: StockTakeItem) => sum + item.quantity_scanned,
              0
            ),
          };
        });
      }

      // Debounced refetch to sync with server (only after user stops scanning)
      debouncedRefetch(session.session_id);
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to scan product');
      // On error, refetch immediately to ensure data consistency
      await fetchSessionDetails(session.session_id);
    } finally {
      setProcessing(false);
    }
  };

  const handleRemoveItem = async (itemId: number) => {
    if (!session) return;

    try {
      setProcessing(true);
      await removeStockTakeItem(session.session_id, itemId);
      toast.success('Item removed');
      await fetchSessionDetails(session.session_id);
    } catch (error: any) {
      toast.error('Failed to remove item');
    } finally {
      setProcessing(false);
    }
  };

  const handleQuantityChange = (itemId: number, newQuantity: number) => {
    if (!session || newQuantity < 0) return;

    // Update local state immediately for responsive UI
    setSession({
      ...session,
      items: session.items?.map((item: StockTakeItem) =>
        item.id === itemId
          ? {
              ...item,
              quantity_scanned: newQuantity,
              quantity_after: item.quantity_before + newQuantity,
            }
          : item
      ),
      total_quantity_added: session.items?.reduce(
        (sum: number, item: StockTakeItem) =>
          sum + (item.id === itemId ? newQuantity : item.quantity_scanned),
        0
      ) || 0,
    });

    // Clear existing timer for this item
    const existingTimer = quantityUpdateTimerRef.current.get(itemId);
    if (existingTimer) {
      clearTimeout(existingTimer);
    }

    // Debounce API call - update backend after user stops typing (1 second delay)
    const newTimer = setTimeout(async () => {
      try {
        await updateStockTakeItemQuantity(session.session_id, itemId, newQuantity);
        quantityUpdateTimerRef.current.delete(itemId);
      } catch (error: any) {
        toast.error('Failed to update quantity');
        // Revert local state on error by refetching
        await fetchSessionDetails(session.session_id);
        quantityUpdateTimerRef.current.delete(itemId);
      }
    }, 1000); // Wait 1 second after last change

    quantityUpdateTimerRef.current.set(itemId, newTimer);
  };

  const handleKitQuantityChange = (newQuantity: number) => {
    if (!session || newQuantity < 0) return;

    // Update local state immediately
    setSession({ ...session, kit_quantity: newQuantity });

    // Clear existing timer
    if (kitQuantityTimerRef.current) {
      clearTimeout(kitQuantityTimerRef.current);
    }

    // Debounce API call
    kitQuantityTimerRef.current = setTimeout(async () => {
      try {
        await updateStockTakeKitQuantity(session.session_id, newQuantity);
        kitQuantityTimerRef.current = null;
      } catch (error: any) {
        toast.error('Failed to update kit quantity');
        await fetchSessionDetails(session.session_id);
        kitQuantityTimerRef.current = null;
      }
    }, 1000);
  };

  const handleComplete = async () => {
    if (!session) return;

    if (!session.items || session.items.length === 0) {
      toast.error('Cannot complete session with no items');
      return;
    }

    try {
      setProcessing(true);
      await completeStockTakeSession(session.session_id, 'user');
      toast.success('Stock take session completed! Inventory updated.');
      await fetchSessionDetails(session.session_id);
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to complete session');
    } finally {
      setProcessing(false);
    }
  };

  const fetchActiveSessions = async () => {
    try {
      setLoadingActiveSessions(true);
      const response = await listActiveStockTakeSessions();
      setActiveSessions(response.sessions || []);
    } catch (error: any) {
      toast.error('Failed to load active sessions');
      console.error(error);
    } finally {
      setLoadingActiveSessions(false);
    }
  };

  const handleCancelSession = async (sessionId: string) => {
    try {
      setProcessing(true);
      await cancelStockTakeSession(sessionId, 'admin');
      toast.success(`Session ${sessionId} cancelled`);
      setSessionToCancel(null);
      setShowCurrentSessionCancelDialog(false);

      // If canceling current session, clear it
      if (session && session.session_id === sessionId) {
        setSession(null);
      }

      await fetchActiveSessions();
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to cancel session');
    } finally {
      setProcessing(false);
    }
  };

  const handleCancelAllSessions = async () => {
    try {
      setProcessing(true);
      const response = await cancelAllActiveStockTakeSessions('admin');
      toast.success(response.message || 'All active sessions cancelled');
      setShowCancelAllDialog(false);
      await fetchActiveSessions();
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to cancel all sessions');
    } finally {
      setProcessing(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'manage') {
      fetchActiveSessions();
    }
  }, [activeTab]);

  const isDraft = session?.status === 'DRAFT';
  const isCompleted = session?.status === 'COMPLETED';

  const handleNavigateBack = () => {
    if (session && session.status === 'DRAFT') {
      setShowNavigationDialog(true);
      setPendingNavigation('/');
    } else {
      navigate('/');
    }
  };

  const confirmNavigation = () => {
    setShowNavigationDialog(false);
    if (pendingNavigation) {
      navigate(pendingNavigation);
    }
  };

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleNavigateBack}
            className="mb-2"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ClipboardList className="h-8 w-8" />
            Stock Taking
          </h1>
          <p className="text-gray-600 mt-1">
            Scan products to add inventory stock
          </p>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'current' | 'manage')} className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="current">Current Session</TabsTrigger>
          <TabsTrigger value="manage">
            <Settings className="h-4 w-4 mr-2" />
            Manage Sessions
            {activeSessions.length > 0 && (
              <Badge variant="destructive" className="ml-2">{activeSessions.length}</Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="current" className="mt-6">
          {!session && (
            <div className="flex justify-end mb-4">
              <Button
                onClick={handleStartSession}
                disabled={loading}
                size="lg"
                className="bg-green-600 hover:bg-green-700"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    Starting...
                  </>
                ) : (
                  <>
                    <Plus className="mr-2 h-5 w-5" />
                    New Stock Take Session
                  </>
                )}
              </Button>
            </div>
          )}

          {session ? (
        <div className="space-y-4">
          {/* Session Header */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>{session.session_id}</CardTitle>
                  <p className="text-sm text-gray-500 mt-1">
                    Created by {session.created_by} on{' '}
                    {new Date(session.created_at).toLocaleString()}
                  </p>
                </div>
                <Badge
                  variant={
                    isCompleted ? 'default' : isDraft ? 'secondary' : 'destructive'
                  }
                >
                  {session.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-gray-600">Items Scanned</p>
                  <p className="text-2xl font-bold">{session.items_count || 0}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Total Quantity Added</p>
                  <p className="text-2xl font-bold text-green-600">
                    +{session.total_quantity_added || 0}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Barcode Scanner - only show if session is in draft */}
          {isDraft && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Scan className="h-4 w-4" />
                  Scan Products
                </CardTitle>
              </CardHeader>
              <CardContent>
                <BarcodeScanner
                  onScan={handleScan}
                  disabled={processing}
                  placeholder="Scan or enter barcode..."
                  autoFocus
                />
                <p className="text-xs text-gray-500 mt-2">
                  Scan products to add to stock. Scanned quantities will be added to existing inventory.
                </p>
              </CardContent>
            </Card>
          )}

          {/* Registration Kits - always visible, no barcode needed */}
          <Card className={isDraft ? 'border-blue-200' : ''}>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Gift className="h-4 w-4 text-blue-600" />
                Registration Kits
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <p className="text-sm text-gray-600 mb-1">Kits counted (no barcode required)</p>
                  {isDraft ? (
                    <input
                      type="number"
                      min="0"
                      value={session.kit_quantity ?? 0}
                      onChange={(e) => handleKitQuantityChange(parseInt(e.target.value) || 0)}
                      className="w-32 px-3 py-2 text-right border rounded-md focus:ring-2 focus:ring-blue-500 font-semibold text-blue-600 text-lg"
                      disabled={processing}
                    />
                  ) : (
                    <p className="text-2xl font-bold text-blue-600">
                      {session.kit_quantity ?? 0}
                    </p>
                  )}
                </div>
                {isDraft && (
                  <p className="text-xs text-gray-400 max-w-xs">
                    Enter the number of registration kits in stock. This updates the REG_KIT_001 inventory when the session is completed.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Scanned Items Table */}
          {session.items && session.items.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Scanned Products {isDraft && <Badge variant="outline" className="ml-2">DRAFT</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Product Name</TableHead>
                      <TableHead>Product Code</TableHead>
                      <TableHead>SKU</TableHead>
                      <TableHead className="text-right">Stock Before</TableHead>
                      <TableHead className="text-right">Qty Scanned</TableHead>
                      <TableHead className="text-right">Stock After</TableHead>
                      <TableHead>Scanned At</TableHead>
                      {isDraft && <TableHead className="w-[50px]"></TableHead>}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {session.items.map((item: StockTakeItem) => (
                      <TableRow key={item.id}>
                        <TableCell className="font-medium">
                          {item.product_name}
                        </TableCell>
                        <TableCell className="text-gray-600">
                          {item.product_code}
                        </TableCell>
                        <TableCell className="text-gray-600">
                          {item.sku}
                        </TableCell>
                        <TableCell className="text-right">
                          {item.quantity_before}
                        </TableCell>
                        <TableCell className="text-right">
                          {isDraft ? (
                            <input
                              type="number"
                              min="1"
                              value={item.quantity_scanned}
                              onChange={(e) => handleQuantityChange(item.id, parseInt(e.target.value) || 0)}
                              className="w-20 px-2 py-1 text-right border rounded focus:ring-2 focus:ring-green-500 font-semibold text-green-600"
                              disabled={processing}
                            />
                          ) : (
                            <span className="font-semibold text-green-600">+{item.quantity_scanned}</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-bold">
                          {item.quantity_after}
                        </TableCell>
                        <TableCell className="text-sm text-gray-500">
                          {new Date(item.scanned_at).toLocaleString()}
                        </TableCell>
                        {isDraft && (
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleRemoveItem(item.id)}
                              disabled={processing}
                            >
                              <Trash2 className="h-4 w-4 text-red-500" />
                            </Button>
                          </TableCell>
                        )}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Actions */}
          {isDraft && (
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setShowCurrentSessionCancelDialog(true)}
                disabled={processing}
              >
                Cancel Session
              </Button>
              <Button
                onClick={handleComplete}
                disabled={processing || (!session.items?.length && !session.kit_quantity)}
                className="bg-green-600 hover:bg-green-700"
              >
                {processing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Completing...
                  </>
                ) : (
                  <>
                    <CheckCircle className="mr-2 h-4 w-4" />
                    Complete Session
                  </>
                )}
              </Button>
            </div>
          )}

          {isDraft && (
            <p className="text-xs text-gray-500 text-center">
              Completing this session will add all scanned quantities to the current inventory stock.
            </p>
          )}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Package className="h-16 w-16 text-gray-300 mb-4" />
            <p className="text-gray-600 mb-4">No active stock take session</p>
            <Button
              onClick={handleStartSession}
              disabled={loading}
              className="bg-green-600 hover:bg-green-700"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Plus className="mr-2 h-4 w-4" />
                  Start New Session
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      )}
        </TabsContent>

        <TabsContent value="manage" className="mt-6">
          <div className="space-y-4">
            {loadingActiveSessions ? (
              <Card>
                <CardContent className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
                </CardContent>
              </Card>
            ) : activeSessions.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center justify-center py-12">
                  <ClipboardList className="h-16 w-16 text-gray-300 mb-4" />
                  <p className="text-gray-600 text-lg font-medium">No active stock take sessions</p>
                  <p className="text-gray-500 text-sm mt-2">
                    All sessions have been completed or cancelled
                  </p>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>
                      Active Sessions ({activeSessions.length})
                    </CardTitle>
                    <div className="flex gap-2">
                      <Button
                        onClick={fetchActiveSessions}
                        variant="outline"
                        size="sm"
                        disabled={loadingActiveSessions}
                      >
                        <RefreshCw className={`mr-2 h-4 w-4 ${loadingActiveSessions ? 'animate-spin' : ''}`} />
                        Refresh
                      </Button>
                      <Button
                        onClick={() => setShowCancelAllDialog(true)}
                        variant="destructive"
                        size="sm"
                        disabled={processing}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Cancel All
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-md flex items-start gap-2">
                    <AlertCircle className="h-5 w-5 text-amber-600 mt-0.5 flex-shrink-0" />
                    <div className="text-sm text-amber-800">
                      <p className="font-medium">Active sessions block certain operations</p>
                      <p className="text-amber-700 mt-1">
                        While stock take sessions are active, you cannot create combined orders.
                        Cancel these sessions to restore full functionality.
                      </p>
                    </div>
                  </div>

                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Session ID</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Created By</TableHead>
                        <TableHead>Created At</TableHead>
                        <TableHead>Items</TableHead>
                        <TableHead>Total Qty</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {activeSessions.map((sess) => (
                        <TableRow key={sess.session_id}>
                          <TableCell className="font-medium">
                            {sess.session_id}
                          </TableCell>
                          <TableCell>
                            <Badge variant="secondary">
                              {sess.status}
                            </Badge>
                          </TableCell>
                          <TableCell>{sess.created_by}</TableCell>
                          <TableCell className="text-gray-600">
                            {new Date(sess.created_at).toLocaleString()}
                          </TableCell>
                          <TableCell>{sess.items_count || 0}</TableCell>
                          <TableCell className="font-semibold text-green-600">
                            +{sess.total_quantity_added || 0}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              onClick={() => setSessionToCancel(sess.session_id)}
                              variant="destructive"
                              size="sm"
                              disabled={processing}
                            >
                              <XCircle className="mr-1 h-4 w-4" />
                              Cancel
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {/* Cancel Single Session Dialog */}
      <AlertDialog
        open={!!sessionToCancel}
        onOpenChange={(open) => !open && setSessionToCancel(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel Stock Take Session?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to cancel session <strong>{sessionToCancel}</strong>?
              This will abandon the session and no inventory changes will be made.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={processing}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => sessionToCancel && handleCancelSession(sessionToCancel)}
              disabled={processing}
              className="bg-red-600 hover:bg-red-700"
            >
              {processing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cancelling...
                </>
              ) : (
                'Confirm Cancel'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cancel All Sessions Dialog */}
      <AlertDialog
        open={showCancelAllDialog}
        onOpenChange={setShowCancelAllDialog}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel All Active Sessions?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to cancel <strong>all {activeSessions.length} active session(s)</strong>?
              This will abandon all sessions and no inventory changes will be made.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={processing}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleCancelAllSessions}
              disabled={processing}
              className="bg-red-600 hover:bg-red-700"
            >
              {processing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cancelling All...
                </>
              ) : (
                'Confirm Cancel All'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cancel Current Session Dialog */}
      <AlertDialog
        open={showCurrentSessionCancelDialog}
        onOpenChange={setShowCurrentSessionCancelDialog}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel Stock Take Session?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to cancel the current stock take session?
              <br />
              <strong>All scanned items will be lost</strong> and no inventory changes will be made.
              <br />
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={processing}>Keep Session</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => session && handleCancelSession(session.session_id)}
              disabled={processing}
              className="bg-red-600 hover:bg-red-700"
            >
              {processing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cancelling...
                </>
              ) : (
                <>
                  <XCircle className="mr-2 h-4 w-4" />
                  Cancel Session
                </>
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Navigation Confirmation Dialog */}
      <AlertDialog
        open={showNavigationDialog}
        onOpenChange={setShowNavigationDialog}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave Stock Take Session?</AlertDialogTitle>
            <AlertDialogDescription>
              You have an active stock take session with scanned items.
              <br />
              <strong>Do you want to complete or cancel the session before leaving?</strong>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col sm:flex-row gap-2">
            <AlertDialogCancel disabled={processing}>
              Stay on Page
            </AlertDialogCancel>
            <Button
              variant="outline"
              onClick={() => {
                setShowNavigationDialog(false);
                setShowCurrentSessionCancelDialog(true);
              }}
              disabled={processing}
            >
              <XCircle className="mr-2 h-4 w-4" />
              Cancel Session
            </Button>
            <AlertDialogAction
              onClick={confirmNavigation}
              disabled={processing}
              className="bg-blue-600 hover:bg-blue-700"
            >
              Leave Anyway
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
