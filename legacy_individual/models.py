from django.db import models
from django.utils.translation import gettext_lazy as _

import core
from core.models import HistoryModel
from location.models import Location, HealthFacility


class LegacyImportBatch(HistoryModel):
    """One paired PSSN upload (household + member CSV)."""

    USE_CACHE = False

    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        IN_PROGRESS = 'IN_PROGRESS', _('In progress')
        SUCCESS = 'SUCCESS', _('Success')
        COMPLETED_WITH_ERRORS = 'COMPLETED_WITH_ERRORS', _('Completed with errors')
        FAIL = 'FAIL', _('Fail')

    code = models.CharField(max_length=64, blank=True, null=True)
    source_system = models.CharField(max_length=64, default='PSSN')
    household_file_name = models.CharField(max_length=255, blank=True, null=True)
    member_file_name = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    started_at = core.fields.DateTimeField(null=True, blank=True)
    finished_at = core.fields.DateTimeField(null=True, blank=True)

    # An import covers exactly one district, so the scope is denormalised here rather than
    # derived from the imported rows -- filtering the batch list must not scan
    # LegacyIndividual. Nullable: batches predating this, and uploads whose district cannot
    # be resolved, keep NULL and are handled by backfill_batch_locations.
    region = models.ForeignKey(
        Location, on_delete=models.DO_NOTHING, null=True, blank=True,
        related_name='legacy_import_batches_region',
    )
    district = models.ForeignKey(
        Location, on_delete=models.DO_NOTHING, null=True, blank=True,
        related_name='legacy_import_batches_district',
    )

    total_households = models.IntegerField(default=0)
    total_members = models.IntegerField(default=0)
    success_household_count = models.IntegerField(default=0)
    success_member_count = models.IntegerField(default=0)
    warning_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    error = models.JSONField(blank=True, default=dict)

    def __str__(self):
        return f"LegacyImportBatch {self.code or self.id} [{self.status}]"

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['status']),
            models.Index(fields=['source_system']),
            models.Index(fields=['date_created']),
            models.Index(fields=['district']),
            models.Index(fields=['region']),
        ]


class LegacyGroup(HistoryModel):
    """One PSSN household. Keyed by REGISTRATIONNO."""

    USE_CACHE = False

    code = models.CharField(max_length=20)
    import_batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.DO_NOTHING,
        related_name='legacy_groups',
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        related_name='legacy_groups',
    )

    def __str__(self):
        return f"LegacyGroup {self.code}"

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['location']),
            models.Index(fields=['import_batch']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['code', 'import_batch'],
                condition=models.Q(is_deleted=False),
                name='legacy_group_code_per_batch_unique',
            ),
        ]


class LegacyIndividual(HistoryModel):
    """One PSSN member."""

    USE_CACHE = False

    legacy_code = models.CharField(max_length=32)
    import_batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.DO_NOTHING,
        related_name='legacy_individuals',
    )

    first_name = models.CharField(max_length=255, blank=True)
    middle_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True)
    dob = core.fields.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, blank=True, null=True)
    disability = models.BooleanField(null=True, blank=True)
    phone_no = models.CharField(max_length=32, blank=True, null=True)
    nin = models.CharField(max_length=32, blank=True, null=True)
    premno = models.CharField(max_length=32, blank=True, null=True)

    location = models.ForeignKey(
        Location,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        related_name='legacy_individuals',
    )
    facility = models.ForeignKey(
        HealthFacility,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        related_name='legacy_individuals',
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.legacy_code})"

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['legacy_code']),
            models.Index(fields=['premno']),
            models.Index(fields=['first_name'], name='legacy_ind_first_n_idx'),
            models.Index(fields=['last_name']),
            models.Index(fields=['dob']),
            models.Index(fields=['location']),
            models.Index(fields=['facility']),
            models.Index(fields=['import_batch']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['legacy_code', 'import_batch'],
                condition=models.Q(is_deleted=False),
                name='legacy_individual_legacycode_per_batch_unique',
            ),
            models.UniqueConstraint(
                fields=['nin'],
                condition=(
                    models.Q(is_deleted=False)
                    & ~models.Q(nin=None)
                    & ~models.Q(nin='')
                ),
                name='legacy_individual_nin_unique_when_present',
            ),
        ]


class LegacyGroupIndividual(HistoryModel):
    """Membership row joining LegacyGroup and LegacyIndividual."""

    USE_CACHE = False

    class Role(models.TextChoices):
        HEAD = 'HEAD', _('HEAD')
        SPOUSE = 'SPOUSE', _('SPOUSE')
        SON = 'SON', _('SON')
        DAUGHTER = 'DAUGHTER', _('DAUGHTER')
        FATHER = 'FATHER', _('FATHER')
        MOTHER = 'MOTHER', _('MOTHER')
        BROTHER = 'BROTHER', _('BROTHER')
        SISTER = 'SISTER', _('SISTER')
        GRANDSON = 'GRANDSON', _('GRANDSON')
        GRANDDAUGHTER = 'GRANDDAUGHTER', _('GRANDDAUGHTER')
        GRANDFATHER = 'GRANDFATHER', _('GRANDFATHER')
        GRANDMOTHER = 'GRANDMOTHER', _('GRANDMOTHER')
        SON_IN_LAW = 'SON IN LAW', _('SON IN LAW')
        DAUGHTER_IN_LAW = 'DAUGHTER IN LAW', _('DAUGHTER IN LAW')
        FATHER_IN_LAW = 'FATHER IN LAW', _('FATHER IN LAW')
        MOTHER_IN_LAW = 'MOTHER IN LAW', _('MOTHER IN LAW')
        STEP_CHILD = 'STEP CHILD', _('STEP CHILD')
        CO_WIFE = 'CO-WIFE', _('CO-WIFE')
        BROTHER_IN_LAW = 'BROTHER IN LAW', _('BROTHER IN LAW')
        SISTER_IN_LAW = 'SISTER IN LAW', _('SISTER IN LAW')
        HOUSE_HELP = 'HOUSE HELP', _('HOUSE HELP')
        OTHER_RELATIVE = 'OTHER RELATIVE', _('OTHER RELATIVE')
        NOT_RELATED = 'NOT RELATED', _('NOT RELATED')

    class RecipientType(models.TextChoices):
        PRIMARY = 'PRIMARY', _('PRIMARY')
        SECONDARY = 'SECONDARY', _('SECONDARY')

    group = models.ForeignKey(
        LegacyGroup,
        on_delete=models.DO_NOTHING,
        related_name='memberships',
    )
    individual = models.ForeignKey(
        LegacyIndividual,
        on_delete=models.DO_NOTHING,
        related_name='memberships',
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        blank=True,
        null=True,
    )
    relationship_code = models.CharField(max_length=8, blank=True, null=True)
    recipient_type = models.CharField(
        max_length=16,
        choices=RecipientType.choices,
        blank=True,
        null=True,
    )
    member_line = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['group']),
            models.Index(fields=['individual']),
            models.Index(fields=['role']),
            models.Index(fields=['relationship_code']),
            models.Index(fields=['member_line']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group', 'individual'],
                condition=models.Q(is_deleted=False),
                name='legacy_groupindividual_active_unique',
            ),
        ]


class _Rm4ArchiveRow(HistoryModel):
    """RM4 archive row: a frozen copy of a live individual-module row, keeping its UUID."""

    USE_CACHE = False

    class Meta:
        abstract = True

    @classmethod
    def _location_scoped(cls, queryset, user, prefix):
        from django.conf import settings
        from location.models import LocationManager

        if not settings.ROW_SECURITY:
            return queryset
        if user.is_anonymous:
            return queryset.none()
        if user.is_imis_admin:
            return queryset
        return queryset.filter(LocationManager().build_user_location_filter_query(user._u, prefix=prefix))


class Rm4Group(_Rm4ArchiveRow):
    """RM4 household. Mirrors individual.Group column for column."""

    code = models.CharField(max_length=64)
    json_ext = models.JSONField(db_column="Json_ext", blank=True, default=dict)
    location = models.ForeignKey(
        Location, on_delete=models.DO_NOTHING, blank=True, null=True, related_name='rm4_groups',
    )
    archive_batch = models.ForeignKey(
        LegacyImportBatch, on_delete=models.DO_NOTHING, related_name='rm4_groups',
    )

    def __str__(self):
        return f"Rm4Group {self.code}"

    @classmethod
    def get_queryset(cls, queryset, user):
        return cls._location_scoped(cls.objects.all() if queryset is None else queryset, user, 'location')

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['code'], name='rm4_group_code_idx'),
            models.Index(fields=['location'], name='rm4_group_location_idx'),
            models.Index(fields=['archive_batch'], name='rm4_group_batch_idx'),
        ]


class Rm4Individual(_Rm4ArchiveRow):
    """RM4 member. Mirrors individual.Individual (without the temporary tmp_pmt_poor column)."""

    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    dob = core.fields.DateField(null=True, blank=True)
    json_ext = models.JSONField(db_column="Json_ext", blank=True, default=dict)
    location = models.ForeignKey(
        Location, on_delete=models.DO_NOTHING, blank=True, null=True, related_name='rm4_individuals',
    )
    archive_batch = models.ForeignKey(
        LegacyImportBatch, on_delete=models.DO_NOTHING, related_name='rm4_individuals',
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @classmethod
    def get_queryset(cls, queryset, user):
        return cls._location_scoped(cls.objects.all() if queryset is None else queryset, user, 'location')

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['last_name'], name='rm4_ind_last_name_idx'),
            models.Index(fields=['first_name'], name='rm4_ind_first_name_idx'),
            models.Index(fields=['dob'], name='rm4_ind_dob_idx'),
            models.Index(fields=['location'], name='rm4_ind_location_idx'),
            models.Index(fields=['archive_batch'], name='rm4_ind_batch_idx'),
        ]


class Rm4GroupIndividual(_Rm4ArchiveRow):
    """RM4 household membership. Mirrors individual.GroupIndividual (same role and recipient values)."""

    group = models.ForeignKey(Rm4Group, on_delete=models.DO_NOTHING, related_name='memberships')
    individual = models.ForeignKey(Rm4Individual, on_delete=models.DO_NOTHING, related_name='memberships')
    role = models.CharField(max_length=255, null=True, blank=True)
    recipient_type = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    json_ext = models.JSONField(db_column="Json_ext", blank=True, default=dict)
    archive_batch = models.ForeignKey(
        LegacyImportBatch, on_delete=models.DO_NOTHING, related_name='rm4_group_individuals',
    )

    @classmethod
    def get_queryset(cls, queryset, user):
        return cls._location_scoped(cls.objects.all() if queryset is None else queryset, user, 'group__location')

    class Meta:
        managed = True
        indexes = [
            models.Index(fields=['group'], name='rm4_gi_group_idx'),
            models.Index(fields=['individual'], name='rm4_gi_individual_idx'),
            models.Index(fields=['archive_batch'], name='rm4_gi_batch_idx'),
        ]
