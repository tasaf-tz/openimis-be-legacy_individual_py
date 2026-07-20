import logging
import os
import threading

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from core.views import check_user_rights

from legacy_individual.apps import LegacyIndividualConfig
from legacy_individual.services import LegacyApiImportService, LegacyImportBatchService
from legacy_individual.workflows.pssn_legacy_upload import (
    process_legacy_pssn_upload,
)

logger = logging.getLogger(__name__)


def _as_bool(value):
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'y', 'on')


_ALLOWED_EXTENSIONS = {'.csv'}
_ALLOWED_MIME_TYPES = {
    'text/csv',
    'application/vnd.ms-excel',
    'application/octet-stream',
}


def _validate_csv(import_file):
    if import_file is None:
        return False, 'Missing file'
    ext = os.path.splitext(import_file.name)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return False, f'Invalid file type for {import_file.name}: only .csv allowed'
    if (
        import_file.content_type
        and import_file.content_type not in _ALLOWED_MIME_TYPES
    ):
        return False, f'Invalid MIME type for {import_file.name}: {import_file.content_type}'
    return True, None


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([
    check_user_rights(LegacyIndividualConfig.gql_legacy_import_execute_perms),
])
def import_pssn(request):
    household_file = request.FILES.get('household_file')
    member_file = request.FILES.get('member_file')
    code = request.POST.get('code') or ''

    for label, f in (('household_file', household_file), ('member_file', member_file)):
        ok, msg = _validate_csv(f)
        if not ok:
            return Response(
                {'success': False, 'error': f'{label}: {msg}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        service = LegacyImportBatchService(request.user)
        batch = service.create_from_files(household_file, member_file, code=code)
        process_legacy_pssn_upload(str(request.user.id), str(batch.id))
        batch.refresh_from_db()
        return Response({
            'success': True,
            'data': {
                'batch_uuid': str(batch.id),
                'status': batch.status,
                'total_households': batch.total_households,
                'total_members': batch.total_members,
                'success_household_count': batch.success_household_count,
                'success_member_count': batch.success_member_count,
                'warning_count': batch.warning_count,
                'error_count': batch.error_count,
            },
        })
    except Exception as exc:
        logger.exception('Legacy PSSN import failed')
        return Response(
            {'success': False, 'error': str(exc)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@parser_classes([JSONParser, FormParser, MultiPartParser])
@permission_classes([
    check_user_rights(LegacyIndividualConfig.gql_legacy_import_execute_perms),
])
def import_pssn_api(request):
    """Pull one district from the legacy PSSN API. See docs/LEGACY_API_ETL_CODE_RATIONALE.md."""
    data = request.data if isinstance(request.data, dict) else {}
    district_code = (data.get('district_code') or request.POST.get('district_code') or '').strip()
    region_code = data.get('region_code') or request.POST.get('region_code') or None
    paa_name = data.get('paa_name') or request.POST.get('paa_name') or None
    dry_run = _as_bool(data.get('dry_run') or request.POST.get('dry_run'))

    if not district_code:
        return Response(
            {'success': False, 'error': 'district_code is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = request.user

    if dry_run:
        try:
            result = LegacyApiImportService(user).run(
                district_code, paa_name=paa_name, region_code=region_code, dry_run=True,
            )
            return Response({'success': True, 'data': {**result, 'mode': 'sync'}})
        except Exception as exc:
            logger.exception('Legacy PSSN API dry run failed (district=%s)', district_code)
            return Response(
                {'success': False, 'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    reimport_error = LegacyApiImportService(user).precheck_reimport(district_code)
    if reimport_error:
        return Response(
            {'success': False, 'error': reimport_error},
            status=status.HTTP_409_CONFLICT,
        )

    mode = 'thread'

    if getattr(LegacyIndividualConfig, 'legacy_api_use_celery', True):
        try:
            from legacy_individual.tasks import run_legacy_pssn_api_import
            run_legacy_pssn_api_import.apply_async(
                args=[str(user.id), district_code, region_code, paa_name, dry_run],
                retry=False,
            )
            mode = 'celery'
        except Exception:
            logger.warning(
                'Legacy PSSN API: Celery enqueue failed (no broker?); '
                'falling back to a background thread.', exc_info=True,
            )

    if mode == 'thread':
        def _run():
            from django.db import close_old_connections
            close_old_connections()
            try:
                LegacyApiImportService(user).run(
                    district_code, paa_name=paa_name, region_code=region_code, dry_run=dry_run
                )
            except Exception:
                logger.exception('Legacy PSSN API import failed (district=%s)', district_code)
            finally:
                close_old_connections()

        threading.Thread(
            target=_run, name=f'legacy_api_import_{district_code}', daemon=True
        ).start()

    return Response({
        'success': True,
        'data': {
            'district_code': district_code,
            'dry_run': dry_run,
            'mode': mode,
            'message': 'Import started. Refresh the import batches list to track progress.',
        },
    })
