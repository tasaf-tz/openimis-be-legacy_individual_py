from django.contrib import admin

from legacy_individual.models import (
    LegacyImportBatch,
    LegacyGroup,
    LegacyIndividual,
    LegacyGroupIndividual,
)

admin.site.register(LegacyImportBatch)
admin.site.register(LegacyGroup)
admin.site.register(LegacyIndividual)
admin.site.register(LegacyGroupIndividual)
