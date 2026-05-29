from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0027_merchandise_models'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MerchandiseStock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('color', models.CharField(blank=True, max_length=50, null=True)),
                ('size', models.CharField(blank=True, max_length=50, null=True)),
                ('quantity', models.IntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_levels', to='payments.merchandisecatalogitem')),
            ],
            options={
                'verbose_name': 'Merchandise Stock',
                'verbose_name_plural': 'Merchandise Stocks',
                'ordering': ['item__name', 'color', 'size'],
                'unique_together': {('item', 'color', 'size')},
            },
        ),
        migrations.CreateModel(
            name='MerchandiseStockMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movement_type', models.CharField(choices=[('MANUAL_ADD', 'Manual Add'), ('MANUAL_DEDUCT', 'Manual Deduct'), ('FULFILLMENT', 'Fulfillment Deduction')], db_index=True, max_length=20)),
                ('quantity_change', models.IntegerField()),
                ('quantity_before', models.IntegerField()),
                ('quantity_after', models.IntegerField()),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='merchandise_stock_movements', to=settings.AUTH_USER_MODEL)),
                ('stock', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movements', to='payments.merchandisestock')),
            ],
            options={
                'verbose_name': 'Merchandise Stock Movement',
                'verbose_name_plural': 'Merchandise Stock Movements',
                'ordering': ['-created_at'],
            },
        ),
    ]
