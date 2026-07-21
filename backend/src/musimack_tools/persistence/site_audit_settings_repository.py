"""SQLAlchemy repository for bounded CSA-02 settings and site-profile versions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from musimack_tools.domain.site_audit_settings import (
    SITE_AUDIT_PROFILE_VERSION,
    SITE_AUDIT_SETTINGS_VERSION,
    ProfileState,
    SiteAuditSettingsError,
    canonical_json,
    stable_hash,
)
from musimack_tools.persistence.site_audit_settings_models import (
    SiteAuditGlobalSettingsVersionModel,
    SiteAuditProfileModel,
    SiteAuditProfileVersionModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from musimack_tools.persistence.engine import PersistenceRuntime


class SQLAlchemySiteAuditSettingsRepository:
    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime

    def latest_global_settings(self) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.execute(
                select(SiteAuditGlobalSettingsVersionModel)
                .order_by(SiteAuditGlobalSettingsVersionModel.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            return _global_record(row) if row else None

    def global_settings_version(self, version: int) -> dict[str, Any] | None:
        """Return one immutable global-settings version without falling forward."""

        if version == 0:
            return None
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditGlobalSettingsVersionModel, version)
            return _global_record(row) if row else None

    def append_global_settings(
        self, configuration: dict[str, Any], *, expected_version: int, created_by: str
    ) -> dict[str, Any]:
        encoded = canonical_json(configuration)
        digest = stable_hash(configuration)
        now = datetime.now(UTC)
        try:
            with self._runtime.transaction() as session:
                current = session.execute(
                    select(func.max(SiteAuditGlobalSettingsVersionModel.version))
                ).scalar_one()
                actual = int(current or 0)
                if actual != expected_version:
                    raise SiteAuditSettingsError(
                        "site_audit_settings_version_conflict",
                        "Global settings changed; reload before saving.",
                    )
                row = SiteAuditGlobalSettingsVersionModel(
                    version=actual + 1,
                    configuration_json=encoded,
                    configuration_hash=digest,
                    created_by=created_by,
                    created_at=now,
                    settings_version=SITE_AUDIT_SETTINGS_VERSION,
                )
                session.add(row)
                session.flush()
                return _global_record(row)
        except IntegrityError as error:
            raise SiteAuditSettingsError(
                "site_audit_settings_conflict", "Global settings already have this configuration."
            ) from error

    def profiles(
        self, *, include_disabled: bool, offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        statement = select(SiteAuditProfileModel).order_by(
            SiteAuditProfileModel.site_label.asc(), SiteAuditProfileModel.profile_id.asc()
        )
        if not include_disabled:
            statement = statement.where(SiteAuditProfileModel.state == ProfileState.ENABLED.value)
        statement = statement.offset(offset).limit(limit)
        with self._runtime.transaction() as session:
            rows = session.execute(statement).scalars().all()
            return tuple(self._profile_record(session, row) for row in rows)

    def profile_count(self, *, include_disabled: bool) -> int:
        statement = select(func.count()).select_from(SiteAuditProfileModel)
        if not include_disabled:
            statement = statement.where(SiteAuditProfileModel.state == ProfileState.ENABLED.value)
        with self._runtime.transaction() as session:
            return int(session.execute(statement).scalar_one())

    def profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditProfileModel, profile_id)
            return self._profile_record(session, row) if row else None

    def profile_versions(self, profile_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.execute(
                select(SiteAuditProfileVersionModel)
                .where(SiteAuditProfileVersionModel.profile_id == profile_id)
                .order_by(SiteAuditProfileVersionModel.version.desc())
            ).scalars()
            return tuple(_profile_version_record(row) for row in rows)

    def profile_version(self, profile_id: str, version: int) -> dict[str, Any] | None:
        """Return one immutable profile version without substituting the latest version."""

        with self._runtime.transaction() as session:
            row = session.execute(
                select(SiteAuditProfileVersionModel).where(
                    SiteAuditProfileVersionModel.profile_id == profile_id,
                    SiteAuditProfileVersionModel.version == version,
                )
            ).scalar_one_or_none()
            return _profile_version_record(row) if row else None

    def create_profile(
        self,
        profile_id: str,
        configuration: dict[str, Any],
        *,
        created_by: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        encoded = canonical_json(configuration)
        digest = stable_hash(configuration)
        seed_host = str(urlsplit(str(configuration["authorized_seed"])).hostname)
        try:
            with self._runtime.transaction() as session:
                row = SiteAuditProfileModel(
                    profile_id=profile_id,
                    site_label=str(configuration["site_label"]),
                    authorized_seed=str(configuration["authorized_seed"]),
                    seed_host=seed_host,
                    state=ProfileState.ENABLED.value,
                    current_version=1,
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.add(
                    SiteAuditProfileVersionModel(
                        profile_id=profile_id,
                        version=1,
                        configuration_json=encoded,
                        configuration_hash=digest,
                        created_by=created_by,
                        created_at=now,
                        profile_version=SITE_AUDIT_PROFILE_VERSION,
                    )
                )
                session.flush()
                return self._profile_record(session, row)
        except IntegrityError as error:
            raise SiteAuditSettingsError(
                "site_profile_conflict", "Site profile already exists."
            ) from error

    def update_profile(
        self,
        profile_id: str,
        configuration: dict[str, Any],
        *,
        expected_version: int,
        created_by: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        digest = stable_hash(configuration)
        try:
            with self._runtime.transaction() as session:
                row = session.get(SiteAuditProfileModel, profile_id)
                if row is None:
                    raise SiteAuditSettingsError(
                        "site_profile_not_found", "Site profile was not found."
                    )
                if row.current_version != expected_version:
                    raise SiteAuditSettingsError(
                        "site_profile_version_conflict",
                        "Site profile changed; reload before saving.",
                    )
                if row.state == ProfileState.ARCHIVED.value:
                    raise SiteAuditSettingsError(
                        "site_profile_archived", "Archived site profiles cannot be edited."
                    )
                next_version = row.current_version + 1
                session.add(
                    SiteAuditProfileVersionModel(
                        profile_id=profile_id,
                        version=next_version,
                        configuration_json=canonical_json(configuration),
                        configuration_hash=digest,
                        created_by=created_by,
                        created_at=now,
                        profile_version=SITE_AUDIT_PROFILE_VERSION,
                    )
                )
                row.site_label = str(configuration["site_label"])
                row.authorized_seed = str(configuration["authorized_seed"])
                row.seed_host = str(urlsplit(str(configuration["authorized_seed"])).hostname)
                row.current_version = next_version
                row.updated_at = now
                session.flush()
                return self._profile_record(session, row)
        except IntegrityError as error:
            raise SiteAuditSettingsError(
                "site_profile_conflict", "Site profile already has this configuration."
            ) from error

    def set_profile_state(self, profile_id: str, state: ProfileState) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditProfileModel, profile_id)
            if row is None:
                raise SiteAuditSettingsError(
                    "site_profile_not_found", "Site profile was not found."
                )
            if row.state == ProfileState.ARCHIVED.value and state is not ProfileState.ARCHIVED:
                raise SiteAuditSettingsError(
                    "site_profile_archived", "Archived site profiles cannot be re-enabled."
                )
            row.state = state.value
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._profile_record(session, row)

    @staticmethod
    def _profile_record(session: Session, row: SiteAuditProfileModel) -> dict[str, Any]:
        version = session.execute(
            select(SiteAuditProfileVersionModel).where(
                SiteAuditProfileVersionModel.profile_id == row.profile_id,
                SiteAuditProfileVersionModel.version == row.current_version,
            )
        ).scalar_one()
        return {
            "profile_id": row.profile_id,
            "site_label": row.site_label,
            "authorized_seed": row.authorized_seed,
            "seed_host": row.seed_host,
            "state": row.state,
            "current_version": row.current_version,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "configuration": json.loads(version.configuration_json),
            "configuration_hash": version.configuration_hash,
            "profile_version": version.profile_version,
        }


def _global_record(row: SiteAuditGlobalSettingsVersionModel) -> dict[str, Any]:
    return {
        "version": row.version,
        "configuration": json.loads(row.configuration_json),
        "configuration_hash": row.configuration_hash,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "settings_version": row.settings_version,
    }


def _profile_version_record(row: SiteAuditProfileVersionModel) -> dict[str, Any]:
    return {
        "profile_id": row.profile_id,
        "version": row.version,
        "configuration": json.loads(row.configuration_json),
        "configuration_hash": row.configuration_hash,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "profile_version": row.profile_version,
    }
