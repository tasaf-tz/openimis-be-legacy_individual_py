"""Celery task for the legacy PSSN API import.

See docs/LEGACY_API_ETL_CODE_RATIONALE.md.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, name="legacy_individual.import_pssn_api")
def run_legacy_pssn_api_import(
    self, user_id, district_code, region_code=None, paa_name=None, dry_run=False
):
    from core.models import User
    from legacy_individual.services import LegacyApiImportService

    user = User.objects.get(id=user_id)
    logger.info(
        "Legacy PSSN API import task starting: district=%s dry_run=%s task=%s",
        district_code, dry_run, getattr(self.request, "id", None),
    )
    result = LegacyApiImportService(user).run(
        district_code, paa_name=paa_name, region_code=region_code, dry_run=dry_run
    )
    logger.info(
        "Legacy PSSN API import task done: district=%s batch=%s status=%s",
        district_code, result.get("batch_id"), result.get("status"),
    )
    return result
