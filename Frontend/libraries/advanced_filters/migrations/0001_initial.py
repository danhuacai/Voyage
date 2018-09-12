# -*- coding: utf-8 -*-
# Generated by Django 1.9.4 on 2016-03-07 23:02


from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AdvancedFilter',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('url', models.CharField(max_length=255)),
                ('b64_query', models.CharField(max_length=2048)),
                ('model', models.CharField(blank=True, max_length=64, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='created_advanced_filters', to=settings.AUTH_USER_MODEL)),
                ('groups', models.ManyToManyField(blank=True, to='auth.Group')),
                ('users', models.ManyToManyField(blank=True, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Advanced Filters',
                'verbose_name': 'Advanced Filter',
            },
        ),
    ]
