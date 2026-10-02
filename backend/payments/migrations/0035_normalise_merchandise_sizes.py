from django.db import migrations

# Standard size labels. Spelled-out variants are folded into the short codes
# so a product never shows both "S" and "Small" as separate options.
SIZE_CANONICAL = {
    'small': 'S',
    'medium': 'M',
    'large': 'L',
    'x-large': 'XL',
    'xx-large': 'XXL',
}


def _canonical_size(value):
    if value is None:
        return None
    return SIZE_CANONICAL.get(value.strip().lower(), value)


def normalise_merchandise_sizes(apps, schema_editor):
    """
    Rename spelled-out size options to their short codes everywhere they appear:
    catalog options, per-variant stock rows, and historical order lines.

    Options are the source of truth, so stock rows and order lines must follow,
    otherwise renaming an option would orphan its stock.
    """
    MerchandiseCatalogOption = apps.get_model('payments', 'MerchandiseCatalogOption')
    MerchandiseStock = apps.get_model('payments', 'MerchandiseStock')
    MerchandiseOrderLine = apps.get_model('payments', 'MerchandiseOrderLine')

    item_ids = (
        MerchandiseCatalogOption.objects.filter(option_type='SIZE')
        .values_list('item_id', flat=True)
        .distinct()
    )

    for item_id in item_ids:
        options = list(
            MerchandiseCatalogOption.objects.filter(item_id=item_id, option_type='SIZE')
        )

        # 1. Options: fold duplicates, then rename in place.
        for option in options:
            target = _canonical_size(option.value)
            if target == option.value:
                continue

            clash = MerchandiseCatalogOption.objects.filter(
                item_id=item_id, option_type='SIZE', value=target
            ).exclude(pk=option.pk).first()

            if clash:
                # Target already declared, so this option is redundant.
                option.delete()
            else:
                option.value = target
                option.save(update_fields=['value'])

        # 2. Stock rows: merge into an existing target row rather than
        #    violating the (item, color, size) unique constraint.
        for stock in list(MerchandiseStock.objects.filter(item_id=item_id)):
            target = _canonical_size(stock.size)
            if target == stock.size:
                continue

            clash = MerchandiseStock.objects.filter(
                item_id=item_id, color=stock.color, size=target
            ).exclude(pk=stock.pk).first()

            if clash:
                clash.quantity += stock.quantity
                clash.save(update_fields=['quantity'])
                stock.delete()
            else:
                stock.size = target
                stock.save(update_fields=['size'])

        # 3. Order lines: no unique constraint, so a straight rename is safe.
        for line in MerchandiseOrderLine.objects.filter(item_id=item_id):
            target = _canonical_size(line.size)
            if target != line.size:
                line.size = target
                line.save(update_fields=['size'])


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0034_remove_merchandise_item_type'),
    ]

    operations = [
        migrations.RunPython(
            normalise_merchandise_sizes,
            migrations.RunPython.noop,
        ),
    ]