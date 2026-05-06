from django.urls import path

from legacy_individual.views import import_pssn

urlpatterns = [
    path('import_pssn/', import_pssn, name='legacy_individual_import_pssn'),
]
