from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0026_main_shop_location_data'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MerchandiseCatalogItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=50, unique=True)),
                ('name', models.CharField(max_length=200)),
                ('item_type', models.CharField(choices=[('TSHIRT', 'Tshirt'), ('HAT', 'Hat'), ('COFFEE', 'Coffee')], db_index=True, max_length=20)),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Merchandise Catalog Item',
                'verbose_name_plural': 'Merchandise Catalog Items',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='MerchandiseOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('FULFILLED', 'Fulfilled'), ('CANCELLED', 'Cancelled')], db_index=True, default='PENDING', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('fulfilled_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('device', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='merchandise_orders', to='payments.device')),
                ('fulfilled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fulfilled_merchandise_orders', to=settings.AUTH_USER_MODEL)),
                ('gateway', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='merchandise_orders', to='payments.paymentgateway')),
                ('transaction', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='merchandise_order', to='payments.transaction')),
            ],
            options={
                'verbose_name': 'Merchandise Order',
                'verbose_name_plural': 'Merchandise Orders',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MerchandiseCatalogOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('option_type', models.CharField(choices=[('COLOR', 'Colour'), ('SIZE', 'Size')], db_index=True, max_length=10)),
                ('value', models.CharField(max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='options', to='payments.merchandisecatalogitem')),
            ],
            options={
                'verbose_name': 'Merchandise Catalog Option',
                'verbose_name_plural': 'Merchandise Catalog Options',
                'ordering': ['option_type', 'value'],
                'unique_together': {('item', 'option_type', 'value')},
            },
        ),
        migrations.CreateModel(
            name='MerchandiseOrderLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.PositiveIntegerField()),
                ('unit_price_snapshot', models.DecimalField(decimal_places=2, max_digits=10)),
                ('color', models.CharField(blank=True, max_length=50, null=True)),
                ('size', models.CharField(blank=True, max_length=50, null=True)),
                ('line_total', models.DecimalField(decimal_places=2, max_digits=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='order_lines', to='payments.merchandisecatalogitem')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='payments.merchandiseorder')),
            ],
            options={
                'verbose_name': 'Merchandise Order Line',
                'verbose_name_plural': 'Merchandise Order Lines',
                'ordering': ['id'],
            },
        ),
    ]
