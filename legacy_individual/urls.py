from django.urls import path

from legacy_individual.views import import_pssn, import_pssn_api

urlpatterns = [
    path('import_pssn/', import_pssn, name='legacy_individual_import_pssn'),
    path('import_pssn_api/', import_pssn_api, name='legacy_individual_import_pssn_api'),
]
