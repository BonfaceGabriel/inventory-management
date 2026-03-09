from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0023_promotion_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='stocktakesession',
            name='kit_quantity',
            field=models.IntegerField(default=0, help_text='Number of registration kits counted in this session'),
        ),
    ]
