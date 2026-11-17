"""RM4 archive: copy live P3- households into the Rm4* tables, verify the copy, clear them from the live register."""
import logging
from contextlib import nullcontext

from django.db import connection, transaction
from django.utils import timezone

from legacy_individual.models import LegacyImportBatch

logger = logging.getLogger(__name__)

SOURCE_SYSTEM = 'RM4'
UNPLACED = 'UNPLACED'

_BASE = ['"UUID"', '"isDeleted"', '"Json_ext"', '"DateCreated"', '"DateUpdated"', 'version',
         '"UserCreatedUUID"', '"UserUpdatedUUID"']
TABLES = {
    'groups': ('individual_group', 'legacy_individual_rm4group', _BASE + ['code', 'location_id']),
    'individuals': ('individual_individual', 'legacy_individual_rm4individual',
                    _BASE + ['first_name', 'last_name', 'dob', 'location_id']),
    'links': ('individual_groupindividual', 'legacy_individual_rm4groupindividual',
              _BASE + ['group_id', 'individual_id', 'role', 'recipient_type', 'is_active']),
}

_DISTRICT = """CASE WHEN l."LocationType" = 'D' THEN l."LocationId"
                    WHEN p."LocationType" = 'D' THEN p."LocationId"
                    WHEN pp."LocationType" = 'D' THEN pp."LocationId" END"""
_GROUP_DISTRICT_JOINS = """
    LEFT JOIN "tblLocations" l ON l."LocationId" = g.location_id
    LEFT JOIN "tblLocations" p ON p."LocationId" = l."ParentLocationId"
    LEFT JOIN "tblLocations" pp ON pp."LocationId" = p."ParentLocationId" """

SOURCE_GROUPS = "SELECT \"UUID\" FROM individual_group WHERE code LIKE 'P3-%%'"
SOURCE_LINKS = f"SELECT \"UUID\" FROM individual_groupindividual WHERE group_id IN ({SOURCE_GROUPS})"
UNLINKED_INDIVIDUALS = """SELECT i."UUID" FROM individual_individual i
    WHERE i."Json_ext" ->> 'external_id' LIKE 'P3-%%'
      AND NOT EXISTS (SELECT 1 FROM individual_groupindividual x WHERE x.individual_id = i."UUID")"""
SOURCE_INDIVIDUALS = f"""SELECT individual_id FROM individual_groupindividual WHERE group_id IN ({SOURCE_GROUPS})
    UNION {UNLINKED_INDIVIDUALS}"""
SOURCE_IDS = {'groups': SOURCE_GROUPS, 'individuals': SOURCE_INDIVIDUALS, 'links': SOURCE_LINKS}


def _cols(columns, alias=''):
    return ', '.join(f'{alias}{c}' for c in columns)


def _upsert(kind, select_ids):
    """Copy the live rows whose UUID is in ``select_ids``; re-runs refresh rows that changed since."""
    source, target, columns = TABLES[kind]
    changed = ' OR '.join(f't.{c} IS DISTINCT FROM EXCLUDED.{c}' for c in columns[1:])
    return f"""
        INSERT INTO {target} AS t ({_cols(columns)}, archive_batch_id)
        SELECT {_cols(columns, 's.')}, %(batch)s FROM {source} s WHERE s."UUID" IN ({select_ids})
        ON CONFLICT ("UUID") DO UPDATE SET ({_cols(columns[1:])}) = ({_cols(columns[1:], 'EXCLUDED.')})
        WHERE {changed}"""


def _scope_groups():
    return f"""SELECT g."UUID" FROM individual_group g {_GROUP_DISTRICT_JOINS}
               WHERE g.code LIKE 'P3-%%' AND ({_DISTRICT}) IS NOT DISTINCT FROM %(district)s"""


def _archive_statements(unplaced):
    groups = _scope_groups()
    individuals = f"SELECT individual_id FROM individual_groupindividual WHERE group_id IN ({groups})"
    if unplaced:
        individuals += f" UNION {UNLINKED_INDIVIDUALS}"
    links = f'SELECT "UUID" FROM individual_groupindividual WHERE group_id IN ({groups})'
    return [('groups', _upsert('groups', groups)),
            ('individuals', _upsert('individuals', individuals)),
            ('links', _upsert('links', links))]


def districts():
    """[(district_id or None, live RM4 households)] — None holds households without a district."""
    with connection.cursor() as cursor:
        cursor.execute(f"""SELECT {_DISTRICT} AS district, count(*) FROM individual_group g {_GROUP_DISTRICT_JOINS}
                           WHERE g.code LIKE 'P3-%%' GROUP BY 1 ORDER BY 2 DESC""")
        rows = cursor.fetchall()
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM ({UNLINKED_INDIVIDUALS}) t")
        unlinked = cursor.fetchone()[0]
    if unlinked and all(district is not None for district, _ in rows):
        rows.append((None, 0))
    return rows


def _batch(district_id, user):
    from location.models import Location

    district = Location.objects.filter(id=district_id).select_related('parent').first() if district_id else None
    code = f"RM4-{district.code if district else UNPLACED}"
    batch = LegacyImportBatch.objects.filter(source_system=SOURCE_SYSTEM, code=code, is_deleted=False).first()
    if batch is None:
        batch = LegacyImportBatch(source_system=SOURCE_SYSTEM, code=code, district=district,
                                  region=district.parent if district else None)
    batch.status = LegacyImportBatch.Status.IN_PROGRESS
    batch.started_at = timezone.now()
    batch.save(user=user)
    return batch


def _finish(batch, copied, user):
    with connection.cursor() as cursor:
        counts = {}
        for kind, (_, target, _) in TABLES.items():
            cursor.execute(f"SELECT count(*) FROM {target} WHERE archive_batch_id = %s", [batch.id])
            counts[kind] = cursor.fetchone()[0]
    batch.total_households = batch.success_household_count = counts['groups']
    batch.total_members = batch.success_member_count = counts['individuals']
    batch.status = LegacyImportBatch.Status.SUCCESS
    batch.finished_at = timezone.now()
    batch.json_ext = {**(batch.json_ext or {}), 'links': counts['links'], 'last_run_copied': copied}
    batch.save(user=user)
    return counts


def archive(user, district_id=None, emit=logger.info):
    """Copy live RM4 into the archive, one transaction per district. Safe to re-run."""
    plan = districts()
    if district_id is not None:
        plan = [row for row in plan if row[0] == district_id]
    totals = {kind: 0 for kind in TABLES}
    for district, households in plan:
        with transaction.atomic():
            batch = _batch(district, user)
            copied = {}
            with connection.cursor() as cursor:
                for kind, sql in _archive_statements(unplaced=district is None):
                    cursor.execute(sql, {'batch': batch.id, 'district': district})
                    copied[kind] = cursor.rowcount
            counts = _finish(batch, copied, user)
        for kind in totals:
            totals[kind] += copied[kind]
        emit(f"{batch.code}: {households} live households; copied/refreshed {copied}; archive now {counts}")
    return totals


def verify():
    """Compare the live RM4 rows with the archive: every row present and identical."""
    report = {}
    with connection.cursor() as cursor:
        for kind, (source, target, columns) in TABLES.items():
            ids = SOURCE_IDS[kind]
            cursor.execute(f"SELECT count(*) FROM ({ids}) t")
            live = cursor.fetchone()[0]
            cursor.execute(f"SELECT count(*) FROM {target}")
            archived = cursor.fetchone()[0]
            cursor.execute(f"""SELECT count(*) FROM {source} s WHERE s."UUID" IN ({ids})
                               AND NOT EXISTS (SELECT 1 FROM {target} a WHERE a."UUID" = s."UUID")""")
            missing = cursor.fetchone()[0]
            differs = ' OR '.join(f's.{c} IS DISTINCT FROM a.{c}' for c in columns[1:])
            cursor.execute(f"""SELECT count(*) FROM {source} s JOIN {target} a ON a."UUID" = s."UUID"
                               WHERE s."UUID" IN ({ids}) AND ({differs})""")
            different = cursor.fetchone()[0]
            report[kind] = {'live': live, 'archived': archived, 'missing': missing, 'different': different}
    report['ok'] = all(r['missing'] == 0 and r['different'] == 0 for r in report.values())
    return report


# ---- clear-down ------------------------------------------------------------------------------------------

def _temp(name, select):
    return [f"DROP TABLE IF EXISTS {name}",
            f"CREATE TEMP TABLE {name} AS {select}",
            f"ALTER TABLE {name} ADD PRIMARY KEY (id)",
            f"ANALYZE {name}"]


def _scope_sql():
    """Live rows of one archive batch, and everything that hangs off them (test enrolment/payment/cases)."""
    sql = []
    sql += _temp('rm4_g', """SELECT g."UUID" AS id FROM individual_group g
                             JOIN legacy_individual_rm4group a ON a."UUID" = g."UUID"
                             WHERE a.archive_batch_id = %(batch)s""")
    sql += _temp('rm4_gi', 'SELECT "UUID" AS id FROM individual_groupindividual WHERE group_id IN (SELECT id FROM rm4_g)')
    # A member also in a live non-RM4 household is kept; only their RM4 membership goes.
    sql += _temp('rm4_i', """
        SELECT i."UUID" AS id FROM individual_individual i
        WHERE (i."UUID" IN (SELECT individual_id FROM individual_groupindividual WHERE group_id IN (SELECT id FROM rm4_g))
               OR i."UUID" IN (SELECT "UUID" FROM legacy_individual_rm4individual WHERE archive_batch_id = %(batch)s))
          AND EXISTS (SELECT 1 FROM legacy_individual_rm4individual a WHERE a."UUID" = i."UUID")
          AND NOT EXISTS (SELECT 1 FROM individual_groupindividual x
                          WHERE x.individual_id = i."UUID" AND x.group_id NOT IN (SELECT id FROM rm4_g))""")
    sql += _temp('rm4_gb', 'SELECT "UUID" AS id FROM social_protection_groupbeneficiary WHERE group_id IN (SELECT id FROM rm4_g)')
    sql += _temp('rm4_b', 'SELECT "UUID" AS id FROM social_protection_beneficiary WHERE individual_id IN (SELECT id FROM rm4_i)')
    sql += _temp('rm4_bc', 'SELECT "UUID" AS id FROM payroll_benefitconsumption WHERE individual_id IN (SELECT id FROM rm4_i)')
    sql += _temp('rm4_pa', """SELECT "UUID" AS id FROM "tasaf_PaymentAccount"
                              WHERE group_beneficiary_id IN (SELECT id FROM rm4_gb)""")
    sql += _temp('rm4_pli', """SELECT "UUID" AS id, paylist_id FROM "tasaf_PaylistItem"
                               WHERE benefit_consumption_id IN (SELECT id FROM rm4_bc)
                                  OR payment_account_id IN (SELECT id FROM rm4_pa)""")
    sql += _temp('rm4_pca', """SELECT "UUID" AS id FROM "case_PaymentChangeAudit"
                               WHERE group_beneficiary_id IN (SELECT id FROM rm4_gb)
                                  OR payment_account_id IN (SELECT id FROM rm4_pa)""")
    sql += _temp('rm4_gvi', 'SELECT id FROM "tasaf_GepgVerificationItem" WHERE payment_account_id IN (SELECT id FROM rm4_pa)')
    sql += _temp('rm4_task', """
        SELECT "UUID" AS id FROM tasks_management_task
        WHERE (entity_type_id = %(ct_group)s AND entity_id IN (SELECT id::text FROM rm4_g))
           OR (entity_type_id = %(ct_individual)s AND entity_id IN (SELECT id::text FROM rm4_i))
           OR (entity_type_id = %(ct_link)s AND entity_id IN (SELECT id::text FROM rm4_gi))
           OR (entity_type_id = %(ct_group_beneficiary)s AND entity_id IN (SELECT id::text FROM rm4_gb))
           OR (entity_type_id = %(ct_beneficiary)s AND entity_id IN (SELECT id::text FROM rm4_b))
           OR (entity_type_id = %(ct_benefit)s AND entity_id IN (SELECT id::text FROM rm4_bc))
           OR (entity_type_id = %(ct_account)s AND entity_id IN (SELECT id::text FROM rm4_pa))""")
    return sql


# Children first.
CLEAR_STEPS = [
    ('grievance tickets re-pointed to RM4 households',
     """UPDATE grievance_social_protection_ticket SET reporter_type_id = %(ct_rm4_group)s
        WHERE reporter_type_id = %(ct_group)s AND reporter_id IN (SELECT id::text FROM rm4_g)"""),
    ('grievance tickets re-pointed to RM4 members',
     """UPDATE grievance_social_protection_ticket SET reporter_type_id = %(ct_rm4_individual)s
        WHERE reporter_type_id = %(ct_individual)s AND reporter_id IN (SELECT id::text FROM rm4_i)"""),
    ('case follow-up remarks', """DELETE FROM "case_FollowUpRemark"
        WHERE group_id IN (SELECT id FROM rm4_g) OR paylist_item_id IN (SELECT id FROM rm4_pli)
           OR payment_change_audit_id IN (SELECT id FROM rm4_pca)"""),
    ('payment return feedback', 'DELETE FROM "tasaf_ReturnFeedback" WHERE paylist_item_id IN (SELECT id FROM rm4_pli)'),
    ('account-check rows unlinked from GePG items',
     'UPDATE "tasaf_AccountCheckRow" SET gepg_item_id = NULL WHERE gepg_item_id IN (SELECT id FROM rm4_gvi)'),
    ('GePG verification items', 'DELETE FROM "tasaf_GepgVerificationItem" WHERE id IN (SELECT id FROM rm4_gvi)'),
    ('MUSE verification records',
     'DELETE FROM "tasaf_MuseVerificationRecord" WHERE payment_account_id IN (SELECT id FROM rm4_pa)'),
    ('payment account mutations',
     'DELETE FROM "tasaf_PaymentAccountMutation" WHERE payment_account_id IN (SELECT id FROM rm4_pa)'),
    ('account verification records',
     'DELETE FROM "tasaf_VerificationRecord" WHERE payment_account_id IN (SELECT id FROM rm4_pa)'),
    ('household deactivations', """DELETE FROM "case_HouseholdDeactivation"
        WHERE group_id IN (SELECT id FROM rm4_g) OR group_beneficiary_id IN (SELECT id FROM rm4_gb)"""),
    ('member deactivations: successor unlinked', """UPDATE "case_MemberDeactivation" SET successor_group_individual_id = NULL
        WHERE successor_group_individual_id IN (SELECT id FROM rm4_gi) AND group_id NOT IN (SELECT id FROM rm4_g)"""),
    ('member deactivations', """DELETE FROM "case_MemberDeactivation"
        WHERE group_id IN (SELECT id FROM rm4_g) OR individual_id IN (SELECT id FROM rm4_i)
           OR group_individual_id IN (SELECT id FROM rm4_gi)"""),
    ('pending data updates', """DELETE FROM "case_PendingDataUpdate"
        WHERE group_id IN (SELECT id FROM rm4_g) OR task_id IN (SELECT id FROM rm4_task)"""),
    ('payment change audits', 'DELETE FROM "case_PaymentChangeAudit" WHERE "UUID" IN (SELECT id FROM rm4_pca)'),
    ('paylist items', 'DELETE FROM "tasaf_PaylistItem" WHERE "UUID" IN (SELECT id FROM rm4_pli)'),
    ('benefit attachments', 'DELETE FROM payroll_benefitattachment WHERE benefit_id IN (SELECT id FROM rm4_bc)'),
    ('payroll benefits', 'DELETE FROM payroll_payrollbenefitconsumption WHERE benefit_id IN (SELECT id FROM rm4_bc)'),
    ('benefits', 'DELETE FROM payroll_benefitconsumption WHERE "UUID" IN (SELECT id FROM rm4_bc)'),
    ('payment accounts', 'DELETE FROM "tasaf_PaymentAccount" WHERE "UUID" IN (SELECT id FROM rm4_pa)'),
    ('household beneficiaries', 'DELETE FROM social_protection_groupbeneficiary WHERE "UUID" IN (SELECT id FROM rm4_gb)'),
    ('member beneficiaries', 'DELETE FROM social_protection_beneficiary WHERE "UUID" IN (SELECT id FROM rm4_b)'),
    ('task mutations', 'DELETE FROM tasks_management_taskmutation WHERE task_id IN (SELECT id FROM rm4_task)'),
    ('tasks', 'DELETE FROM tasks_management_task WHERE "UUID" IN (SELECT id FROM rm4_task)'),
    ('activity participants unlinked (attendance kept)',
     'UPDATE communications_activityparticipant SET individual_id = NULL WHERE individual_id IN (SELECT id FROM rm4_i)'),
    ('PMT enrolments', 'DELETE FROM individual_pmtenrollment WHERE group_id IN (SELECT id FROM rm4_g)'),
    ('household upload records', 'DELETE FROM individual_groupdatasource WHERE group_id IN (SELECT id FROM rm4_g)'),
    ('member upload records', 'DELETE FROM individual_individualdatasource WHERE individual_id IN (SELECT id FROM rm4_i)'),
    ('memberships', 'DELETE FROM individual_groupindividual WHERE "UUID" IN (SELECT id FROM rm4_gi)'),
    ('households', 'DELETE FROM individual_group WHERE "UUID" IN (SELECT id FROM rm4_g)'),
    ('members', 'DELETE FROM individual_individual WHERE "UUID" IN (SELECT id FROM rm4_i)'),
    ('history: memberships', 'DELETE FROM individual_historicalgroupindividual WHERE "UUID" IN (SELECT id FROM rm4_gi)'),
    ('history: households', 'DELETE FROM individual_historicalgroup WHERE "UUID" IN (SELECT id FROM rm4_g)'),
    ('history: members', 'DELETE FROM individual_historicalindividual WHERE "UUID" IN (SELECT id FROM rm4_i)'),
    ('history: PMT enrolments', 'DELETE FROM individual_historicalpmtenrollment WHERE group_id IN (SELECT id FROM rm4_g)'),
    ('history: household upload records',
     'DELETE FROM individual_historicalgroupdatasource WHERE group_id IN (SELECT id FROM rm4_g)'),
    ('history: member upload records',
     'DELETE FROM individual_historicalindividualdatasource WHERE individual_id IN (SELECT id FROM rm4_i)'),
]


def _content_types():
    from django.contrib.contenttypes.models import ContentType

    def ct(app, model):
        return ContentType.objects.get_by_natural_key(app, model).id

    def ct_or_none(app, model):
        try:
            return ct(app, model)
        except ContentType.DoesNotExist:
            return None

    from legacy_individual.models import Rm4Group, Rm4Individual
    return {
        'ct_group': ct('individual', 'group'),
        'ct_individual': ct('individual', 'individual'),
        'ct_link': ct('individual', 'groupindividual'),
        'ct_group_beneficiary': ct_or_none('social_protection', 'groupbeneficiary'),
        'ct_beneficiary': ct_or_none('social_protection', 'beneficiary'),
        'ct_benefit': ct_or_none('payroll', 'benefitconsumption'),
        'ct_account': ct_or_none('tasaf_payment', 'paymentaccount'),
        'ct_rm4_group': ContentType.objects.get_for_model(Rm4Group).id,
        'ct_rm4_individual': ContentType.objects.get_for_model(Rm4Individual).id,
    }


class ArchiveNotVerified(Exception):
    pass


def clear_live(confirm=False, emit=logger.info):
    """Remove the archived RM4 rows from the live register. Without ``confirm`` every change is rolled back,
    so the counts are exact but nothing is kept."""
    report = verify()
    if not report['ok']:
        raise ArchiveNotVerified(f"archive does not match the live RM4 rows: {report}")
    params = _content_types()
    totals, paylists = {}, set()
    batches = LegacyImportBatch.objects.filter(source_system=SOURCE_SYSTEM, is_deleted=False).order_by('code')
    # Dry run: one outer transaction, rolled back at the end.
    try:
        with (nullcontext() if confirm else transaction.atomic()):
            for batch in batches:
                with transaction.atomic(), connection.cursor() as cursor:
                    for sql in _scope_sql():
                        cursor.execute(sql, {**params, 'batch': batch.id})
                    cursor.execute("SELECT DISTINCT paylist_id FROM rm4_pli")
                    paylists.update(row[0] for row in cursor.fetchall())
                    done = {}
                    for label, sql in CLEAR_STEPS:
                        cursor.execute(sql, params)
                        done[label] = cursor.rowcount
                        totals[label] = totals.get(label, 0) + cursor.rowcount
                emit(f"{batch.code}: {done['households']} households, {done['members']} members, "
                     f"{done['memberships']} memberships")
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT count(*) FROM ({SOURCE_GROUPS}) t")
                left = cursor.fetchone()[0]
                cursor.execute("""SELECT count(*) FROM "tasaf_Paylist" p WHERE p."UUID" = ANY(%s::uuid[])
                                  AND NOT EXISTS (SELECT 1 FROM "tasaf_PaylistItem" i WHERE i.paylist_id = p."UUID")""",
                               [[str(p) for p in paylists]])
                emptied = cursor.fetchone()[0]
            result = {'steps': totals, 'live_rm4_households_left': left,
                      'paylists_touched': len(paylists), 'paylists_now_empty': emptied, 'confirmed': confirm}
            if not confirm:
                raise _DryRun(result)
    except _DryRun as dry:
        return dry.result
    logger.info("RM4 live register cleared: %s", result)
    return result


class _DryRun(Exception):
    def __init__(self, result):
        super().__init__('dry run')
        self.result = result
