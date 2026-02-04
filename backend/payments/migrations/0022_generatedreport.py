from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0021_paymentgateway_is_parent_company'),
    ]

    operations = [
        migrations.CreateModel(
            name='GeneratedReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('report_date', models.DateField(unique=True)),
                ('report_file', models.BinaryField()),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Generated Report',
                'verbose_name_plural': 'Generated Reports',
                'ordering': ['-report_date'],
            },
        ),
    ]
