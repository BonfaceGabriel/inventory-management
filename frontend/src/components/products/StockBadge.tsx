import { Badge } from '@/components/ui/badge';

interface StockBadgeProps {
  status: string;
}

export function StockBadge({ status }: StockBadgeProps) {
  switch (status) {
    case 'OUT_OF_STOCK':
      return <Badge variant="destructive">Out of Stock</Badge>;
    case 'LOW_STOCK':
      return <Badge variant="default">Low Stock</Badge>;
    case 'IN_STOCK':
      return <Badge variant="secondary">In Stock</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}
