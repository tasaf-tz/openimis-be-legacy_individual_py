"""RM4 archive GraphQL: rights, filters on answers, membership lookup, and district row security."""
from unittest import mock

import graphene
from django.db.models import Q
from django.test import RequestFactory, TestCase, override_settings

from legacy_individual import rm4_archive
from legacy_individual.models import Rm4Group
from legacy_individual.schema import Query
from legacy_individual.tests.test_rm4_archive import Rm4Fixtures


def _context(user):
    request = RequestFactory().post('/api/graphql')
    request.user = user
    return request


class _NoRights:
    id = 99
    is_anonymous = False

    def has_perms(self, perms):
        return False


class Rm4ApiTest(Rm4Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        rm4_archive.archive(self.user, emit=lambda *_: None)
        self.schema = graphene.Schema(query=Query)

    def run_query(self, query, user=None):
        result = self.schema.execute(query, context_value=_context(user or self.user))
        return result

    def test_households_with_answer_filters(self):
        group = self.hh_a[0]
        group.refresh_from_db()
        key = group.json_ext.get('interview_key')
        result = self.run_query('{ rm4Groups(code_Istartswith: "p3-000000001") { totalCount edges { node { uuid code } } } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['rm4Groups']['totalCount'], 1)
        self.assertEqual(result.data['rm4Groups']['edges'][0]['node']['uuid'], str(group.id))
        if key:
            result = self.run_query(f'{{ rm4Groups(interviewKey: "{key}") {{ totalCount }} }}')
            self.assertEqual(result.data['rm4Groups']['totalCount'], 1)

    def test_members_by_household_code_and_name(self):
        result = self.run_query('{ rm4Individuals(groupCode: "P3-000000001", firstName_Icontains: "jum") '
                                '{ totalCount edges { node { firstName lastName } } } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['rm4Individuals']['totalCount'], 1)
        self.assertEqual(result.data['rm4Individuals']['edges'][0]['node']['firstName'], 'JUMA')

    def test_household_members(self):
        group = self.hh_a[0]
        result = self.run_query(f'{{ rm4GroupIndividuals(group_Id: "{group.id}") '
                                '{ totalCount edges { node { role individual { firstName } } } } }')
        self.assertIsNone(result.errors)
        roles = sorted(e['node']['role'] for e in result.data['rm4GroupIndividuals']['edges'])
        self.assertEqual(roles, ['HEAD', 'SON'])

    def test_refused_without_rights(self):
        for query in ('{ rm4Groups { totalCount } }', '{ rm4Individuals { totalCount } }',
                      '{ rm4GroupIndividuals { totalCount } }'):
            result = self.run_query(query, user=_NoRights())
            self.assertTrue(result.errors, query)
            self.assertIn('Unauthorized', str(result.errors[0]))

    def test_only_households_in_the_users_districts(self):
        village = self.village_a
        user = mock.Mock(is_anonymous=False, is_imis_admin=False)
        with override_settings(ROW_SECURITY=True), mock.patch(
                'location.models.LocationManager.build_user_location_filter_query',
                side_effect=lambda _u, prefix='location', **_: Q(**{f'{prefix}__in': [village.id]})) as built:
            codes = list(Rm4Group.get_queryset(None, user).filter(code__startswith='P3-')
                         .values_list('code', flat=True))
        self.assertEqual(codes, [self.hh_a[0].code])
        self.assertEqual(built.call_args.kwargs['prefix'], 'location')
