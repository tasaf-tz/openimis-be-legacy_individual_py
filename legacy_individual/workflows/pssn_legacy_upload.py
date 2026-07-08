"""
Paired PSSN CSV ingest workflow.

Inputs (preserved on the LegacyImportBatch by ``LegacyImportBatchService``):

- household file : ``PSSN_ENROLLED_HOUSEHOLD_*.csv``
- member file    : ``PSSN_ENROLLMENT_HH_MEMBER_*.csv``

Joined on ``REGISTRATIONNO``. See
``docs/legacy-individual-module/07_PSSN_COLUMN_MAPPING.md`` for the
column-by-column contract this workflow implements.

The workflow only writes to ``legacy_individual_*`` tables. It never touches
``individual_individual`` or ``individual_group``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd
from django.db import transaction

from core.models import User
from core.utils import set_current_user, clear_current_user
from location.models import HealthFacility, Location

from legacy_individual.apps import LegacyIndividualConfig
from legacy_individual.columns import (
    _HOUSEHOLD_KNOWN_COLUMNS,
    _MEMBER_KNOWN_COLUMNS,
)
from legacy_individual.models import (
    LegacyGroup,
    LegacyGroupIndividual,
    LegacyImportBatch,
    LegacyIndividual,
)
from legacy_individual.services import (
    LegacyImportBatchService,
    PssnNormalizationService,
)

logger = logging.getLogger(__name__)


REQUIRED_HOUSEHOLD_COLUMNS = {'REGISTRATIONNO'}
REQUIRED_MEMBER_COLUMNS = {'REGISTRATIONNO', 'MEMBERLINENO'}


def process_legacy_pssn_upload(user_uuid: str, batch_uuid: str) -> None:
    """
    Run the full paired-upload pipeline for one CSV batch.

    Idempotent on retry: re-running on a failed batch will create duplicate
    rows; callers should reset the batch first if they want to re-import.
    """
    user = User.objects.get(id=user_uuid)
    set_current_user(user)
    try:
        batch = LegacyImportBatch.objects.get(id=batch_uuid)
        service = LegacyImportBatchService(user)

        files = (batch.json_ext or {}).get('files') or {}
        household_path = (files.get('household') or {}).get('path')
        member_path = (files.get('member') or {}).get('path')

        if not household_path or not member_path:
            service.fail(batch, 'Missing preserved files on batch')
            return

        try:
            household_df = pd.read_csv(household_path, dtype=str, keep_default_na=False)
            member_df = pd.read_csv(member_path, dtype=str, keep_default_na=False)
        except Exception as exc:
            service.fail(batch, 'Could not read CSV files', {'error': str(exc)})
            logger.exception('Legacy PSSN upload — read failure')
            return

        process_legacy_pssn_frames(user, batch, household_df, member_df, service=service)
    finally:
        clear_current_user()


def process_legacy_pssn_frames(
    user,
    batch: LegacyImportBatch,
    household_df: pd.DataFrame,
    member_df: pd.DataFrame,
    *,
    service: Optional[LegacyImportBatchService] = None,
) -> Optional[Dict]:
    """Import a pre-loaded pair of PSSN frames. See docs/LEGACY_API_ETL_CODE_RATIONALE.md."""
    service = service or LegacyImportBatchService(user)

    missing_household = REQUIRED_HOUSEHOLD_COLUMNS - set(household_df.columns)
    missing_member = REQUIRED_MEMBER_COLUMNS - set(member_df.columns)
    if missing_household or missing_member:
        service.fail(
            batch,
            'Required columns missing',
            {
                'household_missing': sorted(missing_household),
                'member_missing': sorted(missing_member),
            },
        )
        return None

    service.mark_in_progress(batch)

    try:
        with transaction.atomic():
            stats = _import_paired(batch, household_df, member_df, user)
    except Exception as exc:
        logger.exception('Legacy PSSN import — fatal during import')
        service.fail(batch, 'Fatal error during import', {'error': str(exc)})
        return None

    service.finalize(
        batch,
        total_households=stats['total_households'],
        total_members=stats['total_members'],
        success_household_count=stats['success_household_count'],
        success_member_count=stats['success_member_count'],
        warning_count=stats['warning_count'],
        error_count=stats['error_count'],
        errors={'errors': stats['errors']} if stats['errors'] else {},
    )
    return stats


def _import_paired(
    batch: LegacyImportBatch,
    household_df: pd.DataFrame,
    member_df: pd.DataFrame,
    user,
) -> Dict:
    errors: Dict[str, list] = {'household_file': [], 'member_file': []}
    warning_count = 0

    location_cache = _build_village_cache(household_df)

    group_by_registration: Dict[str, LegacyGroup] = {}
    success_household = 0

    for idx, row in household_df.iterrows():
        registration_no = (row.get('REGISTRATIONNO') or '').strip()
        if not registration_no:
            errors['household_file'].append({
                'row': int(idx),
                'reason': 'REGISTRATIONNO blank',
            })
            continue
        if registration_no in group_by_registration:
            errors['household_file'].append({
                'row': int(idx),
                'reason': f'Duplicate REGISTRATIONNO {registration_no} in household file',
            })
            continue

        village_code = PssnNormalizationService.normalize_code(
            row.get('VILLAGE_CODE'), 'village'
        )
        location = location_cache.get(village_code) if village_code else None
        if village_code and not location:
            warning_count += 1

        group = LegacyGroup(
            code=registration_no,
            import_batch=batch,
            location=location,
            json_ext=_build_group_json_ext(row, village_code, location),
        )
        group.save(user=user)
        group_by_registration[registration_no] = group
        success_household += 1

    facility_cache = _build_facility_cache(member_df)
    head_phone_by_registration = _extract_head_phones(household_df)
    success_member = 0

    for idx, row in member_df.iterrows():
        registration_no = (row.get('REGISTRATIONNO') or '').strip()
        member_line_no = (row.get('MEMBERLINENO') or '').strip()

        if not registration_no:
            errors['member_file'].append({
                'row': int(idx),
                'reason': 'REGISTRATIONNO blank',
            })
            continue
        if not member_line_no:
            errors['member_file'].append({
                'row': int(idx),
                'reason': 'MEMBERLINENO blank',
            })
            continue

        group = group_by_registration.get(registration_no)
        if not group:
            errors['member_file'].append({
                'row': int(idx),
                'reason': f'No matching household for REGISTRATIONNO {registration_no}',
            })
            continue

        first_name = PssnNormalizationService.trim_name(row.get('FIRSTNAME'))
        last_name = PssnNormalizationService.trim_name(row.get('LASTNAME'))
        if not (first_name or last_name):
            errors['member_file'].append({
                'row': int(idx),
                'reason': 'Both FIRSTNAME and LASTNAME blank',
            })
            continue

        gender = PssnNormalizationService.decode_gender(row.get('SEX'))
        rel_code = (row.get('RELATIONSHIPTOHEAD') or '').strip() or None
        hh_rep = (row.get('HH_REP') or '').strip()
        is_primary_recipient = hh_rep == '1'

        legacy_code = PssnNormalizationService.derive_legacy_code(
            registration_no, member_line_no
        )

        facility_code = PssnNormalizationService.normalize_code(
            row.get('FACILITY_CODE'), 'village'
        ) if row.get('FACILITY_CODE') else None
        raw_facility_code = (row.get('FACILITY_CODE') or '').strip() or None
        facility = (
            facility_cache.get(raw_facility_code)
            if raw_facility_code and LegacyIndividualConfig.legacy_resolve_facility_against_tblhf
            else None
        )
        if raw_facility_code and not facility:
            warning_count += 1

        phone_no = None
        if is_primary_recipient:
            phone_no = head_phone_by_registration.get(registration_no)

        nin = (row.get('NIDA_NIN') or '').strip() or None
        premno = (row.get('PREM_NO') or '').strip() or None
        dob = PssnNormalizationService.parse_dob(row.get('DATEOFBIRTH'))
        disability = PssnNormalizationService.decode_disability(row.get('DISABILITY'))

        individual = LegacyIndividual(
            legacy_code=legacy_code,
            import_batch=batch,
            first_name=(first_name or ''),
            middle_name=PssnNormalizationService.trim_name(row.get('MIDDLENAME')),
            last_name=(last_name or ''),
            dob=dob,
            gender=gender,
            disability=disability,
            phone_no=phone_no,
            nin=nin,
            premno=premno,
            location=group.location,
            facility=facility,
            json_ext=_build_individual_json_ext(row, raw_facility_code, facility),
        )
        individual.save(user=user)

        membership = LegacyGroupIndividual(
            group=group,
            individual=individual,
            role=PssnNormalizationService.map_relationship_to_role(rel_code, gender),
            relationship_code=rel_code,
            recipient_type=(
                LegacyGroupIndividual.RecipientType.PRIMARY
                if is_primary_recipient else None
            ),
            member_line=int(member_line_no) if member_line_no.isdigit() else None,
            json_ext=_build_membership_json_ext(row),
        )
        membership.save(user=user)
        success_member += 1

    return {
        'total_households': len(household_df),
        'total_members': len(member_df),
        'success_household_count': success_household,
        'success_member_count': success_member,
        'warning_count': warning_count,
        'error_count': sum(len(v) for v in errors.values()),
        'errors': errors,
    }


def _build_village_cache(household_df: pd.DataFrame) -> Dict[str, Location]:
    """Pre-fetch village Locations for every code in the file."""
    if 'VILLAGE_CODE' not in household_df.columns:
        return {}
    codes = set()
    for raw in household_df['VILLAGE_CODE']:
        normalized = PssnNormalizationService.normalize_code(raw, 'village')
        if normalized:
            codes.add(normalized)
    if not codes:
        return {}
    qs = Location.objects.filter(
        type='V', code__in=codes, validity_to__isnull=True
    )
    return {loc.code: loc for loc in qs}


def _build_facility_cache(member_df: pd.DataFrame) -> Dict[str, HealthFacility]:
    if 'FACILITY_CODE' not in member_df.columns:
        return {}
    codes = {
        (str(c) if c is not None else '').strip()
        for c in member_df['FACILITY_CODE']
        if str(c or '').strip()
    }
    if not codes:
        return {}
    qs = HealthFacility.objects.filter(
        code__in=codes, validity_to__isnull=True
    )
    return {hf.code: hf for hf in qs}


def _extract_head_phones(household_df: pd.DataFrame) -> Dict[str, str]:
    if 'PHONE_NO' not in household_df.columns or 'REGISTRATIONNO' not in household_df.columns:
        return {}
    out: Dict[str, str] = {}
    for _, row in household_df.iterrows():
        reg = (row.get('REGISTRATIONNO') or '').strip()
        phone = (row.get('PHONE_NO') or '').strip()
        if reg and phone:
            out[reg] = phone
    return out


def _build_group_json_ext(
    row: pd.Series,
    village_code: Optional[str],
    location: Optional[Location],
) -> Dict:
    def g(col):
        v = row.get(col)
        return None if v is None or str(v).strip() == '' else str(v).strip()

    head = {
        'first_name': PssnNormalizationService.trim_name(row.get('HH_FIRSTNAME')),
        'middle_name': PssnNormalizationService.trim_name(row.get('HH_MIDDLENAME')),
        'last_name': PssnNormalizationService.trim_name(row.get('HH_LASTNAME')),
        'age': g('AGE'),
        'dob': g('DOB'),
        'popular_name': PssnNormalizationService.trim_name(row.get('POPULAR_HH_NAME')),
    }

    head_correction = {
        'no_change_flag': g('NO_HH_CHANGE'),
        'first_name': PssnNormalizationService.trim_name(row.get('NEW_HH_FIRSTNAME')),
        'middle_name': PssnNormalizationService.trim_name(row.get('NEW_HH_MIDDLENAME')),
        'last_name': PssnNormalizationService.trim_name(row.get('NEW_HH_LASTNAME')),
    }

    location_source = {
        'region_code': PssnNormalizationService.normalize_code(row.get('REGION_CODE'), 'region'),
        'district_code': PssnNormalizationService.normalize_code(row.get('DISTRICT_CODE'), 'district'),
        'ward_code': PssnNormalizationService.normalize_code(row.get('WARD_CODE'), 'ward'),
        'village_code': village_code,
        'urban_or_rural': g('URBANORRULAR'),
        'area_code': g('AREA_CODE'),
        'subvillage': g('SUBVILLAGE'),
        'popular_area': g('POPULAR_AREA'),
    }

    payment = {
        'bank_account': g('BANK_ACCOUNT'),
        'epayment_code': g('EPAYMENT_CODE'),
        'epayment_approach': g('EPAYMENT_APPROACH'),
        'epayment_account': g('EPAYMENT_ACCOUNT'),
        'epayment_bank_branch': g('EPAYMENT_BANK_BRANCH'),
        'epayment_status': g('EPAYMENT_STATUS'),
        'epayment_registered_name': g('EPAYMENT_REGISTERED_NAME'),
        'approved': {
            'epayment_code': g('APR_EPAYMENT_CODE'),
            'epayment_account': g('APR_EPAYMENT_ACCOUNT'),
            'epayment_bank_branch': g('APR_EPAYMENT_BANK_BRANCH'),
            'epayment_approach': g('APR_EPAYMENT_APPROACH'),
            'epayment_registered_name': g('APR_EPAYMENT_REGISTERED_NAME'),
            'date': g('APRROVED_DATE'),
            'by': g('APPROVED_BY'),
        },
    }

    audit = {
        'enrollment_date': g('ENROLLMENT_DATE'),
        'signed_representative': g('SIGNED_REPRESENTATIVE'),
        'supervisor_name': g('SUPERVISOR_NAME'),
        'signed_by_supervisor': g('SIGNED_BY_SUPERVISOR'),
        'data_entry_id': g('DATAENTRYID'),
        'captured_by': g('CAPTUREDBY'),
        'date_captured': g('DATECAPTURED'),
        'updated_by': g('UPDATEDBY'),
        'date_updated': g('DATEUPDATED'),
        'approved_by': g('APPROVEDBY'),
        'date_approved': g('DATEAPPROVED'),
        'reviewed_by': g('REVIEWED_BY'),
        'reviewed_date': g('REVIEWED_DATE'),
        'remarks': g('REMARKS'),
        'v_status': g('V_STATUS'),
    }

    out = {
        'source_uniqueno': g('UNIQUENO'),
        'wave_no': g('WAVENO'),
        'round_no': g('ROUNDNO'),
        'batch_no': g('BATCHNO'),
        'form_no': g('FORMNO'),
        'hh_status': g('HHSTATUS'),
        'hh_size': g('HHSIZE'),
        'pmt_score': PssnNormalizationService.round_decimal(g('PMTSCORE')),
        'hh_classification': g('HHCLASSIFICATION'),
        'phone_no': g('PHONE_NO'),
        'head': {k: v for k, v in head.items() if v},
        'head_correction': {k: v for k, v in head_correction.items() if v},
        'location_source': {k: v for k, v in location_source.items() if v},
        'location_mapping_status': 'resolved' if location else 'unresolved',
        'payment': {k: v for k, v in payment.items() if v},
        'audit': {k: v for k, v in audit.items() if v},
    }
    raw = _collect_raw_columns(row, _HOUSEHOLD_KNOWN_COLUMNS)
    if raw:
        out['raw'] = raw
    return out


def _build_individual_json_ext(
    row: pd.Series,
    raw_facility_code: Optional[str],
    facility: Optional[HealthFacility],
) -> Dict:
    def g(col):
        v = row.get(col)
        return None if v is None or str(v).strip() == '' else str(v).strip()

    nida = {
        'first_name': PssnNormalizationService.trim_name(row.get('NIDA_FIRSTNAME')),
        'middle_name': PssnNormalizationService.trim_name(row.get('NIDA_MIDDLENAME')),
        'last_name': PssnNormalizationService.trim_name(row.get('NIDA_LASTNAME')),
        'dob': g('NIDA_BIRTH_DATE'),
        'expiry_date': g('NIDA_EXPIRY_DATE'),
        'status': g('NIDA_STATUS'),
        'no_nida_reason': g('NO_NIDA_REASON'),
    }

    corrected = {
        'first_name': PssnNormalizationService.trim_name(row.get('NEW_FIRSTNAME')),
        'middle_name': PssnNormalizationService.trim_name(row.get('NEW_MIDDLENAME')),
        'last_name': PssnNormalizationService.trim_name(row.get('NEW_LASTNAME')),
        'age': g('NEW_AGE'),
        'dob': g('NEW_DATEOFBIRTH'),
        'no_change_flag': g('NO_CHANGE'),
    }

    sis = {
        'dob': g('SIS_DOB'),
        'sex': g('SIS_SEX'),
        'school_id': g('SIS_SCHOOL_ID'),
        'sis_id': g('SIS_ID'),
        'photo': g('SIS_PHOTO'),
        'school_code': g('SIS_SCHOOL_CODE'),
        'grade': g('SIS_GRADE'),
        'update_year': g('SIS_UPDATE_YEAR'),
    }

    out = {
        'source_uniqueno': g('UNIQUENO'),
        'source_ref_uniqueno': g('REF_UNIQUENO'),
        'age': g('AGE'),
        'grade': g('GRADE'),
        'disability_level': g('DISLEVEL'),
        'disability_reason': g('DIS_REASON'),
        'chronic_illness': g('CHRONICALILINESS'),
        'prem_status': g('PREM_STATUS'),
        'prem_code': g('PREM_CODE'),
        'source_facility_code': raw_facility_code,
        'source_facility_name': g('FACILITY_NAME'),
        'facility_mapping_status': 'resolved' if facility else (
            'unresolved' if raw_facility_code else None
        ),
        'nida': {k: v for k, v in nida.items() if v},
        'corrected': {k: v for k, v in corrected.items() if v},
        'sis': {k: v for k, v in sis.items() if v},
    }
    raw = _collect_raw_columns(row, _MEMBER_KNOWN_COLUMNS)
    if raw:
        out['raw'] = raw
    return {k: v for k, v in out.items() if v not in (None, '', {}, [])}


def _build_membership_json_ext(row: pd.Series) -> Dict:
    def g(col):
        v = row.get(col)
        return None if v is None or str(v).strip() == '' else str(v).strip()

    out = {
        'corrected_relationship': g('NEW_RELATIONSHIPTOHEAD'),
        'hh_member_status': g('HH_MEMBER_STATUS'),
        'hh_member_exemption': g('HH_MEMBER_EXEMPTION'),
        'service_cat': g('SERVICE_CAT'),
        'v_status': g('V_STATUS'),
    }
    return {k: v for k, v in out.items() if v}


def _collect_raw_columns(row: pd.Series, known_cols: set) -> Dict:
    raw: Dict[str, str] = {}
    for col in row.index:
        if col in known_cols:
            continue
        v = row.get(col)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            raw[col] = s
    return raw
