import graphene
import graphene_django_optimizer as gql_optimizer
from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Upper

from core.schema import OrderedDjangoFilterConnectionField
from location.apps import LocationConfig

from legacy_individual.apps import LegacyIndividualConfig
from legacy_individual.gql_mutations import Mutation as MutationBase
from legacy_individual.gql_queries import (
    LegacyGroupGQLType,
    LegacyGroupIndividualGQLType,
    LegacyImportBatchGQLType,
    LegacyIndividualGQLType,
    Rm4GroupGQLType,
    Rm4GroupIndividualGQLType,
    Rm4IndividualGQLType,
    _have_permissions,
)
from legacy_individual.models import (
    LegacyGroup,
    LegacyGroupIndividual,
    LegacyImportBatch,
    LegacyIndividual,
    Rm4Group,
    Rm4GroupIndividual,
    Rm4Individual,
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
        parent_location=graphene.String(),
        parent_location_level=graphene.Int(),
    )

    rm4_groups = OrderedDjangoFilterConnectionField(
        Rm4GroupGQLType,
        orderBy=graphene.List(of_type=graphene.String),
        parent_location=graphene.String(),
        parent_location_level=graphene.Int(),
        archive_batch_id=graphene.String(),
        interview_key=graphene.String(),
        pmt_class=graphene.String(),
    )
    rm4_individuals = OrderedDjangoFilterConnectionField(
        Rm4IndividualGQLType,
        orderBy=graphene.List(of_type=graphene.String),
        parent_location=graphene.String(),
        parent_location_level=graphene.Int(),
        archive_batch_id=graphene.String(),
        external_id=graphene.String(),
        group_code=graphene.String(),
    )
    rm4_group_individuals = OrderedDjangoFilterConnectionField(
        Rm4GroupIndividualGQLType,
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
        qs = LegacyImportBatch.objects.filter(
            is_deleted=False, *Query._batch_scope_filters(kwargs)
        )
        return gql_optimizer.query(qs, info)

    def resolve_rm4_groups(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_rm4_group_search_perms)
        qs = Query._rm4_queryset(Rm4Group, info, kwargs)
        if kwargs.get('interview_key'):
            qs = qs.annotate(_interview_key=KeyTextTransform('interview_key', 'json_ext')).filter(
                _interview_key=kwargs['interview_key'])
        if kwargs.get('pmt_class'):
            qs = qs.annotate(_pmt_class=KeyTextTransform('pmt_class_household', 'json_ext')).filter(
                _pmt_class=kwargs['pmt_class'])
        return gql_optimizer.query(qs, info)

    def resolve_rm4_individuals(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_rm4_individual_search_perms)
        qs = Query._rm4_queryset(Rm4Individual, info, kwargs)
        if kwargs.get('external_id'):
            qs = qs.annotate(_external_id=Upper(KeyTextTransform('external_id', 'json_ext'))).filter(
                _external_id__startswith=kwargs['external_id'].upper())
        if kwargs.get('group_code'):
            qs = qs.filter(memberships__group__code__istartswith=kwargs['group_code']).distinct()
        return gql_optimizer.query(qs, info)

    def resolve_rm4_group_individuals(self, info, **kwargs):
        Query._check_search_perm(info, LegacyIndividualConfig.gql_rm4_group_search_perms)
        qs = Rm4GroupIndividual.get_queryset(None, info.context.user).filter(is_deleted=False)
        return gql_optimizer.query(qs, info)

    @staticmethod
    def _rm4_queryset(model, info, kwargs):
        """Archive rows the user's districts allow, filtered by location and archive batch."""
        qs = model.get_queryset(None, info.context.user).filter(
            is_deleted=False, *Query._scope_filters(kwargs))
        if kwargs.get('archive_batch_id'):
            qs = qs.filter(archive_batch__id=kwargs['archive_batch_id'])
        return qs

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
    def _batch_scope_filters(kwargs):
        """Location scoping for batches, which carry district/region directly.

        A batch IS one district, so the selected location is resolved to the district it
        belongs to and matched against that column -- an indexed FK compare, no join into
        LegacyIndividual.
        """
        from location.models import Location

        parent_location = kwargs.get("parent_location")
        if not parent_location:
            return []

        loc = Location.objects.filter(
            uuid=parent_location, validity_to__isnull=True).select_related(
            'parent', 'parent__parent').first()
        if loc is None:
            return []

        if loc.type == 'R':
            return [Q(region=loc) | Q(district__parent=loc)]

        node, hops = loc, 0
        while node is not None and node.type != 'D' and hops < 5:
            node = node.parent
            hops += 1
        if node is None or node.type != 'D':
            return []
        return [Q(district=node)]

    @staticmethod
    def _check_search_perm(info, perm):
        if not _have_permissions(info.context.user, perm):
            raise PermissionError("Unauthorized")


class Mutation(MutationBase):
    pass
