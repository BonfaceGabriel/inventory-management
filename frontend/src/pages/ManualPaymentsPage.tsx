import { toast } from 'sonner';
import { useForm, Controller } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { extractApiError } from '@/lib/error-utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { DateTimePicker } from '@/components/ui/date-time-picker';
import { useCreateManualPayment } from '@/services/queries/payments';

interface ManualPaymentForm {
  amount: string;
  payment_date: Date | null;
  payer_name: string;
}

export default function ManualPaymentsPage() {
  const navigate = useNavigate();
  const { register, handleSubmit, control, formState: { errors } } = useForm<ManualPaymentForm>({
    defaultValues: {
      payment_date: new Date(),
    }
  });
  const createPayment = useCreateManualPayment();

  const onSubmit = async (data: ManualPaymentForm) => {
    try {
      const paymentData = {
        payment_method: 'PDQ',
        amount: data.amount,
        payment_date: data.payment_date ? data.payment_date.toISOString() : new Date().toISOString(),
        payer_name: data.payer_name,
        created_by: 'Web Dashboard User',
      };
      await createPayment.mutateAsync(paymentData as any);
      toast.success('Manual payment created successfully', {
        description: `PDQ payment of KES ${data.amount}`
      });
      navigate('/transactions');
    } catch (error: any) {
      console.error('Failed to create payment:', error);
      toast.error('Failed to create payment', {
        description: extractApiError(error, 'An error occurred while creating the payment')
      });
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Manual Payments</h1>
        <p className="text-gray-600 dark:text-gray-400">Record PDQ card payments</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Payment Form */}
        <Card>
          <CardHeader>
            <CardTitle>New Manual Payment</CardTitle>
            <CardDescription>Enter payment details for non-SMS payments</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="payer_name">Payer Name *</Label>
                <Input
                  id="payer_name"
                  placeholder="John Doe"
                  {...register('payer_name', { required: 'Payer name is required' })}
                />
                {errors.payer_name && (
                  <p className="text-sm text-destructive">{errors.payer_name.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="amount">Amount (KES) *</Label>
                <Input
                  id="amount"
                  type="number"
                  step="0.01"
                  placeholder="1000.00"
                  {...register('amount', { required: 'Amount is required', min: 0.01 })}
                />
                {errors.amount && (
                  <p className="text-sm text-destructive">{errors.amount.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="payment_date">Payment Date & Time *</Label>
                <Controller
                  name="payment_date"
                  control={control}
                  rules={{ required: 'Date and time are required' }}
                  render={({ field }) => (
                    <DateTimePicker
                      selected={field.value}
                      onChange={field.onChange}
                      showTimeSelect
                      dateFormat="yyyy-MM-dd HH:mm"
                      placeholderText="Select date and time"
                    />
                  )}
                />
                {errors.payment_date && (
                  <p className="text-sm text-red-600 dark:text-red-400">{errors.payment_date.message}</p>
                )}
              </div>

              {createPayment.isError && (
                <div className="rounded-lg bg-[rgb(var(--color-destructive))]/[0.1] dark:bg-red-900/20 p-4 text-sm text-red-600 dark:text-red-400">
                  ✗ Failed to record payment. Please try again.
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={createPayment.isPending}
              >
                {createPayment.isPending ? 'Saving...' : 'Record Payment'}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Instructions */}
        <Card>
          <CardHeader>
            <CardTitle>Instructions</CardTitle>
            <CardDescription>How to record manual payments</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <h4 className="font-medium mb-2">PDQ Card Payments</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Use this form to record payments made via the PDQ card machine. These are added directly to the transaction ledger and included in daily reconciliation reports.
              </p>
            </div>

            <div>
              <h4 className="font-medium mb-2">Required Information</h4>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li>• Payer's name</li>
                <li>• Payment amount in KES</li>
                <li>• Date and time of payment (defaults to current time)</li>
              </ul>
            </div>

            <div>
              <h4 className="font-medium mb-2">Important Notes</h4>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li>• All fields marked with * are required</li>
                <li>• Payments will be included in daily reports</li>
                <li>• Once saved, payments cannot be deleted</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
