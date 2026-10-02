from django.db import migrations


def backfill_options_from_existing_variants(apps, schema_editor):
    """
    Derive COLOR/SIZE options from data that already exists.

    Before this change, an item's variants were decided by its item_type, and
    items could hold variant stock rows or order lines for colour/size values
    that were never declared as options. With item_type gone, an item with no
    options means "no variants", so those values would be silently orphaned.
    Collect every colour/size already in use per item and declare them as
    options first.
    """
    MerchandiseCatalogItem = apps.get_model('payments', 'MerchandiseCatalogItem')
    MerchandiseCatalogOption = apps.get_model('payments', 'MerchandiseCatalogOption')
    MerchandiseStock = apps.get_model('payments', 'MerchandiseStock')
    MerchandiseOrderLine = apps.get_model('payments', 'MerchandiseOrderLine')

    for item in MerchandiseCatalogItem.objects.all():
        for option_type, field in (('COLOR', 'color'), ('SIZE', 'size')):
            values = set()
            for model, related in (
                (MerchandiseStock, 'stock_levels'),
                (MerchandiseOrderLine, 'order_lines'),
            ):
                for value in (
                    model.objects.filter(item_id=item.id)
                    .exclude(**{f'{field}__isnull': True})
                    .exclude(**{field: ''})
                    .values_list(field, flat=True)
                    .distinct()
                ):
                    values.add(value)

            for value in sorted(values):
                MerchandiseCatalogOption.objects.get_or_create(
                    item_id=item.id,
                    option_type=option_type,
                    value=value,
                )


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0033_add_product_image_field'),
    ]

    operations = [
        migrations.RunPython(
            backfill_options_from_existing_variants,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='merchandisecatalogitem',
            name='item_type',
        ),
    ]