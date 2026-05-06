"""
Service layer for the legacy_individual module.

Three classes:

- ``PssnNormalizationService``  — pure helpers: name/date/code normalization,
  gender/disability decoding, relationship-code → role mapping.
- ``LegacyImportBatchService``  — creates a batch, persists the two PSSN
  CSV files, kicks off the paired-upload workflow, finalizes the batch.
- ``LegacyIndividualService`` / ``LegacyGroupService`` — read-mostly helpers
  for the GraphQL layer.

Important: this module never writes to ``individual_individual`` or
``individual_group``. All writes target the legacy_individual_* tables.
"""

import logging
import os
import re
import uuid
from datetime import date, datetime
from typing import Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from legacy_individual.apps import LegacyIndividualConfig
from legacy_individual.models import (
    LegacyGroup,
    LegacyGroupIndividual,
    LegacyImportBatch,
    LegacyIndividual,
)

logger = logging.getLogger(__name__)


_LEGACY_UPLOAD_DIR = os.path.join(
    getattr(settings, 'BASE_DIR', '.'),
    'legacy_individual_uploads',
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class PssnNormalizationService:
    """Stateless helpers used by the workflow during file ingestion."""

    # See docs/legacy-individual-module/07_PSSN_COLUMN_MAPPING.md §6
    _CODE_WIDTH_BY_LEVEL = {
        'region': 2,
        'district': 4,
        'ward': 7,
        'village': 9,
    }

    @staticmethod
    def trim_name(value) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        return re.sub(r'\s+', ' ', s)

    @staticmethod
    def parse_dob(value) -> Optional[date]:
        """Parse PSSN date format ``YYYY-MM-DD HH:MM:SS.fff`` (or just YYYY-MM-DD)."""
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        # Take the YYYY-MM-DD prefix; ignore any trailing time.
        prefix = s.split(' ')[0].split('T')[0]
        try:
            return datetime.strptime(prefix, '%Y-%m-%d').date()
        except ValueError:
            return None

    @staticmethod
    def decode_gender(value) -> Optional[str]:
        """``1`` → ``M``, ``2`` → ``F``, blank → ``None``."""
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        if s == '1':
            return 'M'
        if s == '2':
            return 'F'
        # Sometimes upstream already mapped to letters
        if s.upper() in ('M', 'F'):
            return s.upper()
        return None

    @staticmethod
    def decode_disability(value) -> Optional[bool]:
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        if s == '1' or s.lower() in ('true', 'yes', 'y'):
            return True
        if s == '0' or s.lower() in ('false', 'no', 'n'):
            return False
        return None

    @classmethod
    def normalize_code(cls, value, level: str) -> Optional[str]:
        """Strip non-digits, drop trailing ``.0``, zero-pad to the level width."""
        width = cls._CODE_WIDTH_BY_LEVEL.get(level)
        if width is None:
            raise ValueError(f"Unknown code level: {level}")
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        s = s.split('.')[0]  # drop ".0" from Excel-cast floats
        s = re.sub(r'[^0-9]', '', s)
        if not s:
            return None
        return s.zfill(width)

    @staticmethod
    def map_relationship_to_role(rel_code, gender) -> Optional[str]:
        """
        Map ``RELATIONSHIPTOHEAD`` + ``SEX`` to the openIMIS role label.
        Source table: docs/legacy-individual-module/07_PSSN_COLUMN_MAPPING.md §6.
        """
        if rel_code is None:
            return None
        code = str(rel_code).strip()
        if not code:
            return None

        g = (gender or '').strip().upper()
        Role = LegacyGroupIndividual.Role

        if code == '1':
            return Role.HEAD
        if code in ('2', '12'):
            return Role.SPOUSE
        if code in ('3', '4'):
            if g == 'M':
                return Role.SON
            if g == 'F':
                return Role.DAUGHTER
            return Role.OTHER_RELATIVE
        if code == '5':
            if g == 'M':
                return Role.BROTHER
            if g == 'F':
                return Role.SISTER
            return Role.OTHER_RELATIVE
        if code == '6':
            if g == 'M':
                return Role.GRANDSON
            if g == 'F':
                return Role.GRANDDAUGHTER
            return Role.OTHER_RELATIVE
        if code == '7':
            if g == 'M':
                return Role.FATHER
            if g == 'F':
                return Role.MOTHER
            return Role.OTHER_RELATIVE
        if code == '14':
            return Role.NOT_RELATED
        return Role.OTHER_RELATIVE

    @staticmethod
    def derive_legacy_code(registration_no, member_line_no) -> Optional[str]:
        if not registration_no:
            return None
        line = str(member_line_no or '').strip()
        if not line:
            return str(registration_no).strip()
        return f"{str(registration_no).strip()}-{line}"


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------


def _ensure_upload_dir():
    os.makedirs(_LEGACY_UPLOAD_DIR, exist_ok=True)


def _save_uploaded_file(uploaded_file, batch_uuid: str, role: str) -> Tuple[str, str]:
    """
    Persist an uploaded file under ``legacy_individual_uploads/{batch_uuid}/``.

    Returns ``(stored_filename, absolute_path)``.
    """
    _ensure_upload_dir()
    batch_dir = os.path.join(_LEGACY_UPLOAD_DIR, batch_uuid)
    os.makedirs(batch_dir, exist_ok=True)
    safe_name = os.path.basename(uploaded_file.name)
    stored = f"{role}__{safe_name}"
    target = os.path.join(batch_dir, stored)
    with open(target, 'wb') as fh:
        for chunk in uploaded_file.chunks():
            fh.write(chunk)
    return stored, target


class LegacyImportBatchService:
    """Create + finalize batches; trigger the workflow."""

    def __init__(self, user):
        self.user = user

    @transaction.atomic
    def create_from_files(self, household_file, member_file, code: Optional[str] = None) -> LegacyImportBatch:
        batch = LegacyImportBatch(
            code=code or '',
            source_system='PSSN',
            household_file_name=os.path.basename(household_file.name),
            member_file_name=os.path.basename(member_file.name),
            status=LegacyImportBatch.Status.PENDING,
            json_ext={},
        )
        batch.save(user=self.user)

        if LegacyIndividualConfig.legacy_preserve_uploaded_file:
            household_stored, household_path = _save_uploaded_file(
                household_file, str(batch.id), 'household'
            )
            member_stored, member_path = _save_uploaded_file(
                member_file, str(batch.id), 'member'
            )
            batch.json_ext = {
                **(batch.json_ext or {}),
                'files': {
                    'household': {
                        'original_name': household_file.name,
                        'stored_name': household_stored,
                        'path': household_path,
                    },
                    'member': {
                        'original_name': member_file.name,
                        'stored_name': member_stored,
                        'path': member_path,
                    },
                },
            }
            batch.save(user=self.user)
        return batch

    def mark_in_progress(self, batch: LegacyImportBatch):
        batch.status = LegacyImportBatch.Status.IN_PROGRESS
        batch.started_at = timezone.now()
        batch.save(user=self.user)

    def finalize(
        self,
        batch: LegacyImportBatch,
        *,
        total_households: int,
        total_members: int,
        success_household_count: int,
        success_member_count: int,
        warning_count: int,
        error_count: int,
        errors: dict,
    ):
        batch.total_households = total_households
        batch.total_members = total_members
        batch.success_household_count = success_household_count
        batch.success_member_count = success_member_count
        batch.warning_count = warning_count
        batch.error_count = error_count
        batch.error = errors or {}

        if error_count and not (success_household_count or success_member_count):
            batch.status = LegacyImportBatch.Status.FAIL
        elif error_count or warning_count:
            batch.status = LegacyImportBatch.Status.COMPLETED_WITH_ERRORS
        else:
            batch.status = LegacyImportBatch.Status.SUCCESS

        batch.finished_at = timezone.now()
        batch.save(user=self.user)

    def fail(self, batch: LegacyImportBatch, reason: str, detail: Optional[dict] = None):
        batch.status = LegacyImportBatch.Status.FAIL
        batch.finished_at = timezone.now()
        err = batch.error or {}
        err.setdefault('errors', {})
        err['errors']['fatal'] = {'reason': reason, 'detail': detail or {}}
        batch.error = err
        batch.save(user=self.user)


# ---------------------------------------------------------------------------
# Read helpers (thin — most filtering happens in GraphQL)
# ---------------------------------------------------------------------------


class LegacyIndividualService:
    def __init__(self, user):
        self.user = user

    @staticmethod
    def base_queryset():
        return LegacyIndividual.objects.filter(is_deleted=False)


class LegacyGroupService:
    def __init__(self, user):
        self.user = user

    @staticmethod
    def base_queryset():
        return LegacyGroup.objects.filter(is_deleted=False)
