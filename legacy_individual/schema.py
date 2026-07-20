import graphene
import graphene_django_optimizer as gql_optimizer

from core.schema import OrderedDjangoFilterConnectionField

from legacy_individual.apps import LegacyIndividualConfig
from legacy_individual.gql_mutations import Mutation as MutationBase
from legacy_individual.gql_queries import (
    LegacyGroupGQLType,
    LegacyGroupIndividualGQLType,
    LegacyImportBatchGQLType,
    LegacyIndividualGQLType,
    _have_permissions,
)
from legacy_individual.models import (
    LegacyGroup,
    LegacyGroupIndividual,
    LegacyImportBatch,
    LegacyIndividual,
)


class Query(graphene.ObjectType):
    legacy_individual = graphene.relay.Node.Field(LegacyIndividualGQLType)
    legacy_individuals = OrderedDjangoFilterConnectionField(
        LegacyIndividualGQLType,
        orderBy=graphene.List(of_type=graphene.String),
    )

    legacy_group = graphene.relay.Node.Field(LegacyGroupGQLType)
    legacy_groups = OrderedDjangoFilterConnectionField(
        LegacyGroupGQLType,
        orderBy=graphene.List(of_type=graphene.String),
    )

    legacy_group_individual = graphene.relay.Node.Field(LegacyGroupIndividualGQLType)
    legacy_group_individuals = OrderedDjangoFilterConnectionField(
        LegacyGroupIndividualGQLType,
        orderBy=graphene.List(of_type=graphene.String),
    )

    legacy_import_batch = graphene.relay.Node.Field(LegacyImportBatchGQLType)
    legacy_import_batches = OrderedDjangoFilterConnectionField(
        LegacyImportBatchGQLType,
        orderBy=graphene.List(of_type=graphene.String),
    )

    # ---- resolvers ----
    def resolve_legacy_individuals(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_legacy_individual_search_perms)
        return gql_optimizer.query(
            LegacyIndividual.objects.filter(is_deleted=False), info,
        )

    def resolve_legacy_groups(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_legacy_group_search_perms)
        return gql_optimizer.query(
            LegacyGroup.objects.filter(is_deleted=False), info,
        )

    def resolve_legacy_group_individuals(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_legacy_group_search_perms)
        return gql_optimizer.query(
            LegacyGroupIndividual.objects.filter(is_deleted=False), info,
        )

    def resolve_legacy_import_batches(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_legacy_individual_search_perms)
        return gql_optimizer.query(
            LegacyImportBatch.objects.filter(is_deleted=False), info,
        )

    @staticmethod
    def _check_search_perm(info, perm):
        if not _have_permissions(info.context.user, perm):
            raise PermissionError("Unauthorized")


class Mutation(MutationBase):
    pass
