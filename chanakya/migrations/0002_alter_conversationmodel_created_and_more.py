# Generated by Django 5.0.6 on 2024-07-30 08:56

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chanakya', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversationmodel',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='created'),
        ),
        migrations.AlterField(
            model_name='feedbackmodel',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name='messagemodel',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='created'),
        ),
        migrations.AlterField(
            model_name='promptsmodel',
            name='created_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
