import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0035_normalise_merchandise_sizes'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorymovement',
            name='location',
            field=models.ForeignKey(
                blank=True,
                help_text='Location where the inventory movement occurred',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='inventory_movements',
                to='payments.location',
            ),
        ),
    ]
