"""
Integration tests for the legacy_individual paired-PSSN workflow.

Prerequisite: the test database must be seeded with the openIMIS legacy
tables (``tblUsers``, ``tblLocations``, etc.). Run
``openIMIS/init_test_db.py`` after the test DB is created. This mirrors
the existing openIMIS module test pattern; standalone ``manage.py test``
without that seed will fail with ``relation "tblUsers" does not exist``.

These tests use synthetic CSV fixtures (built inline, no on-disk
dependency). They confirm:

- happy path: paired files with matching REGISTRATIONNOs → 2 households +
  4 members written, batch SUCCESS
- members with no matching household → COMPLETED_WITH_ERRORS, member rows
  not written
- the workflow never writes to ``individual_individual`` /
  ``individual_group``
- gender, disability, role, NIN, premno, dob propagate as designed
"""

import os
import shutil
import tempfile
from io import BytesIO

from django.db import connection
from django.test import TestCase
from unittest import skipIf

from core.test_helpers import create_test_interactive_user

from legacy_individual.models import (
    LegacyGroup,
    LegacyGroupIndividual,
    LegacyImportBatch,
    LegacyIndividual,
)
from legacy_individual.services import LegacyImportBatchService
from legacy_individual.workflows.pssn_legacy_upload import (
    process_legacy_pssn_upload,
)


HOUSEHOLD_HEADER = (
    'REGISTRATIONNO,UNIQUENO,WAVENO,REGION_CODE,DISTRICT_CODE,WARD_CODE,VILLAGE_CODE,'
    'HH_FIRSTNAME,HH_MIDDLENAME,HH_LASTNAME,AGE,DOB,POPULAR_HH_NAME,HHSTATUS,HHSIZE,'
    'PMTSCORE,HHCLASSIFICATION,PHONE_NO\n'
)

MEMBER_HEADER = (
    'UNIQUENO,MEMBERLINENO,FIRSTNAME,MIDDLENAME,LASTNAME,SEX,AGE,REGISTRATIONNO,'
    'RELATIONSHIPTOHEAD,HH_REP,DATEOFBIRTH,DISABILITY,FACILITY_CODE,FACILITY_NAME,'
    'NIDA_NIN,PREM_NO\n'
)


class _UploadStub:
    """Minimal stand-in for an InMemoryUploadedFile."""

    def __init__(self, name, content_bytes):
        self.name = name
        self._buf = BytesIO(content_bytes)

    def chunks(self):
        self._buf.seek(0)
        while True:
            chunk = self._buf.read(8192)
            if not chunk:
                break
            yield chunk


def _build_household_csv(rows):
    body = ''.join(rows)
    return (HOUSEHOLD_HEADER + body).encode('utf-8')


def _build_member_csv(rows):
    body = ''.join(rows)
    return (MEMBER_HEADER + body).encode('utf-8')


@skipIf(
    connection.vendor != 'postgresql',
    'Suite assumes the openIMIS PostgreSQL fixture (locations, etc.).',
)
class PssnPairedWorkflowTest(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmpdir = tempfile.mkdtemp(prefix='legacy_individual_test_')
        # Redirect upload dir to a sandbox so tests don't pollute the project.
        from legacy_individual import services
        cls._orig_upload_dir = services._LEGACY_UPLOAD_DIR
        services._LEGACY_UPLOAD_DIR = cls._tmpdir

    @classmethod
    def tearDownClass(cls):
        from legacy_individual import services
        services._LEGACY_UPLOAD_DIR = cls._orig_upload_dir
        shutil.rmtree(cls._tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = create_test_interactive_user(username='admin_legacy_test')

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------
    def test_paired_happy_path(self):
        household_rows = [
            '02040210000001,1001,0,02,0204,0204021,020402101,'
            'Asha,Juma,Mwangi,42,1982-01-15 00:00:00.000,Asha Mwangi,5,4,11.20,70PCT,0712345678\n',
            '02040210000002,1002,0,02,0204,0204021,020402101,'
            'Hassan,Ally,Bakari,55,1969-04-02 00:00:00.000,Hassan Bakari,5,3,12.50,80PCT,0789999999\n',
        ]
        member_rows = [
            # household 1 — head, spouse, son
            '2001,1,Asha,Juma,Mwangi,2,42,02040210000001,1,1,1982-01-15 00:00:00.000,0,,,,\n',
            '2002,2,Tariq,Hassan,Mwangi,1,45,02040210000001,2,0,1979-08-20 00:00:00.000,0,,,,\n',
            '2003,3,Khalid,Tariq,Mwangi,1,12,02040210000001,3,0,2012-03-30 00:00:00.000,0,,,,'
            '19120330-12345-00001-99,PR-001\n',
            # household 2 — head only
            '2004,1,Hassan,Ally,Bakari,1,55,02040210000002,1,1,1969-04-02 00:00:00.000,1,,,,'
            '19690402-12345-00002-77,PR-002\n',
        ]
        batch = self._run(_build_household_csv(household_rows),
                          _build_member_csv(member_rows))

        self.assertEqual(batch.status, LegacyImportBatch.Status.SUCCESS)
        self.assertEqual(batch.success_household_count, 2)
        self.assertEqual(batch.success_member_count, 4)
        self.assertEqual(batch.error_count, 0)

        self.assertEqual(LegacyGroup.objects.filter(import_batch=batch).count(), 2)
        self.assertEqual(LegacyIndividual.objects.filter(import_batch=batch).count(), 4)
        self.assertEqual(
            LegacyGroupIndividual.objects.filter(group__import_batch=batch).count(),
            4,
        )

        # Spot-check role + gender mapping
        khalid = LegacyIndividual.objects.get(legacy_code='02040210000001-3')
        self.assertEqual(khalid.first_name, 'Khalid')
        self.assertEqual(khalid.gender, 'M')
        self.assertEqual(khalid.nin, '19120330-12345-00001-99')
        self.assertEqual(khalid.premno, 'PR-001')
        self.assertEqual(khalid.disability, False)
        self.assertEqual(khalid.dob.isoformat(), '2012-03-30')

        # khalid's RELATIONSHIPTOHEAD=3, SEX=1 → SON
        membership = LegacyGroupIndividual.objects.get(individual=khalid)
        self.assertEqual(membership.role, LegacyGroupIndividual.Role.SON)
        self.assertEqual(membership.relationship_code, '3')
        self.assertEqual(membership.member_line, 3)
        self.assertIsNone(membership.recipient_type)

        # Hassan (HH_REP=1) gets the household phone.
        hassan = LegacyIndividual.objects.get(legacy_code='02040210000002-1')
        self.assertEqual(hassan.phone_no, '0789999999')
        self.assertEqual(hassan.disability, True)

    # ------------------------------------------------------------------
    # Mismatched REGISTRATIONNO — members rejected, batch partial
    # ------------------------------------------------------------------
    def test_mismatched_registration_no(self):
        household_rows = [
            '02040210000010,1010,0,02,0204,0204021,020402101,'
            'Maria,J,Lema,30,1995-05-05 00:00:00.000,Maria Lema,5,2,9.50,40PCT,\n',
        ]
        member_rows = [
            # Wrong REGISTRATIONNO — should be rejected
            '2010,1,Maria,J,Lema,2,30,02040210000099,1,1,1995-05-05 00:00:00.000,0,,,,\n',
        ]
        batch = self._run(_build_household_csv(household_rows),
                          _build_member_csv(member_rows))

        self.assertEqual(batch.status, LegacyImportBatch.Status.COMPLETED_WITH_ERRORS)
        self.assertEqual(batch.success_household_count, 1)
        self.assertEqual(batch.success_member_count, 0)
        self.assertGreaterEqual(batch.error_count, 1)
        self.assertEqual(LegacyIndividual.objects.filter(import_batch=batch).count(), 0)

    # ------------------------------------------------------------------
    # Boundary: legacy module never writes to live tables
    # ------------------------------------------------------------------
    def test_no_writes_to_live_individual_tables(self):
        from individual.models import Individual, Group as LiveGroup, GroupIndividual as LiveGI
        before_ind = Individual.objects.count()
        before_grp = LiveGroup.objects.count()
        before_gi = LiveGI.objects.count()

        household_rows = [
            '02040210000020,1020,0,02,0204,0204021,020402101,'
            'Sara,K,Mwema,28,1997-07-07 00:00:00.000,Sara Mwema,5,2,10.00,50PCT,\n',
        ]
        member_rows = [
            '2020,1,Sara,K,Mwema,2,28,02040210000020,1,1,1997-07-07 00:00:00.000,,,,,\n',
        ]
        self._run(_build_household_csv(household_rows),
                  _build_member_csv(member_rows))

        self.assertEqual(Individual.objects.count(), before_ind)
        self.assertEqual(LiveGroup.objects.count(), before_grp)
        self.assertEqual(LiveGI.objects.count(), before_gi)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _run(self, household_bytes, member_bytes) -> LegacyImportBatch:
        hh = _UploadStub('PSSN_ENROLLED_HOUSEHOLD_test.csv', household_bytes)
        mb = _UploadStub('PSSN_ENROLLMENT_HH_MEMBER_test.csv', member_bytes)
        service = LegacyImportBatchService(self.user)
        batch = service.create_from_files(hh, mb, code='UT')
        process_legacy_pssn_upload(str(self.user.id), str(batch.id))
        batch.refresh_from_db()
        return batch
