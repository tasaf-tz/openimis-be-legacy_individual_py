"""Legacy PSSN API rows -> (household_df, member_df) for ``_import_paired``.

See docs/LEGACY_API_ETL_CODE_RATIONALE.md.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from legacy_individual.columns import to_household_column, to_member_column

logger = logging.getLogger(__name__)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


class LegacyPssnApiAdapter:
    def split(
        self, rows: Iterable[Dict[str, Any]]
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        household_by_regno: Dict[str, Dict[str, str]] = {}
        member_rows: List[Dict[str, str]] = []
        seen_member_keys = set()
        duplicate_members = 0

        for raw in rows:
            if not isinstance(raw, dict):
                continue

            household: Dict[str, str] = {}
            member: Dict[str, str] = {}
            for api_key, value in raw.items():
                hh_col = to_household_column(api_key)
                if hh_col is not None:
                    household[hh_col] = _clean(value)
                    continue
                mem_col = to_member_column(api_key)
                if mem_col is not None:
                    member[mem_col] = _clean(value)

            regno = (household.get("REGISTRATIONNO") or "").strip()
            if regno and regno not in household_by_regno:
                household_by_regno[regno] = household

            if not member:
                continue

            m_regno = (member.get("REGISTRATIONNO") or "").strip()
            m_line = (member.get("MEMBERLINENO") or "").strip()
            if m_regno and m_line:
                key = (m_regno, m_line)
                if key in seen_member_keys:
                    duplicate_members += 1
                    continue
                seen_member_keys.add(key)
            member_rows.append(member)

        household_rows = list(household_by_regno.values())

        logger.info(
            "LegacyPssnApiAdapter: %s households, %s members from combined rows "
            "(%s duplicate member rows dropped)",
            len(household_rows),
            len(member_rows),
            duplicate_members,
        )

        return self._to_frame(household_rows), self._to_frame(member_rows)

    @staticmethod
    def _to_frame(rows: List[Dict[str, str]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).fillna("").astype(str)
