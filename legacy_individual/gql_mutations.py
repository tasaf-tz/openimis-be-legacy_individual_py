"""
Mutations for the legacy_individual module.

For now there is no GraphQL mutation that uploads files — file uploads are
done through the REST endpoint ``POST /legacy_individual/import_pssn/``.
This module reserves a mutation slot for phase-2 (matching/promotion) work.
"""

import graphene


class Mutation(graphene.ObjectType):
    """Placeholder. File uploads use the REST endpoint."""
    pass
