import { useState } from 'react';
import { toast } from 'sonner';
import {
  createStockTakeSession,
  getStockTakeSession,
  scanProductToStockTake,
  completeStockTakeSession,
  removeStockTakeItem,
  searchProductBySku,
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
} from 'lucide-react';
import BarcodeScanner from '../components/scanner/BarcodeScanner';
import type { ParsedBarcode } from '../utils/barcodeParser';

export default function StockTakingPage() {
  const [session, setSession] = useState<StockTakeSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);

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

  const handleScan = async (barcode: ParsedBarcode) => {
    if (!session) return;

    try {
      setProcessing(true);

      // Search for product by SKU
      const productData = await searchProductBySku(barcode.sku);

      if (!productData) {
        toast.error(`Product not found: ${barcode.sku}`);
        return;
      }

      // Scan product to stock take (staged)
      await scanProductToStockTake(
        session.session_id,
        productData.id,
        barcode.quantity,
        'user'
      );

      toast.success(`Scanned ${barcode.quantity}x ${productData.prod_name}`);
      await fetchSessionDetails(session.session_id);
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to scan product');
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

  const isDraft = session?.status === 'DRAFT';
  const isCompleted = session?.status === 'COMPLETED';

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ClipboardList className="h-8 w-8" />
            Stock Taking
          </h1>
          <p className="text-gray-600 mt-1">
            Scan products to add inventory stock
          </p>
        </div>

        {!session && (
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
        )}
      </div>

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
                        <TableCell className="text-right font-semibold text-green-600">
                          +{item.quantity_scanned}
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
                onClick={() => setSession(null)}
                disabled={processing}
              >
                Cancel
              </Button>
              <Button
                onClick={handleComplete}
                disabled={processing || !session.items?.length}
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
    </div>
  );
}
