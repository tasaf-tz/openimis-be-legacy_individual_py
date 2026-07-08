"""
Tests for the legacy PSSN API pull path.

Two layers:

- ``SimpleTestCase`` unit tests (no DB): the HH_/MEMBER_ un-prefix rule, the
  adapter split/dedupe/null-normalization, and the source's pagination + error
  handling against a fake HTTP session.
- ``TestCase`` integration test (needs the openIMIS PostgreSQL fixture, like
  ``test_pssn_workflow``): ``LegacyApiImportService`` end-to-end with a mocked
  source, proving the ``replace`` re-import strategy supersedes prior API
  batches (and clears the global NIN unique index so a re-pull doesn't fail).
"""

import shutil
import tempfile
from unittest import mock, skipIf

from django.db import connection
from django.test import SimpleTestCase, TestCase

from legacy_individual.adapters.pssn_api_adapter import LegacyPssnApiAdapter
from legacy_individual.columns import to_household_column, to_member_column
from legacy_individual.sources.pssn_api_source import LegacyPssnApiSource


SAMPLE_ROWS = [
    {
        "HH_REGISTRATIONNO": "07030720127146", "HH_UNIQUENO": "4945236",
        "HH_REGION_CODE": "07", "HH_DISTRICT_CODE": "0703",
        "HH_WARD_CODE": "0703072", "HH_VILLAGE_CODE": "070307201",
        "HH_FIRSTNAME": "MARIA", "HH_MIDDLENAME": "PAULO", "HH_LASTNAME": "MSHAUZI",
        "HH_AGE": "47", "HH_DOB": "1974-12-04 00:00:00",
        "HH_HHSTATUS": "5", "HH_HHSIZE": "8", "HH_PMTSCORE": "11.371333",
        "HH_PHONE_NO": "0742348236", "HH_BANK_ACCOUNT": None, "HH_AREA_CODE": None,
        "MEMBER_UNIQUENO": "25426968", "MEMBER_MEMBERLINENO": "1",
        "MEMBER_FIRSTNAME": "Seleman ", "MEMBER_MIDDLENAME": "Ahmad ",
        "MEMBER_LASTNAME": "Mpelo", "MEMBER_SEX": "1",
        "MEMBER_REGISTRATIONNO": "07030720127146",
        "MEMBER_RELATIONSHIPTOHEAD": "1", "MEMBER_HH_REP": "1",
        "MEMBER_DATEOFBIRTH": None, "MEMBER_NIDA_NIN": None,
    },
    {
        "HH_REGISTRATIONNO": "07030720127146", "HH_FIRSTNAME": "MARIA",
        "HH_LASTNAME": "MSHAUZI", "HH_VILLAGE_CODE": "070307201",
        "MEMBER_MEMBERLINENO": "2", "MEMBER_FIRSTNAME": "Juma",
        "MEMBER_LASTNAME": "Mpelo", "MEMBER_SEX": "1",
        "MEMBER_REGISTRATIONNO": "07030720127146",
        "MEMBER_RELATIONSHIPTOHEAD": "3", "MEMBER_HH_REP": "0",
        "MEMBER_NIDA_NIN": "19700101-11111-00001-11",
    },
    {
        "HH_REGISTRATIONNO": "07030720127999", "HH_FIRSTNAME": "JOHN",
        "HH_LASTNAME": "DOE", "HH_VILLAGE_CODE": "070307202",
        "MEMBER_MEMBERLINENO": "1", "MEMBER_FIRSTNAME": "John",
        "MEMBER_LASTNAME": "Doe", "MEMBER_SEX": "1",
        "MEMBER_REGISTRATIONNO": "07030720127999",
        "MEMBER_RELATIONSHIPTOHEAD": "1", "MEMBER_HH_REP": "1",
    },
]


class PrefixRuleTests(SimpleTestCase):
    def test_household_prefix(self):
        self.assertEqual(to_household_column("HH_REGISTRATIONNO"), "REGISTRATIONNO")
        self.assertEqual(to_household_column("HH_HHSTATUS"), "HHSTATUS")

    def test_household_already_prefixed_not_double_stripped(self):
        self.assertEqual(to_household_column("HH_FIRSTNAME"), "HH_FIRSTNAME")
        self.assertEqual(to_household_column("HH_MIDDLENAME"), "HH_MIDDLENAME")

    def test_member_prefix(self):
        self.assertEqual(to_member_column("MEMBER_MEMBERLINENO"), "MEMBERLINENO")
        self.assertEqual(to_member_column("MEMBER_HH_REP"), "HH_REP")
        self.assertEqual(to_member_column("MEMBER_HH_MEMBER_STATUS"), "HH_MEMBER_STATUS")

    def test_cross_and_unknown_return_none(self):
        self.assertIsNone(to_household_column("MEMBER_FIRSTNAME"))
        self.assertIsNone(to_member_column("HH_FIRSTNAME"))
        self.assertIsNone(to_household_column("HH_TOTALLY_UNKNOWN"))
        self.assertIsNone(to_member_column("MEMBER_TOTALLY_UNKNOWN"))
        self.assertIsNone(to_household_column("success"))


class AdapterSplitTests(SimpleTestCase):
    def test_split_dedupes_and_normalizes(self):
        hh_df, mem_df = LegacyPssnApiAdapter().split(SAMPLE_ROWS)

        self.assertEqual(hh_df.shape[0], 2)
        self.assertEqual(mem_df.shape[0], 3)

        self.assertIn("REGISTRATIONNO", hh_df.columns)
        self.assertIn("HH_FIRSTNAME", hh_df.columns)
        self.assertIn("MEMBERLINENO", mem_df.columns)
        self.assertIn("HH_REP", mem_df.columns)

        self.assertEqual(set(hh_df["BANK_ACCOUNT"].tolist()), {""})
        self.assertTrue(all(str(dt) == "object" for dt in hh_df.dtypes))

    def test_split_empty(self):
        hh_df, mem_df = LegacyPssnApiAdapter().split([])
        self.assertTrue(hh_df.empty)
        self.assertTrue(mem_df.empty)




class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        page = (params or {}).get("page")
        return self.pages[page]


def _row(regno, line):
    return {
        "HH_REGISTRATIONNO": regno, "HH_FIRSTNAME": "X", "HH_LASTNAME": "Y",
        "MEMBER_REGISTRATIONNO": regno, "MEMBER_MEMBERLINENO": str(line),
        "MEMBER_FIRSTNAME": "A", "MEMBER_LASTNAME": "B",
    }


_CFG = {
    "legacy_api_base_url": "http://legacy.test",
    "legacy_api_path": "/etlapi/combined.php",
    "legacy_api_page_size": 2,
    "legacy_api_max_pages": 10,
    "legacy_api_connect_timeout": 1,
    "legacy_api_read_timeout": 1,
    "legacy_api_retries": 0,
    "legacy_api_auth_type": "none",
}


class SourcePaginationTests(SimpleTestCase):
    def test_pages_until_short_page(self):
        pages = {
            1: _Resp(200, {"success": True, "per_page": 2, "records_returned": 2,
                           "data": [_row("a", 1), _row("a", 2)]}),
            2: _Resp(200, {"success": True, "per_page": 2, "records_returned": 1,
                           "data": [_row("b", 1)]}),
        }
        session = _Session(pages)
        src = LegacyPssnApiSource(config=_CFG, session=session)
        rows = list(src.pull("0703"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["district_code"], "0703")
        self.assertEqual(session.calls[0]["page"], 1)

    def test_http_error_raises(self):
        session = _Session({1: _Resp(500, None)})
        src = LegacyPssnApiSource(config=_CFG, session=session)
        with self.assertRaises(LegacyPssnApiSource.Error):
            list(src.pull("0703"))

    def test_success_false_raises(self):
        session = _Session({1: _Resp(200, {"success": False, "message": "bad district"})})
        src = LegacyPssnApiSource(config=_CFG, session=session)
        with self.assertRaises(LegacyPssnApiSource.Error):
            list(src.pull("0703"))

    def test_non_json_raises(self):
        session = _Session({1: _Resp(200, None)})
        src = LegacyPssnApiSource(config=_CFG, session=session)
        with self.assertRaises(LegacyPssnApiSource.Error):
            list(src.pull("0703"))

    def test_missing_district_raises(self):
        src = LegacyPssnApiSource(config=_CFG, session=_Session({}))
        with self.assertRaises(LegacyPssnApiSource.Error):
            list(src.pull(""))




@skipIf(
    connection.vendor != 'postgresql',
    'Suite assumes the openIMIS PostgreSQL fixture (users, locations, etc.).',
)
class LegacyApiImportServiceTest(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmpdir = tempfile.mkdtemp(prefix='legacy_api_test_')
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
        from core.test_helpers import create_test_interactive_user
        self.user = create_test_interactive_user(username='admin_legacy_api_test')

    def _run_import(self, district_code, rows, **kwargs):
        from legacy_individual.services import LegacyApiImportService

        fake_source = mock.MagicMock()
        fake_source.url = "http://legacy.test/etlapi/combined.php"
        fake_source.pull.side_effect = lambda dc: iter(list(rows))
        with mock.patch(
            "legacy_individual.sources.pssn_api_source.LegacyPssnApiSource",
            return_value=fake_source,
        ):
            return LegacyApiImportService(self.user).run(district_code, **kwargs)

    def test_import_and_reimport_replace(self):
        from legacy_individual.models import (
            LegacyGroup, LegacyImportBatch, LegacyIndividual,
        )

        result1 = self._run_import("0703", SAMPLE_ROWS, paa_name="TEST DC")
        batch1_id = result1["batch_id"]
        self.assertEqual(result1["raw_rows"], 3)
        self.assertEqual(
            LegacyGroup.objects.filter(
                import_batch_id=batch1_id, is_deleted=False
            ).count(),
            2,
        )
        self.assertEqual(
            LegacyIndividual.objects.filter(
                import_batch_id=batch1_id, is_deleted=False
            ).count(),
            3,
        )

        result2 = self._run_import("0703", SAMPLE_ROWS, paa_name="TEST DC")
        batch2_id = result2["batch_id"]
        self.assertNotEqual(batch1_id, batch2_id)
        self.assertIn(batch1_id, result2["replaces"])

        self.assertEqual(
            LegacyGroup.objects.filter(
                import_batch_id=batch1_id, is_deleted=False
            ).count(),
            0,
        )
        self.assertEqual(
            LegacyGroup.objects.filter(
                import_batch_id=batch2_id, is_deleted=False
            ).count(),
            2,
        )
        self.assertEqual(
            LegacyGroup.objects.filter(code__isnull=False, is_deleted=False)
            .exclude(import_batch_id=batch2_id)
            .filter(import_batch__code="0703").count(),
            0,
        )

        batch1 = LegacyImportBatch.objects.get(id=batch1_id)
        self.assertEqual(batch1.json_ext.get("superseded_by"), batch2_id)

    def test_empty_district_is_empty_success(self):
        from legacy_individual.models import LegacyImportBatch

        result = self._run_import("9999", [])
        batch = LegacyImportBatch.objects.get(id=result["batch_id"])
        self.assertEqual(batch.status, LegacyImportBatch.Status.SUCCESS)
        self.assertEqual(batch.total_households, 0)
        self.assertEqual(batch.total_members, 0)

    def test_never_writes_to_individual_tables(self):
        from individual.models import Individual

        before = Individual.objects.count()
        self._run_import("0703", SAMPLE_ROWS)
        self.assertEqual(Individual.objects.count(), before)
