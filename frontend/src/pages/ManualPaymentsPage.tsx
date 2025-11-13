import { useState } from 'react';
import { toast } from 'sonner';
import { useForm, Controller } from 'react-hook-form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { DateTimePicker } from '@/components/ui/date-time-picker';
import { useCreateManualPayment } from '@/services/queries/payments';

interface ManualPaymentForm {
  payment_method: string;
  amount: string;
  payment_date: Date | null;
  payer_name: string;
  payer_phone: string;
  reference_number: string;
  gateway_id: string;
  notes: string;
}

export default function ManualPaymentsPage() {
  const [success, setSuccess] = useState(false);
  const { register, handleSubmit, reset, control, formState: { errors } } = useForm<ManualPaymentForm>({
    defaultValues: {
      payment_date: new Date(),
    }
  });
  const createPayment = useCreateManualPayment();

  const onSubmit = async (data: ManualPaymentForm) => {
    try {
      // Convert date to ISO datetime format and add created_by
      const paymentData = {
        ...data,
        payment_date: data.payment_date ? data.payment_date.toISOString() : new Date().toISOString(),
        created_by: 'Web Dashboard User', // Default user
      };
      await createPayment.mutateAsync(paymentData as any);
      toast.success('Manual payment created successfully', {
        description: `${data.payment_method} payment of KES ${data.amount}`
      });
      setSuccess(true);
      reset({ payment_date: new Date() });
      setTimeout(() => setSuccess(false), 3000);
    } catch (error: any) {
      console.error('Failed to create payment:', error);
      toast.error('Failed to create payment', {
        description: error.response?.data?.error || 'An error occurred while creating the payment'
      });
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Manual Payments</h1>
        <p className="text-gray-600 dark:text-gray-400">Enter payments from PDQ, Bank, Cash, or Cheque</p>
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
                <Label htmlFor="payment_method">Payment Method *</Label>
                <Select
                  id="payment_method"
                  {...register('payment_method', { required: 'Payment method is required' })}
                >
                  <option value="">Select method...</option>
                  <option value="PDQ">PDQ (Card Machine)</option>
                  <option value="BANK_TRANSFER">Bank Transfer</option>
                  <option value="CASH">Cash</option>
                  <option value="CHEQUE">Cheque</option>
                </Select>
                {errors.payment_method && (
                  <p className="text-sm text-destructive">{errors.payment_method.message}</p>
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
                <Label htmlFor="payer_phone">Payer Phone</Label>
                <Input
                  id="payer_phone"
                  placeholder="0712345678"
                  {...register('payer_phone')}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="reference_number">Reference Number (Optional)</Label>
                <Input
                  id="reference_number"
                  placeholder="REF123456 (optional)"
                  {...register('reference_number')}
                />
                {errors.reference_number && (
                  <p className="text-sm text-destructive">{errors.reference_number.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="notes">Notes</Label>
                <Input
                  id="notes"
                  placeholder="Additional information..."
                  {...register('notes')}
                />
              </div>

              {success && (
                <div className="rounded-lg bg-green-50 dark:bg-green-900/20 p-4 text-sm text-green-600 dark:text-green-400">
                  ✓ Payment recorded successfully!
                </div>
              )}

              {createPayment.isError && (
                <div className="rounded-lg bg-red-50 dark:bg-red-900/20 p-4 text-sm text-red-600 dark:text-red-400">
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
              <h4 className="font-medium mb-2">Payment Methods</h4>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li><strong>PDQ:</strong> For card payments via the PDQ machine</li>
                <li><strong>Bank Transfer:</strong> For direct bank transfers</li>
                <li><strong>Cash:</strong> For cash payments</li>
                <li><strong>Cheque:</strong> For cheque payments</li>
              </ul>
            </div>

            <div>
              <h4 className="font-medium mb-2">Required Information</h4>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li>• Payment method and amount</li>
                <li>• Date and time of payment (defaults to current time)</li>
                <li>• Payer's name</li>
                <li>• Reference number (transaction ID, receipt number, etc.)</li>
              </ul>
            </div>

            <div>
              <h4 className="font-medium mb-2">Important Notes</h4>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li>• All fields marked with * are required</li>
                <li>• Reference numbers must be unique</li>
                <li>• You can select both date and time for accurate records</li>
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
