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
