from django.core.management.base import BaseCommand
from django.db import transaction

from payments.models import MerchandiseCatalogItem, MerchandiseCatalogOption


CATALOG = [
    {
        'code': 'MERCH_SET',
        'name': 'Shirt + Hat Set',
        'unit_price': '1400.00',
        'colors': ['yellow', 'green', 'lilac'],
        'sizes': ['S', 'M', 'L'],
        'is_active': True,
    },
    {
        'code': 'MERCH_NMN_COFFEE',
        'name': 'Nmn Coffee',
        'unit_price': '100.00',
        'colors': [],
        'sizes': [],
    },
    {
        'code': 'MERCH_REISHI_COFFEE',
        'name': 'Reishi Coffee',
        'unit_price': '100.00',
        'colors': [],
        'sizes': [],
    },
    {
        'code': 'MERCH_CORDYCEPS_COFFEE',
        'name': 'Cordyceps Coffee',
        'unit_price': '100.00',
        'colors': [],
        'sizes': [],
    },
    {
        'code': 'MERCH_GINSENG_COFFEE',
        'name': 'Ginseng Coffee',
        'unit_price': '100.00',
        'colors': [],
        'sizes': [],
    },
]


class Command(BaseCommand):
    help = 'Seed the dedicated merchandise catalog and options.'

    @transaction.atomic
    def handle(self, *args, **options):
        created_items = 0
        updated_items = 0
        active_codes = [item['code'] for item in CATALOG]

        # Cleanup: archive items no longer in CATALOG (never hard delete, they
        # may be referenced by historical merchandise orders).
        retired = MerchandiseCatalogItem.objects.exclude(code__in=active_codes)
        archived_count = retired.filter(is_active=True).update(is_active=False)
        if archived_count:
            self.stdout.write(self.style.WARNING(f'Archived {archived_count} catalog items.'))

        for item_data in CATALOG:
            item, created = MerchandiseCatalogItem.objects.update_or_create(
                code=item_data['code'],
                defaults={
                    'name': item_data['name'],
                    'unit_price': item_data['unit_price'],
                    'is_active': item_data.get('is_active', True),
                }
            )
            if created:
                created_items += 1
            else:
                updated_items += 1

            allowed_options = set()
            for color in item_data['colors']:
                allowed_options.add((MerchandiseCatalogOption.OptionType.COLOR, color))
                MerchandiseCatalogOption.objects.update_or_create(
                    item=item,
                    option_type=MerchandiseCatalogOption.OptionType.COLOR,
                    value=color,
                )

            for size in item_data['sizes']:
                allowed_options.add((MerchandiseCatalogOption.OptionType.SIZE, size))
                MerchandiseCatalogOption.objects.update_or_create(
                    item=item,
                    option_type=MerchandiseCatalogOption.OptionType.SIZE,
                    value=size,
                )

            MerchandiseCatalogOption.objects.filter(item=item).exclude(
                option_type__in=[t for t, _ in allowed_options] if allowed_options else ['COLOR', 'SIZE']
            ).delete()
            if allowed_options:
                for option in MerchandiseCatalogOption.objects.filter(item=item):
                    if (option.option_type, option.value) not in allowed_options:
                        option.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Seed complete: {created_items} created, {updated_items} updated.'
        ))
