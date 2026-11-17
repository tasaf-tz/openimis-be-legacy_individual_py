
import core.fields
import core.utils
import datetime
import dirtyfields.dirtyfields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('location', '0019_alter_location_code'),
        ('legacy_individual', '0009_search_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='Rm4Group',
            fields=[
                ('id', models.UUIDField(db_column='UUID', default=None, editable=False, primary_key=True, serialize=False)),
                ('is_deleted', models.BooleanField(db_column='isDeleted', default=False)),
                ('date_created', core.fields.DateTimeField(db_column='DateCreated', default=datetime.datetime.now, null=True)),
                ('date_updated', core.fields.DateTimeField(db_column='DateUpdated', default=datetime.datetime.now, null=True)),
                ('version', models.IntegerField(default=1)),
                ('code', models.CharField(max_length=64)),
                ('json_ext', models.JSONField(blank=True, db_column='Json_ext', default=dict)),
                ('archive_batch', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='rm4_groups', to='legacy_individual.legacyimportbatch')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='rm4_groups', to='location.location')),
                ('user_created', models.ForeignKey(db_column='UserCreatedUUID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(class)s_user_created', to=settings.AUTH_USER_MODEL)),
                ('user_updated', models.ForeignKey(db_column='UserUpdatedUUID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(class)s_user_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'managed': True,
            },
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, core.utils.CachedModelMixin, models.Model),
        ),
        migrations.CreateModel(
            name='Rm4Individual',
            fields=[
                ('id', models.UUIDField(db_column='UUID', default=None, editable=False, primary_key=True, serialize=False)),
                ('is_deleted', models.BooleanField(db_column='isDeleted', default=False)),
                ('date_created', core.fields.DateTimeField(db_column='DateCreated', default=datetime.datetime.now, null=True)),
                ('date_updated', core.fields.DateTimeField(db_column='DateUpdated', default=datetime.datetime.now, null=True)),
                ('version', models.IntegerField(default=1)),
                ('first_name', models.CharField(max_length=255)),
                ('last_name', models.CharField(max_length=255)),
                ('dob', core.fields.DateField(blank=True, null=True)),
                ('json_ext', models.JSONField(blank=True, db_column='Json_ext', default=dict)),
                ('archive_batch', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='rm4_individuals', to='legacy_individual.legacyimportbatch')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='rm4_individuals', to='location.location')),
                ('user_created', models.ForeignKey(db_column='UserCreatedUUID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(class)s_user_created', to=settings.AUTH_USER_MODEL)),
                ('user_updated', models.ForeignKey(db_column='UserUpdatedUUID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(class)s_user_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'managed': True,
            },
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, core.utils.CachedModelMixin, models.Model),
        ),
        migrations.CreateModel(
            name='Rm4GroupIndividual',
            fields=[
                ('id', models.UUIDField(db_column='UUID', default=None, editable=False, primary_key=True, serialize=False)),
                ('is_deleted', models.BooleanField(db_column='isDeleted', default=False)),
                ('date_created', core.fields.DateTimeField(db_column='DateCreated', default=datetime.datetime.now, null=True)),
                ('date_updated', core.fields.DateTimeField(db_column='DateUpdated', default=datetime.datetime.now, null=True)),
                ('version', models.IntegerField(default=1)),
                ('role', models.CharField(blank=True, max_length=255, null=True)),
                ('recipient_type', models.CharField(blank=True, max_length=255, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('json_ext', models.JSONField(blank=True, db_column='Json_ext', default=dict)),
                ('archive_batch', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='rm4_group_individuals', to='legacy_individual.legacyimportbatch')),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='memberships', to='legacy_individual.rm4group')),
                ('individual', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='memberships', to='legacy_individual.rm4individual')),
                ('user_created', models.ForeignKey(db_column='UserCreatedUUID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(class)s_user_created', to=settings.AUTH_USER_MODEL)),
                ('user_updated', models.ForeignKey(db_column='UserUpdatedUUID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='%(class)s_user_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'managed': True,
            },
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, core.utils.CachedModelMixin, models.Model),
        ),
        migrations.CreateModel(
            name='HistoricalRm4Individual',
            fields=[
                ('id', models.UUIDField(db_column='UUID', db_index=True, default=None, editable=False)),
                ('is_deleted', models.BooleanField(db_column='isDeleted', default=False)),
                ('date_created', core.fields.DateTimeField(db_column='DateCreated', default=datetime.datetime.now, null=True)),
                ('date_updated', core.fields.DateTimeField(db_column='DateUpdated', default=datetime.datetime.now, null=True)),
                ('version', models.IntegerField(default=1)),
                ('first_name', models.CharField(max_length=255)),
                ('last_name', models.CharField(max_length=255)),
                ('dob', core.fields.DateField(blank=True, null=True)),
                ('json_ext', models.JSONField(blank=True, db_column='Json_ext', default=dict)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('archive_batch', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='legacy_individual.legacyimportbatch')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('location', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='location.location')),
                ('user_created', models.ForeignKey(blank=True, db_column='UserCreatedUUID', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user_updated', models.ForeignKey(blank=True, db_column='UserUpdatedUUID', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical rm4 individual',
                'verbose_name_plural': 'historical rm4 individuals',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='HistoricalRm4GroupIndividual',
            fields=[
                ('id', models.UUIDField(db_column='UUID', db_index=True, default=None, editable=False)),
                ('is_deleted', models.BooleanField(db_column='isDeleted', default=False)),
                ('date_created', core.fields.DateTimeField(db_column='DateCreated', default=datetime.datetime.now, null=True)),
                ('date_updated', core.fields.DateTimeField(db_column='DateUpdated', default=datetime.datetime.now, null=True)),
                ('version', models.IntegerField(default=1)),
                ('role', models.CharField(blank=True, max_length=255, null=True)),
                ('recipient_type', models.CharField(blank=True, max_length=255, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('json_ext', models.JSONField(blank=True, db_column='Json_ext', default=dict)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('archive_batch', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='legacy_individual.legacyimportbatch')),
                ('group', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='legacy_individual.rm4group')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('individual', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='legacy_individual.rm4individual')),
                ('user_created', models.ForeignKey(blank=True, db_column='UserCreatedUUID', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user_updated', models.ForeignKey(blank=True, db_column='UserUpdatedUUID', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical rm4 group individual',
                'verbose_name_plural': 'historical rm4 group individuals',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='HistoricalRm4Group',
            fields=[
                ('id', models.UUIDField(db_column='UUID', db_index=True, default=None, editable=False)),
                ('is_deleted', models.BooleanField(db_column='isDeleted', default=False)),
                ('date_created', core.fields.DateTimeField(db_column='DateCreated', default=datetime.datetime.now, null=True)),
                ('date_updated', core.fields.DateTimeField(db_column='DateUpdated', default=datetime.datetime.now, null=True)),
                ('version', models.IntegerField(default=1)),
                ('code', models.CharField(max_length=64)),
                ('json_ext', models.JSONField(blank=True, db_column='Json_ext', default=dict)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('archive_batch', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='legacy_individual.legacyimportbatch')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('location', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='location.location')),
                ('user_created', models.ForeignKey(blank=True, db_column='UserCreatedUUID', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user_updated', models.ForeignKey(blank=True, db_column='UserUpdatedUUID', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical rm4 group',
                'verbose_name_plural': 'historical rm4 groups',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddIndex(
            model_name='rm4individual',
            index=models.Index(fields=['last_name'], name='rm4_ind_last_name_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4individual',
            index=models.Index(fields=['first_name'], name='rm4_ind_first_name_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4individual',
            index=models.Index(fields=['dob'], name='rm4_ind_dob_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4individual',
            index=models.Index(fields=['location'], name='rm4_ind_location_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4individual',
            index=models.Index(fields=['archive_batch'], name='rm4_ind_batch_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4groupindividual',
            index=models.Index(fields=['group'], name='rm4_gi_group_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4groupindividual',
            index=models.Index(fields=['individual'], name='rm4_gi_individual_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4groupindividual',
            index=models.Index(fields=['archive_batch'], name='rm4_gi_batch_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4group',
            index=models.Index(fields=['code'], name='rm4_group_code_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4group',
            index=models.Index(fields=['location'], name='rm4_group_location_idx'),
        ),
        migrations.AddIndex(
            model_name='rm4group',
            index=models.Index(fields=['archive_batch'], name='rm4_group_batch_idx'),
        ),
    ]
