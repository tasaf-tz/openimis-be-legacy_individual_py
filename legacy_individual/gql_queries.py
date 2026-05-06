from django.contrib.auth.models import AnonymousUser

import graphene
import graphene_django_optimizer as gql_optimizer
from graphene_django import DjangoObjectType

from core import ExtendedConnection

from legacy_individual.models import (
    LegacyGroup,
    LegacyGroupIndividual,
    LegacyImportBatch,
    LegacyIndividual,
)


def _have_permissions(user, permission):
    if isinstance(user, AnonymousUser):
        return False
    if not user.id:
        return False
    return user.has_perms(permission)


class LegacyImportBatchGQLType(DjangoObjectType):
    uuid = graphene.String(source='uuid')

    class Meta:
        model = LegacyImportBatch
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'id': ['exact'],
            'code': ['iexact', 'istartswith', 'icontains'],
            'source_system': ['iexact'],
            'status': ['exact'],
            'date_created': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'is_deleted': ['exact'],
        }
        connection_class = ExtendedConnection


class LegacyGroupGQLType(DjangoObjectType):
    uuid = graphene.String(source='uuid')

    class Meta:
        model = LegacyGroup
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'id': ['exact'],
            'code': ['iexact', 'istartswith', 'icontains'],
            'is_deleted': ['exact'],
            'date_created': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
        connection_class = ExtendedConnection


class LegacyIndividualGQLType(DjangoObjectType):
    uuid = graphene.String(source='uuid')

    class Meta:
        model = LegacyIndividual
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'id': ['exact'],
            'legacy_code': ['iexact', 'istartswith'],
            'first_name': ['iexact', 'istartswith', 'icontains'],
            'middle_name': ['iexact', 'istartswith', 'icontains'],
            'last_name': ['iexact', 'istartswith', 'icontains'],
            'gender': ['exact'],
            'dob': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'nin': ['exact'],
            'premno': ['exact'],
            'phone_no': ['exact', 'icontains'],
            'is_deleted': ['exact'],
            'date_created': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
        connection_class = ExtendedConnection


class LegacyGroupIndividualGQLType(DjangoObjectType):
    uuid = graphene.String(source='uuid')

    class Meta:
        model = LegacyGroupIndividual
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'id': ['exact'],
            'group__id': ['exact'],
            'role': ['exact'],
            'relationship_code': ['exact'],
            'recipient_type': ['exact'],
            'member_line': ['exact'],
            'is_deleted': ['exact'],
        }
        connection_class = ExtendedConnection
