import json
import logging
import os

from django.apps import AppConfig
from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "gql_legacy_individual_search_perms": ["200001"],
    "gql_legacy_individual_create_perms": ["200002"],
    "gql_legacy_individual_update_perms": ["200003"],
    "gql_legacy_individual_delete_perms": ["200004"],
    "gql_legacy_group_search_perms": ["200011"],
    "gql_legacy_group_create_perms": ["200012"],
    "gql_legacy_group_update_perms": ["200013"],
    "gql_legacy_group_delete_perms": ["200014"],
    "gql_legacy_import_execute_perms": ["200021"],
    "gql_legacy_match_review_perms": ["200031"],
    "gql_legacy_promotion_execute_perms": ["200041"],

    "legacy_read_only_default": True,
    "legacy_preserve_uploaded_file": True,
    "legacy_resolve_facility_against_tblhf": True,

    # Legacy PSSN API pull — see docs/LEGACY_API_ETL_CODE_RATIONALE.md.
    "legacy_api_base_url": "",
    "legacy_api_path": "/livePSSN/api/etlapi/combined_household_members.php",
    "legacy_api_auth_type": "none",
    "legacy_api_username": "",
    "legacy_api_password": "",
    "legacy_api_bearer_token": "",
    "legacy_api_connect_timeout": 5,
    "legacy_api_read_timeout": 60,
    "legacy_api_retries": 3,
    "legacy_api_page_size": 1000,
    "legacy_api_max_pages": 1000,
    "legacy_api_reimport_strategy": "replace",
    "legacy_api_preserve_raw_json": True,
    "legacy_api_use_celery": True,

    "enable_legacy_matching": False,
    "enable_legacy_promotion": False,
}


class LegacyIndividualConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'legacy_individual'

    gql_legacy_individual_search_perms = None
    gql_legacy_individual_create_perms = None
    gql_legacy_individual_update_perms = None
    gql_legacy_individual_delete_perms = None
    gql_legacy_group_search_perms = None
    gql_legacy_group_create_perms = None
    gql_legacy_group_update_perms = None
    gql_legacy_group_delete_perms = None
    gql_legacy_import_execute_perms = None
    gql_legacy_match_review_perms = None
    gql_legacy_promotion_execute_perms = None

    legacy_read_only_default = None
    legacy_preserve_uploaded_file = None
    legacy_resolve_facility_against_tblhf = None
    enable_legacy_matching = None
    enable_legacy_promotion = None

    legacy_api_base_url = None
    legacy_api_path = None
    legacy_api_auth_type = None
    legacy_api_username = None
    legacy_api_password = None
    legacy_api_bearer_token = None
    legacy_api_connect_timeout = None
    legacy_api_read_timeout = None
    legacy_api_retries = None
    legacy_api_page_size = None
    legacy_api_max_pages = None
    legacy_api_reimport_strategy = None
    legacy_api_preserve_raw_json = None
    legacy_api_use_celery = None

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default(self.name, DEFAULT_CONFIG)
        self.__load_config(cfg)
        self.__connect_signals()

    def __connect_signals(self):
        from core.models import ModuleConfiguration
        post_save.connect(
            self._reload_module_config,
            sender=ModuleConfiguration,
            weak=False,
        )

    def _reload_module_config(self, sender, instance, **kwargs):
        if instance.module == self.name and instance.layer == 'be':
            db_config = json.loads(instance.config)
            config = {**DEFAULT_CONFIG, **db_config}
            self.__load_config(config)
            logger.info("Reloaded app configs for %s module", self.name)

    @classmethod
    def __load_config(cls, cfg):
        for field in cfg:
            if hasattr(cls, field):
                setattr(cls, field, cfg[field])

    @staticmethod
    def get_legacy_upload_file_path(filename):
        """Mirrors IndividualConfig.get_individual_upload_file_path."""
        from django.conf import settings
        upload_root = getattr(settings, 'BASE_DIR', '.')
        return os.path.join(upload_root, 'legacy_individual_uploads', filename)
