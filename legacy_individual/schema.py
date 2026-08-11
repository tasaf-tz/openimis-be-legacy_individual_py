import graphene
import graphene_django_optimizer as gql_optimizer
from django.db.models import Q

from core.schema import OrderedDjangoFilterConnectionField
from location.apps import LocationConfig

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
        parent_location=graphene.String(),
        parent_location_level=graphene.Int(),
        import_batch_id=graphene.String(),
    )

    legacy_group = graphene.relay.Node.Field(LegacyGroupGQLType)
    legacy_groups = OrderedDjangoFilterConnectionField(
        LegacyGroupGQLType,
        orderBy=graphene.List(of_type=graphene.String),
        parent_location=graphene.String(),
        parent_location_level=graphene.Int(),
        import_batch_id=graphene.String(),
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
        qs = LegacyIndividual.objects.filter(
            is_deleted=False, *Query._scope_filters(kwargs)
        )
        return gql_optimizer.query(qs, info)

    def resolve_legacy_groups(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_legacy_group_search_perms)
        qs = LegacyGroup.objects.filter(
            is_deleted=False, *Query._scope_filters(kwargs)
        )
        return gql_optimizer.query(qs, info)

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
    def _scope_filters(kwargs):
        """
        Location and import-batch scoping, matching the individual module's
        parent_location / parent_location_level convention.
        """
        filters = []
        parent_location = kwargs.get("parent_location")
        parent_location_level = kwargs.get("parent_location_level")
        if parent_location is not None and parent_location_level is not None:
            query_key = "uuid"
            for _ in range(
                len(LocationConfig.location_types) - parent_location_level - 1
            ):
                query_key = "parent__" + query_key
            filters.append(Q(**{f"location__{query_key}": parent_location}))

        import_batch_id = kwargs.get("import_batch_id")
        if import_batch_id:
            filters.append(Q(import_batch__id=import_batch_id))
        return filters

    @staticmethod
    def _check_search_perm(info, perm):
        if not _have_permissions(info.context.user, perm):
            raise PermissionError("Unauthorized")


class Mutation(MutationBase):
    pass
