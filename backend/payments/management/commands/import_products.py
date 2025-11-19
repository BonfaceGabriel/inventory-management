"""
Django management command to import products from the consignment order form.
Data extracted from products.jpeg - Consignment Order Form dated 2025/09/15.

Usage:
    python manage.py import_products
    python manage.py import_products --clear  # Clear existing products first
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from payments.models import Product, ProductCategory


class Command(BaseCommand):
    help = 'Import 32 products from the consignment order form (products.jpeg)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing products before importing',
        )

    def handle(self, *args, **options):
        # Product data extracted from products.jpeg
        # Columns: ProdCode, ProdName, SKU/Name, Price, SKU PV
        products_data = [
            {'prod_code': 'AP004E', 'prod_name': 'MicroQ2 Cycle Tablets', 'sku_name': '100 tablets', 'price': '2970.00', 'pv': '11.00'},
            {'prod_code': 'AP008E', 'prod_name': 'Consiclean Capsules', 'sku_name': "30's/Box(Box)", 'price': '3915.00', 'pv': '22.00'},
            {'prod_code': 'AP009F', 'prod_name': 'Prostaflexa™ Capsules', 'sku_name': "60's/bottle", 'price': '3240.00', 'pv': '18.00'},
            {'prod_code': 'AP011E', 'prod_name': '2 in 1 Reishi Coffee', 'sku_name': '20 sachets/box', 'price': '1755.00', 'pv': '6.50'},
            {'prod_code': 'AP013E', 'prod_name': 'Pure & Broken Ganoderma Spores', 'sku_name': "30's/Bottle(Bottle)", 'price': '7785.00', 'pv': '57.00'},
            {'prod_code': 'AP014E', 'prod_name': 'Refined Yunzhi Capsules', 'sku_name': "60's/bottle", 'price': '3915.00', 'pv': '24.00'},
            {'prod_code': 'AP022E', 'prod_name': 'Arthroviva Tablets', 'sku_name': "60's/Bottle(Bottle)", 'price': '5400.00', 'pv': '36.00'},
            {'prod_code': 'AP024E', 'prod_name': 'AnalacicM Herbal Essence Soap', 'sku_name': "1's/Box(Box)", 'price': '297.00', 'pv': '1.00'},
            {'prod_code': 'AP026E', 'prod_name': '4 in 1 Ginseng Coffee', 'sku_name': '20 sachets/box', 'price': '1755.00', 'pv': '6.50'},
            {'prod_code': 'AP029E', 'prod_name': 'X Power Man Capsules - New', 'sku_name': "30's/Bottle(Bottle)", 'price': '5670.00', 'pv': '35.00'},
            {'prod_code': 'AP039E', 'prod_name': '4 in 1 Cordyceps Coffee', 'sku_name': "20's/Box", 'price': '1755.00', 'pv': '6.50'},
            {'prod_code': 'AP041E', 'prod_name': 'Novel Diople Capsules', 'sku_name': "60's/Bottle(Bottle)", 'price': '2970.00', 'pv': '17.00'},
            {'prod_code': 'AP042E', 'prod_name': 'Feminergy Capsules', 'sku_name': '60 capsules/bottle', 'price': '4050.00', 'pv': '25.00'},
            {'prod_code': 'AP077E', 'prod_name': 'CereBrain Tablets', 'sku_name': "60's/Bottle(Bottle)", 'price': '3375.00', 'pv': '22.00'},
            {'prod_code': 'AP081E', 'prod_name': 'Relifin Tea', 'sku_name': '20 sachets/box', 'price': '2430.00', 'pv': '9.00'},
            {'prod_code': 'AP097E', 'prod_name': 'Detoxilive Capsules', 'sku_name': '60 coffees/box', 'price': '2025.00', 'pv': '10.00'},
            {'prod_code': 'AP101E', 'prod_name': 'Tooth Paste', 'sku_name': '130g/box', 'price': '742.50', 'pv': '2.80'},
            {'prod_code': 'AP102E', 'prod_name': 'Ex-Zilin Capsule', 'sku_name': '90 Tablets', 'price': '7020.00', 'pv': '45.00'},
            {'prod_code': 'AP107E', 'prod_name': 'ZaminoCal Plus', 'sku_name': '60 Tablets', 'price': '3105.00', 'pv': '18.00'},
            {'prod_code': 'AP118F', 'prod_name': 'Elements', 'sku_name': '20 sachets', 'price': '4050.00', 'pv': '15.00'},
            {'prod_code': 'AP131A', 'prod_name': 'COOLROLL', 'sku_name': '1 bottle', 'price': '135.00', 'pv': '0.20'},
            {'prod_code': 'AP132B', 'prod_name': 'MClairr Pills', 'sku_name': "20's /bottle", 'price': '135.00', 'pv': '0.20'},
            {'prod_code': 'AP144B', 'prod_name': 'MMN Coffee', 'sku_name': '20 Sachets/Box', 'price': '3375.00', 'pv': '12.50'},
            {'prod_code': 'AP153A', 'prod_name': 'Quad-Shield', 'sku_name': '60capsules/bottle', 'price': '4725.00', 'pv': '28.00'},
            {'prod_code': 'AP155C', 'prod_name': 'Probio 3+', 'sku_name': "30's/Box", 'price': '4050.00', 'pv': '22.00'},
            {'prod_code': 'AP169A', 'prod_name': 'Veggie Veggie', 'sku_name': '15 sachets', 'price': '4050.00', 'pv': '23.00'},
            {'prod_code': 'AP177A', 'prod_name': 'Pure &Broken Ganoderma Spores', 'sku_name': '60capsules', 'price': '14850.00', 'pv': '99.00'},
            {'prod_code': 'AP188A', 'prod_name': 'Blueberry Chewable Tablets for Sharp Vision', 'sku_name': '90 Tablets', 'price': '3240.00', 'pv': '18.00'},
            {'prod_code': 'AP190A', 'prod_name': 'Gluzojoini Ultra Pro', 'sku_name': '60 tablets', 'price': '7560.00', 'pv': '44.80'},
            {'prod_code': 'AP192C', 'prod_name': 'FemiCalcium D3', 'sku_name': '120 Tablets', 'price': '4320.00', 'pv': '24.50'},
            {'prod_code': 'KIT001', 'prod_name': 'Kit', 'sku_name': '1 pcs', 'price': '2700.00', 'pv': '0.00'},
        ]

        # If --clear flag is set, delete all existing products
        if options['clear']:
            deleted_count = Product.objects.all().count()
            Product.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f'Deleted {deleted_count} existing products')
            )

        # Get or create default category
        default_category, created = ProductCategory.objects.get_or_create(
            name='General Products',
            defaults={'description': 'Default category for imported products'}
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Created default category: {default_category.name}')
            )

        # Import products
        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for idx, data in enumerate(products_data, start=1):
                prod_code = data['prod_code']
                prod_name = data['prod_name']
                sku_name = data['sku_name']
                price = Decimal(data['price'])
                pv = Decimal(data['pv'])

                # Generate SKU from prod_code (remove any special characters)
                sku = prod_code.upper().replace('-', '').replace(' ', '')

                # Set cost_price to 70% of selling price (default assumption)
                # This can be updated later with actual cost data
                cost_price = (price * Decimal('0.70')).quantize(Decimal('0.01'))

                # Check if product already exists
                product, created = Product.objects.update_or_create(
                    prod_code=prod_code,
                    defaults={
                        'prod_name': prod_name,
                        'sku': sku,
                        'sku_name': sku_name,
                        'current_price': price,
                        'cost_price': cost_price,
                        'current_pv': pv,
                        'quantity': 0,  # Start with zero inventory
                        'reorder_level': 10,  # Default reorder level
                        'category': default_category,
                        'is_active': True,
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ [{idx}/31] Created: {prod_code} - {prod_name} (Price: {price}, PV: {pv})'
                        )
                    )
                else:
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'↻ [{idx}/31] Updated: {prod_code} - {prod_name} (Price: {price}, PV: {pv})'
                        )
                    )

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('IMPORT SUMMARY'))
        self.stdout.write(self.style.SUCCESS('='*70))
        self.stdout.write(self.style.SUCCESS(f'Created: {created_count}'))
        self.stdout.write(self.style.WARNING(f'Updated: {updated_count}'))
        self.stdout.write(self.style.ERROR(f'Skipped: {skipped_count}'))
        self.stdout.write(self.style.SUCCESS(f'Total Products: {Product.objects.count()}'))
        self.stdout.write(self.style.SUCCESS('='*70))
        self.stdout.write(
            self.style.SUCCESS(
                '\n✓ Product import completed successfully!'
            )
        )
