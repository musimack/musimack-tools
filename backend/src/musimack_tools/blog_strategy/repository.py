"""Durable BS-01 repository with optimistic concurrency and audit events."""

# ruff: noqa: ANN401 - Repository runtime/session protocols are injected SQLAlchemy objects.

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from musimack_tools.persistence.blog_strategy_models import (
    BlogStrategyEventModel,
    BlogStrategyOverlapModel,
    BlogStrategyPageModel,
    BlogStrategyProjectModel,
    BlogStrategyTopicFamilyModel,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class BlogStrategyRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def create_project(self, values: dict[str, Any], actor: str | None) -> dict[str, Any]:
        now = _now()
        row = BlogStrategyProjectModel(
            project_id=_id("bsp"),
            created_at=now,
            updated_at=now,
            revision=1,
            **values,
        )
        with self._runtime.transaction() as session:
            session.add(row)
            session.flush()
            self._event(session, row.project_id, "project_created", row.project_id, actor)
        return self.project(row.project_id)

    def projects(self) -> list[dict[str, Any]]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(BlogStrategyProjectModel).order_by(
                    BlogStrategyProjectModel.updated_at.desc(),
                    BlogStrategyProjectModel.project_id,
                )
            ).all()
            return [self._project(row, session) for row in rows]

    def project(self, project_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyProjectModel, project_id)
            if row is None:
                raise ValueError("blog_strategy_project_not_found")
            return self._project(row, session)

    def update_project(
        self, project_id: str, values: dict[str, Any], revision: int, actor: str | None
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyProjectModel, project_id)
            if row is None:
                raise ValueError("blog_strategy_project_not_found")
            self._revision(row.revision, revision)
            for key, value in values.items():
                setattr(row, key, value)
            row.revision += 1
            row.updated_at = _now()
            self._event(session, project_id, "project_updated", project_id, actor)
        return self.project(project_id)

    def add_page(
        self, project_id: str, values: dict[str, Any], actor: str | None
    ) -> dict[str, Any]:
        self.project(project_id)
        now = _now()
        row = BlogStrategyPageModel(
            page_id=_id("bpg"),
            project_id=project_id,
            revision=1,
            created_at=now,
            updated_at=now,
            **values,
        )
        try:
            with self._runtime.transaction() as session:
                session.add(row)
                session.flush()
                self._event(session, project_id, "page_added", row.page_id, actor)
        except IntegrityError:
            raise ValueError("blog_strategy_duplicate_url") from None
        return self.page(project_id, row.page_id)

    def pages(self, project_id: str) -> list[dict[str, Any]]:
        self.project(project_id)
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(BlogStrategyPageModel)
                .where(BlogStrategyPageModel.project_id == project_id)
                .order_by(BlogStrategyPageModel.normalized_url, BlogStrategyPageModel.page_id)
            ).all()
            return [self._page(row) for row in rows]

    def page(self, project_id: str, page_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyPageModel, page_id)
            if row is None or row.project_id != project_id:
                raise ValueError("blog_strategy_page_not_found")
            return self._page(row)

    def update_page(
        self,
        project_id: str,
        page_id: str,
        values: dict[str, Any],
        revision: int,
        actor: str | None,
    ) -> dict[str, Any]:
        try:
            with self._runtime.transaction() as session:
                row = session.get(BlogStrategyPageModel, page_id)
                if row is None or row.project_id != project_id:
                    raise ValueError("blog_strategy_page_not_found")
                self._revision(row.revision, revision)
                for key, value in values.items():
                    setattr(row, key, value)
                row.revision += 1
                row.updated_at = _now()
                self._event(session, project_id, "page_updated", page_id, actor)
                session.flush()
        except IntegrityError:
            raise ValueError("blog_strategy_duplicate_url") from None
        return self.page(project_id, page_id)

    def create_family(
        self, project_id: str, values: dict[str, Any], actor: str | None
    ) -> dict[str, Any]:
        self.project(project_id)
        now = _now()
        row = BlogStrategyTopicFamilyModel(
            family_id=_id("btf"),
            project_id=project_id,
            revision=1,
            created_at=now,
            updated_at=now,
            **values,
        )
        try:
            with self._runtime.transaction() as session:
                session.add(row)
                session.flush()
                self._event(session, project_id, "topic_family_created", row.family_id, actor)
        except IntegrityError:
            raise ValueError("blog_strategy_topic_family_conflict") from None
        return self.family(project_id, row.family_id)

    def families(self, project_id: str) -> list[dict[str, Any]]:
        self.project(project_id)
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(BlogStrategyTopicFamilyModel)
                .where(BlogStrategyTopicFamilyModel.project_id == project_id)
                .order_by(BlogStrategyTopicFamilyModel.name, BlogStrategyTopicFamilyModel.family_id)
            ).all()
            return [self._family(row) for row in rows]

    def family(self, project_id: str, family_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyTopicFamilyModel, family_id)
            if row is None or row.project_id != project_id:
                raise ValueError("blog_strategy_topic_family_not_found")
            return self._family(row)

    def update_family(
        self,
        project_id: str,
        family_id: str,
        values: dict[str, Any],
        revision: int,
        actor: str | None,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyTopicFamilyModel, family_id)
            if row is None or row.project_id != project_id:
                raise ValueError("blog_strategy_topic_family_not_found")
            self._revision(row.revision, revision)
            for key, value in values.items():
                setattr(row, key, value)
            row.revision += 1
            row.updated_at = _now()
            self._event(session, project_id, "topic_family_updated", family_id, actor)
        return self.family(project_id, family_id)

    def merge_family(
        self,
        project_id: str,
        source_id: str,
        destination_id: str,
        revision: int,
        actor: str | None,
    ) -> dict[str, Any]:
        if source_id == destination_id:
            raise ValueError("blog_strategy_topic_family_merge_invalid")
        with self._runtime.transaction() as session:
            source = session.get(BlogStrategyTopicFamilyModel, source_id)
            destination = session.get(BlogStrategyTopicFamilyModel, destination_id)
            if any(row is None or row.project_id != project_id for row in (source, destination)):
                raise ValueError("blog_strategy_topic_family_not_found")
            self._revision(source.revision, revision)
            pages = session.scalars(
                select(BlogStrategyPageModel).where(BlogStrategyPageModel.family_id == source_id)
            ).all()
            for page in pages:
                page.family_id = destination_id
                page.revision += 1
                page.updated_at = _now()
            source.status = "merged"
            source.merged_into_family_id = destination_id
            source.revision += 1
            source.updated_at = _now()
            self._event(session, project_id, "topic_family_merged", source_id, actor)
        return self.family(project_id, source_id)

    def create_overlap(
        self, project_id: str, values: dict[str, Any], actor: str | None
    ) -> dict[str, Any]:
        self.project(project_id)
        now = _now()
        row = BlogStrategyOverlapModel(
            overlap_id=_id("bov"),
            project_id=project_id,
            revision=1,
            created_at=now,
            updated_at=now,
            **values,
        )
        with self._runtime.transaction() as session:
            session.add(row)
            session.flush()
            self._event(session, project_id, "overlap_created", row.overlap_id, actor)
        return self.overlap(project_id, row.overlap_id)

    def overlaps(self, project_id: str) -> list[dict[str, Any]]:
        self.project(project_id)
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(BlogStrategyOverlapModel)
                .where(BlogStrategyOverlapModel.project_id == project_id)
                .order_by(BlogStrategyOverlapModel.created_at, BlogStrategyOverlapModel.overlap_id)
            ).all()
            return [self._overlap(row) for row in rows]

    def overlap(self, project_id: str, overlap_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyOverlapModel, overlap_id)
            if row is None or row.project_id != project_id:
                raise ValueError("blog_strategy_overlap_not_found")
            return self._overlap(row)

    def update_overlap(
        self,
        project_id: str,
        overlap_id: str,
        values: dict[str, Any],
        revision: int,
        actor: str | None,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.get(BlogStrategyOverlapModel, overlap_id)
            if row is None or row.project_id != project_id:
                raise ValueError("blog_strategy_overlap_not_found")
            self._revision(row.revision, revision)
            for key, value in values.items():
                setattr(row, key, value)
            row.revision += 1
            row.updated_at = _now()
            self._event(session, project_id, "overlap_updated", overlap_id, actor)
        return self.overlap(project_id, overlap_id)

    def events(self, project_id: str) -> list[dict[str, Any]]:
        self.project(project_id)
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(BlogStrategyEventModel)
                .where(BlogStrategyEventModel.project_id == project_id)
                .order_by(BlogStrategyEventModel.occurred_at, BlogStrategyEventModel.event_id)
            ).all()
            return [
                {
                    "event_id": row.event_id,
                    "project_id": row.project_id,
                    "event_type": row.event_type,
                    "entity_id": row.entity_id,
                    "actor": row.actor,
                    "details": json.loads(row.details_json),
                    "occurred_at": row.occurred_at,
                }
                for row in rows
            ]

    @staticmethod
    def _revision(actual: int, expected: int) -> None:
        if actual != expected:
            raise ValueError("blog_strategy_revision_conflict")

    @staticmethod
    def _event(session: Any, project_id: str, kind: str, entity_id: str, actor: str | None) -> None:
        session.add(
            BlogStrategyEventModel(
                event_id=_id("bev"),
                project_id=project_id,
                event_type=kind,
                entity_id=entity_id,
                actor=actor,
                details_json="{}",
                occurred_at=_now(),
            )
        )

    @staticmethod
    def _project(row: BlogStrategyProjectModel, session: Any) -> dict[str, Any]:
        pages = session.scalars(
            select(BlogStrategyPageModel).where(BlogStrategyPageModel.project_id == row.project_id)
        ).all()
        families = session.scalars(
            select(BlogStrategyTopicFamilyModel).where(
                BlogStrategyTopicFamilyModel.project_id == row.project_id
            )
        ).all()
        overlaps = session.scalars(
            select(BlogStrategyOverlapModel).where(
                BlogStrategyOverlapModel.project_id == row.project_id
            )
        ).all()
        return {
            "project_id": row.project_id,
            "client_name": row.client_name,
            "primary_website": row.primary_website,
            "normalized_origin": row.normalized_origin,
            "primary_market": row.primary_market,
            "service_area_notes": row.service_area_notes,
            "core_services": json.loads(row.core_services_json),
            "important_pages": json.loads(row.important_pages_json),
            "compliance_notes": row.compliance_notes,
            "status": row.status,
            "revision": row.revision,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "counts": {
                "included_pages": sum(page.inclusion_state == "included" for page in pages),
                "classified_pages": sum(page.human_reviewed for page in pages),
                "topic_families": sum(family.status == "active" for family in families),
                "open_overlaps": sum(overlap.review_state == "open" for overlap in overlaps),
                "approved_decisions": sum(page.approved for page in pages),
            },
        }

    @staticmethod
    def _page(row: BlogStrategyPageModel) -> dict[str, Any]:
        result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        result["secondary_topics"] = json.loads(result.pop("secondary_topics_json"))
        result["provenance"] = json.loads(result.pop("provenance_json"))
        return result

    @staticmethod
    def _family(row: BlogStrategyTopicFamilyModel) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    @staticmethod
    def _overlap(row: BlogStrategyOverlapModel) -> dict[str, Any]:
        result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        result["page_ids"] = json.loads(result.pop("page_ids_json"))
        return result
