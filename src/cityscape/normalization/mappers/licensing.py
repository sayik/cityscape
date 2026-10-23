"""Per-record license mapper `map_license` (GOV-04 Core, T-10-CONTAM).

Pure function ``map_license(raw) -> (LicenseId, LicenseTier)``: maps a
raw license string (or license URL) deterministically to the existing
``LicenseId``/``LicenseTier`` enum pair. It is the single source of
truth for the license->tier mapping (REST Rule 6) and is called by the
destination.one mapper PRO Record (D-05).

SECURITY-CRITICAL CHECK ORDER (Pitfall 1, GOV-04): ShareAlike is checked BEFORE
CC-BY. Otherwise, “cc-by-sa-4.0” would be incorrectly matched as “cc-by,” and a
Copyleft record (Tier B) would be tagged as Tier A and contaminate the
product. Empty/None/unknown -> Tier C (fail-safe, NEVER Tier A).

Clean: no system clock, no I/O, no log calls.
"""

from __future__ import annotations

from cityscape.normalization import LicenseId, LicenseTier


def map_license(raw: str | None) -> tuple[LicenseId, LicenseTier]:
    s = (raw or "").lower().replace("-", " ").replace("_", " ").strip()
    if not s:
        return LicenseId.UNKNOWN, LicenseTier.C
    is_cc = "cc" in s or "creativecommons" in s
    if is_cc and ("by sa" in s):
        return LicenseId.CC_BY_SA_4_0, LicenseTier.B
    if "dl de" in s and "zero" in s:
        return LicenseId.DL_DE_ZERO_2_0, LicenseTier.A
    if "dl de" in s:
        return LicenseId.DL_DE_BY_2_0, LicenseTier.A
    if "cc0" in s or "zero" in s or "publicdomain" in s:
        return LicenseId.CC0, LicenseTier.A
    if is_cc and "by nd" in s:
        return LicenseId.UNKNOWN, LicenseTier.C
    if is_cc and "by" in s:  
        return LicenseId.CC_BY_4_0, LicenseTier.A