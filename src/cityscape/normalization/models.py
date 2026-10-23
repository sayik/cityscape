"""Canonical Data Schema as the Single Source of Truth (CORE-01).

Defines the ``CanonicalRecord`` envelope with common meta fields (Geo,
timestamp, source, license, tier, attribution) plus an interchangeable payload union defined via the
``kind`` field. License and Tier are required fields
(no default) to ensure that no record enters the system without a Tier tag
(GOV Foundation). ``extra=“forbid”`` rejects silent additional fields, thereby
detecting mapper typos early on.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import orjson
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from cityscape.normalization.enums import LicenseId, LicenseTier, SourceId
from cityscape.normalization.payloads import PayloadUnion

# Version of the canonical schema. Incremental schema changes increment this
# constant (ARCH-02 reproducibility): a record thus carries
# the schema version under which it was created. Deliberately NOT part of
# ``content_hash`` (deduplication should remain stable across version boundaries).
SCHEMA_VERSION = 1


class GeoPoint(BaseModel):
    """Geocoordinate with declarative value range validation (value object)."""

    model_config = ConfigDict(frozen=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Attribution(BaseModel):
    """Exact citation of the name plus optional license URL (attribution required)."""

    model_config = ConfigDict(frozen=True)

    text: str
    license_url: str | None = None
    modified: bool = False


class CanonicalRecord(BaseModel):
    """Uniform envelope for each normalized city dataset.

    Contains the common meta fields from each source plus a payload
    discriminated by ``kind``. ``license_tier`` is required (no default) to ensure
    that no dataset is created without a tier tag. ``extra=“forbid”`` prevents silent
    additional fields.

    Identity (ARCH-02): ``schema_version`` specifies the schema version;
    ``record_id`` and ``content_hash`` are ``computed_field`` values derived deterministically from the record data
    (no mapper sets them manually). ``ags``
    and ``wikidata_qid`` are join keys to official and Wikidata identifiers, respectively.

    Security: ``ags`` is a data-only field (official municipality code).
    It must NEVER be used as a path segment in a store (T-06.6-02); the
    store paths use only the slug/tier allowlist. ``record_id`` and
    ``content_hash`` include ONLY open user data that is already in the envelope
    anyway, no secrets/PII (T-06.6-04, ASVS L1) — all fields are open data.
"""

    model_config = ConfigDict(extra="forbid")

    city_slug: str
    geo: GeoPoint | None = None
    observed_at: datetime | None = None
    retrieved_at: datetime
    source: SourceId
    license_id: LicenseId
    license_tier: LicenseTier
    schema_version: int = SCHEMA_VERSION
    ags: str | None = None
    wikidata_qid: str | None = None
    attribution: Attribution
    payload: PayloadUnion

    @model_validator(mode="after")
    def _normalize_observed_at_utc(self) -> CanonicalRecord:
        """Treats ``observed_at`` canonically as timezone-aware UTC.

        Naive time (without tzinfo) is interpreted as UTC; timezone-aware time is converted to UTC;
        ``None`` remains ``None``. Guarantees comparable timestamps
        across all sources (ARCH-02).
        """
        if self.observed_at is not None:
            if self.observed_at.tzinfo is None:
                object.__setattr__(
                    self, "observed_at", self.observed_at.replace(tzinfo=UTC)
                )
            else:
                object.__setattr__(
                    self, "observed_at", self.observed_at.astimezone(UTC)
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        """Deterministic hash of the raw payload (deduplication key).

        Intentionally excludes ``retrieved_at``, ``record_id``, ``content_hash``, AND
        ``schema_version``: two retrievals of the same payload (with different
        ``retrieved_at`` values) or an incremental schema update must NOT
        NOT change the dedup hash (T-06.6-03). Canonical via
        ``orjson.OPT_SORT_KEYS`` (dict-order-independent) + sha256.
        """
        payload = {
            "city_slug": self.city_slug,
            "geo": self.geo.model_dump(mode="json") if self.geo else None,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source": self.source.value,
            "license_id": self.license_id.value,
            "license_tier": self.license_tier.value,
            "attribution": self.attribution.model_dump(mode="json"),
            "payload": self.payload.model_dump(mode="json"),
            "ags": self.ags,
            "wikidata_qid": self.wikidata_qid,
        }
        canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(canonical).hexdigest()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_id(self) -> str:
        """Deterministic identity of a record (stable primary key).

        Stable key consisting of source, city, time anchor (``observed_at`` if
        set, otherwise ``retrieved_at`` -- static sources do not have a
        ``observed_at``), payload ``kind``, and the domain-specific key
        (``station_id``/``stop_id``/``poi_type``). Same input -> same ID;
        different ``observed_at`` or different domain-specific key -> different ID.
        Canonicalized via ``orjson.OPT_SORT_KEYS`` + sha256 (T-06.6-03).
        """
        anchor = self.observed_at if self.observed_at else self.retrieved_at
        business_key = (
            getattr(self.payload, "station_id", None)
            or getattr(self.payload, "stop_id", None)
            or getattr(self.payload, "poi_type", None)
        )
        key = {
            "source": self.source.value,
            "city_slug": self.city_slug,
            "anchor": anchor.isoformat() if anchor else None,
            "kind": self.payload.kind,
            "business_key": business_key,
        }
        canonical = orjson.dumps(key, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(canonical).hexdigest()
