"""RM4 archive: mirror columns, archive + verify, re-run refresh, clear-down."""
from datetime import date

from django.db import connection
from django.test import SimpleTestCase, TestCase

from legacy_individual import rm4_archive
from legacy_individual.models import (
    LegacyImportBatch, Rm4Group, Rm4GroupIndividual, Rm4Individual,
)


def _columns(model):
    return {f.column for f in model._meta.concrete_fields}


class MirrorColumnsTest(SimpleTestCase):
    def test_rm4_tables_mirror_the_individual_tables(self):
        from individual.models import Group, GroupIndividual, Individual

        extra = {'archive_batch_id'}
        self.assertEqual(_columns(Rm4Group), _columns(Group) | extra)
        self.assertEqual(_columns(Rm4Individual), (_columns(Individual) - {'tmp_pmt_poor'}) | extra)
        self.assertEqual(_columns(Rm4GroupIndividual), _columns(GroupIndividual) | extra)

    def test_copy_statements_use_every_mirrored_column(self):
        for kind, model in (('groups', Rm4Group), ('individuals', Rm4Individual), ('links', Rm4GroupIndividual)):
            copied = {c.strip('"') for c in rm4_archive.TABLES[kind][2]}
            self.assertEqual(copied | {'archive_batch_id'}, _columns(model), kind)


class Rm4Fixtures:
    """Two RM4 households in two districts and one non-RM4 household; the clone's own RM4 is out of scope."""

    @classmethod
    def setUpTestData(cls):
        from core.models import User
        from location.models import Location

        cls.user = User.objects.filter(username='Admin').first() or User.objects.order_by('id').first()
        villages = (Location.objects.filter(type='V', validity_to__isnull=True, parent__parent__type='D')
                    .select_related('parent__parent').order_by('id'))
        first = villages.first()
        cls.village_a = first
        cls.village_b = villages.exclude(parent__parent=first.parent.parent).first()

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE individual_group SET code = 'X3' || substr(code, 3) WHERE code LIKE 'P3-%%'")
            cursor.execute("""UPDATE individual_individual SET "Json_ext" = "Json_ext" - 'external_id'
                              WHERE "Json_ext" ->> 'external_id' LIKE 'P3-%%'""")
        self.hh_a = self._household('P3-000000001-00000001', self.village_a, ['ASHA', 'JUMA'])
        self.hh_b = self._household('P3-000000002-00000002', self.village_b, ['NEEMA'])
        self.other = self._household('NSR-0001', self.village_a, ['BARAKA'])

    def _household(self, code, village, names):
        from individual.models import Group, GroupIndividual, Individual

        group = Group(code=code, location=village, json_ext={'interview_key': code[-8:], 'pmt_score': 9.5})
        group.save(user=self.user)
        members = []
        for index, name in enumerate(names):
            person = Individual(first_name=name, last_name='TEST', dob=date(1990, 1, 1), location=village,
                                json_ext={'external_id': f'{code}-{index}'})
            person.save(user=self.user)
            GroupIndividual(group=group, individual=person, role='HEAD' if index == 0 else 'SON').save(user=self.user)
            members.append(person)
        return group, members


class Rm4ArchiveTest(Rm4Fixtures, TestCase):
    def test_archive_copies_every_row_and_verifies(self):
        totals = rm4_archive.archive(self.user, emit=lambda *_: None)
        self.assertEqual(totals, {'groups': 2, 'individuals': 3, 'links': 3})

        archived = Rm4Group.objects.get(id=self.hh_a[0].id)
        self.assertEqual((archived.code, archived.location_id), (self.hh_a[0].code, self.village_a.id))
        self.hh_a[0].refresh_from_db()
        self.assertEqual(archived.json_ext, self.hh_a[0].json_ext)
        self.assertFalse(Rm4Group.objects.filter(code='NSR-0001').exists())
        person = Rm4Individual.objects.get(id=self.hh_a[1][1].id)
        self.assertEqual((person.first_name, person.dob), ('JUMA', date(1990, 1, 1)))
        self.assertEqual(Rm4GroupIndividual.objects.get(individual=person).role, 'SON')

        batches = LegacyImportBatch.objects.filter(source_system='RM4')
        self.assertEqual(batches.count(), 2)
        batch_a = batches.get(district=self.village_a.parent.parent)
        self.assertEqual((batch_a.total_households, batch_a.total_members, batch_a.status), (1, 2, 'SUCCESS'))
        self.assertTrue(rm4_archive.verify()['ok'])

    def test_rerun_refreshes_rows_changed_after_the_archive(self):
        rm4_archive.archive(self.user, emit=lambda *_: None)
        group = self.hh_a[0]
        with connection.cursor() as cursor:
            cursor.execute("""UPDATE individual_group SET "Json_ext" = "Json_ext" || '{"pmt_score": 3}'
                              WHERE "UUID" = %s""", [group.id])
        report = rm4_archive.verify()
        self.assertFalse(report['ok'])
        self.assertEqual(report['groups']['different'], 1)

        totals = rm4_archive.archive(self.user, emit=lambda *_: None)
        self.assertEqual(totals['groups'], 1)
        self.assertTrue(rm4_archive.verify()['ok'])
        self.assertEqual(Rm4Group.objects.get(id=group.id).json_ext['pmt_score'], 3)

    def test_clear_refuses_until_verified(self):
        with self.assertRaises(rm4_archive.ArchiveNotVerified):
            rm4_archive.clear_live(confirm=True, emit=lambda *_: None)

    def test_dry_run_counts_and_keeps_everything(self):
        rm4_archive.archive(self.user, emit=lambda *_: None)
        result = rm4_archive.clear_live(confirm=False, emit=lambda *_: None)
        self.assertEqual((result['steps']['households'], result['steps']['members']), (2, 3))
        self.assertEqual(result['live_rm4_households_left'], 0)
        from individual.models import Group
        self.assertEqual(Group.objects.filter(code__startswith='P3-').count(), 2)

    def test_confirmed_clear_removes_rm4_and_its_test_data_only(self):
        from individual.models import Group, GroupIndividual, Individual

        shared = self.hh_a[1][0]
        GroupIndividual(group=self.other[0], individual=shared, role='SON').save(user=self.user)
        ticket, payment_account = self._attach_ticket_and_payment_account()
        rm4_archive.archive(self.user, emit=lambda *_: None)

        result = rm4_archive.clear_live(confirm=True, emit=lambda *_: None)

        self.assertEqual(result['live_rm4_households_left'], 0)
        self.assertFalse(Group.objects.filter(code__startswith='P3-').exists())
        self.assertTrue(Group.objects.filter(id=self.other[0].id).exists())
        self.assertEqual(list(GroupIndividual.objects.filter(individual=shared).values_list('group_id', flat=True)),
                         [self.other[0].id])
        self.assertFalse(Individual.objects.filter(id=self.hh_a[1][1].id).exists())
        self.assertTrue(Rm4Individual.objects.filter(id=self.hh_a[1][1].id).exists())
        with connection.cursor() as cursor:
            if ticket:
                cursor.execute("""SELECT ct.model FROM grievance_social_protection_ticket t
                                  JOIN django_content_type ct ON ct.id = t.reporter_type_id WHERE t."UUID" = %s""",
                               [ticket])
                self.assertEqual(cursor.fetchone()[0], 'rm4group')
            if payment_account:
                cursor.execute('SELECT count(*) FROM "tasaf_PaymentAccount" WHERE "UUID" = %s', [payment_account])
                self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute('SELECT count(*) FROM individual_historicalgroup WHERE "UUID" = %s', [self.hh_a[0].id])
            self.assertEqual(cursor.fetchone()[0], 0)

    def _attach_ticket_and_payment_account(self):
        """Point an existing grievance ticket and an enrolled household (with its payment chain) at RM4."""
        group = self.hh_a[0]
        with connection.cursor() as cursor:
            cursor.execute("""UPDATE grievance_social_protection_ticket SET reporter_id = %s,
                                reporter_type_id = (SELECT id FROM django_content_type
                                                    WHERE app_label = 'individual' AND model = 'group')
                              WHERE "UUID" = (SELECT "UUID" FROM grievance_social_protection_ticket LIMIT 1)
                              RETURNING "UUID" """, [str(group.id)])
            ticket = (cursor.fetchone() or [None])[0]
            cursor.execute("""UPDATE social_protection_groupbeneficiary gb SET group_id = %s
                              WHERE gb."UUID" = (SELECT a.group_beneficiary_id FROM "tasaf_PaymentAccount" a
                                                 JOIN "tasaf_PaylistItem" i ON i.payment_account_id = a."UUID"
                                                 LIMIT 1)
                              RETURNING (SELECT a."UUID" FROM "tasaf_PaymentAccount" a
                                         WHERE a.group_beneficiary_id = gb."UUID" LIMIT 1)""", [group.id])
            account = (cursor.fetchone() or [None])[0]
        return ticket, account
