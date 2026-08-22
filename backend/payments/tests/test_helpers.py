from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from payments.models import (
    Location, PaymentGateway, Product, ProductLine, Device, Transaction,
    ManualPayment, CombinedOrder, CombinedOrderTransaction, CombinedOrderLineItem,
    TransactionLineItem, InventoryMovement, StockTakeSession, StockTakeItem,
    DailyStockReconciliation, StockAdjustmentItem, EndOfDayValueReconciliation,
    Promotion, PromotionProduct, RawMessage, GeneratedReport,
    MerchandiseCatalogItem, MerchandiseCatalogOption, MerchandiseOrder,
    MerchandiseOrderLine, MerchandiseStock, MerchandiseStockMovement,
)

User = get_user_model()


def make_admin(username='admin', password='testpass123'):
    user, _ = User.objects.get_or_create(username=username, defaults={'role': 'ADMIN'})
    user.set_password(password)
    user.role = 'ADMIN'
    user.save(update_fields=['role', 'password'])
    return user


def make_processor(username='processor', password='testpass123'):
    user, _ = User.objects.get_or_create(username=username, defaults={'role': 'PROCESSOR'})
    user.set_password(password)
    user.role = 'PROCESSOR'
    user.save(update_fields=['role', 'password'])
    return user


def make_issuer(username='issuer', password='testpass123'):
    user, _ = User.objects.get_or_create(username=username, defaults={'role': 'ISSUER'})
    user.set_password(password)
    user.role = 'ISSUER'
    user.save(update_fields=['role', 'password'])
    return user


def make_location(name='Main Shop', location_type='MAIN'):
    loc, _ = Location.objects.get_or_create(
        name=name,
        defaults={'location_type': location_type, 'status': 'ACTIVE'}
    )
    return loc


def make_gateway(name='Till 1', gateway_type='MPESA_TILL', gateway_number='555000'):
    gw, _ = PaymentGateway.objects.get_or_create(
        gateway_number=gateway_number,
        defaults={
            'name': name,
            'gateway_type': gateway_type,
            'is_active': True,
        }
    )
    return gw


def make_product(prod_code='PROD001', prod_name='Test Product', price=Decimal('500.00'),
                 quantity=100, pv=Decimal('10.00'), cost_price=Decimal('300.00'),
                 sku=None, product_line=None, barcode=None):
    if sku is None:
        sku = prod_code
    prod, _ = Product.objects.get_or_create(
        prod_code=prod_code,
        defaults={
            'prod_name': prod_name,
            'sku': sku,
            'barcode': barcode or prod_code,
            'current_price': price,
            'cost_price': cost_price,
            'current_pv': pv,
            'quantity': quantity,
            'reorder_level': 10,
            'product_line': product_line,
            'is_active': True,
        }
    )
    return prod


def make_registration_kit_product():
    return make_product(
        prod_code='REG_KIT_001',
        prod_name='Registration Kit',
        price=Decimal('2900.00'),
        quantity=50,
        pv=Decimal('0.00'),
    )


def make_transaction(tx_id='TX001', amount=Decimal('1000.00'), status='NOT_PROCESSED',
                     gateway=None, sender_name='John Doe', sender_phone='0712345678',
                     unique_hash=None, location=None, is_registration=False,
                     amount_fulfilled=Decimal('0.00'), is_in_issuance=False):
    if gateway is None:
        gateway = make_gateway()
    if unique_hash is None:
        unique_hash = f'hash_{tx_id}'
    tx, _ = Transaction.objects.get_or_create(
        tx_id=tx_id,
        defaults={
            'amount': amount,
            'status': status,
            'gateway': gateway,
            'gateway_type': gateway.gateway_type,
            'sender_name': sender_name,
            'sender_phone': sender_phone,
            'timestamp': timezone.localtime(timezone.now()),
            'unique_hash': unique_hash,
            'location': location,
            'is_registration': is_registration,
            'amount_fulfilled': amount_fulfilled,
            'is_in_issuance': is_in_issuance,
        }
    )
    return tx


def make_device(name='Test Device', gateway=None, phone_number='0711111111'):
    if gateway is None:
        gateway = make_gateway()
    device = Device.objects.create(
        name=name,
        phone_number=phone_number,
        gateway=gateway,
        api_key='test-api-key-' + name.lower().replace(' ', '-'),
    )
    return device


def make_authenticated_client(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def make_device_client(device=None):
    if device is None:
        device = make_device()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=device.api_key)
    return client


def make_product_line(name='Test Line'):
    pl, _ = ProductLine.objects.get_or_create(name=name)
    return pl


def make_manual_payment(transaction=None, payment_method='CASH', amount=Decimal('500.00'),
                        payer_name='Jane Doe', reference_number=''):
    if transaction is None:
        transaction = make_transaction(tx_id='MAN-TX-001')
    mp = ManualPayment.objects.create(
        transaction=transaction,
        payment_method=payment_method,
        amount=amount,
        payer_name=payer_name,
        payer_phone='0722222222',
        payment_date=timezone.localtime(timezone.now()),
        reference_number=reference_number,
    )
    return mp


def make_combined_order(transactions=None, created_by=None, location=None):
    if location is None:
        location = make_location()
    if created_by is None:
        created_by = make_admin()
    if transactions is None:
        tx1 = make_transaction(tx_id='CMB-TX-01', amount=Decimal('1000.00'))
        tx2 = make_transaction(tx_id='CMB-TX-02', amount=Decimal('500.00'), unique_hash='hash_cmb2')
        transactions = [tx1, tx2]

    from payments.services.combined_order_service import CombinedOrderService
    result = CombinedOrderService.create_combined_order(
        transaction_ids=[t.id for t in transactions],
        created_by=created_by.username,
        created_by_user=created_by,
        location=location,
    )
    return CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])


def make_line_item(transaction, product, quantity=1, scanned_by_user=None):
    if scanned_by_user is None:
        scanned_by_user = make_issuer()
    return TransactionLineItem.objects.create(
        transaction=transaction,
        product=product,
        scanned_prod_code=product.prod_code,
        scanned_prod_name=product.prod_name,
        scanned_sku=product.sku,
        scanned_sku_name=product.sku_name,
        scanned_price=product.current_price,
        scanned_pv=product.current_pv,
        quantity=quantity,
        scanned_by_user=scanned_by_user,
    )


def make_daily_stock_reconciliation(date=None, created_by=None):
    if date is None:
        date = timezone.localdate()
    if created_by is None:
        created_by = make_admin()
    rec, _ = DailyStockReconciliation.objects.get_or_create(
        reconciliation_date=date,
        defaults={
            'status': 'DRAFT',
            'created_by': created_by,
        }
    )
    return rec


def make_stock_adjustment_item(reconciliation, product, opening_stock=100, closing_stock=100):
    adj, _ = StockAdjustmentItem.objects.get_or_create(
        reconciliation=reconciliation,
        product=product,
        defaults={
            'opening_stock': opening_stock,
            'closing_stock': closing_stock,
            'quantity_added': 0,
            'quantity_deducted': 0,
        }
    )
    return adj


def make_stock_take_session(created_by=None, location=None):
    if created_by is None:
        created_by = make_admin()
    if location is None:
        location = make_location()
    from payments.services.stock_take_service import StockTakeService
    return StockTakeService.create_session(created_by=created_by)


def today():
    return timezone.localdate()


def now():
    return timezone.localtime(timezone.now())
