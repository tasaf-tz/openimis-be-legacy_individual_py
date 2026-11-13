import logging

from core.signals import register_service_signal

logger = logging.getLogger(__name__)


class LegacyIndividualEvents:
    def __init__(self, user=None):
        self.user = user

    @register_service_signal("legacy_individual_service.api_import_finished")
    def api_import_finished(self, *, batch_id, status, district_code="", paa_name="", message=""):
        return {"batch_id": str(batch_id) if batch_id else "", "status": status,
                "district_code": district_code, "paa_name": paa_name, "message": message}


def emit_api_import_finished(user, **kwargs):
    try:
        LegacyIndividualEvents(user).api_import_finished(**kwargs)
    except Exception:
        logger.warning("legacy_individual: api_import_finished signal failed %s", kwargs, exc_info=True)
