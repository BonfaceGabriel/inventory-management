import { useParams, useNavigate } from 'react-router';
import { ArrowLeft } from 'lucide-react';
import { Button } from '../components/ui/button';
import CombinedOrderDetailsView from '../components/transactions/CombinedOrderDetailsView';

export default function CombinedOrderScanningPage() {
  const { id: combinedOrderId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  if (!combinedOrderId) {
    return (
      <div className="container mx-auto p-6">
        <div className="text-center text-red-600">
          Invalid combined order ID
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-6 max-w-6xl">
      <div className="mb-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate('/transactions')}
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Transactions
        </Button>
      </div>

      <CombinedOrderDetailsView
        combinedOrderId={combinedOrderId}
        onClose={() => navigate('/transactions')}
        onUpdate={() => {
          // Optionally refresh or navigate after completion
        }}
      />
    </div>
  );
}
