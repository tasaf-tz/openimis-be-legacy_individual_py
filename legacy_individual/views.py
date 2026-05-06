"""
REST endpoints for the legacy_individual module.

Single endpoint for MVP:

- POST ``/legacy_individual/import_pssn/`` — multipart upload of the two
  PSSN CSVs (``household_file`` + ``member_file``). Creates a
  ``LegacyImportBatch``, persists both files, and runs the paired-upload
  workflow synchronously (mirrors the live ``individual.import_individuals``
  pattern).
"""

import logging
import os

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from core.views import check_user_rights

from legacy_individual.apps import LegacyIndividualConfig
from legacy_individual.services import LegacyImportBatchService
from legacy_individual.workflows.pssn_legacy_upload import (
    process_legacy_pssn_upload,
)

logger = logging.getLogger(__name__)


_ALLOWED_EXTENSIONS = {'.csv'}
_ALLOWED_MIME_TYPES = {
    'text/csv',
    'application/vnd.ms-excel',  # Windows browsers tag .csv as this
    'application/octet-stream',  # some browsers/OSes give no MIME for .csv
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
        # Run synchronously for now. If file pairs grow, swap to a
        # background task — the workflow function is the contract.
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
