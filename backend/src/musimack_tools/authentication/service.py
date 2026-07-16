"""Explicit, transaction-bounded user, password, session, and audit service."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from musimack_tools.domain.authentication import (
    AUTH_AUDIT_VERSION,
    AUTHENTICATION_VERSION,
    SESSION_TOKEN_ALGORITHM,
    SESSION_VERSION,
    AuthenticatedPrincipal,
    AuthenticationConfiguration,
    AuthenticationDiagnostics,
    AuthenticationMethod,
    AuthenticationMode,
    PasswordHash,
    PrincipalType,
    UserRole,
    UserState,
    normalize_email,
    permissions_for_role,
    validate_password,
)
from musimack_tools.persistence.auth_models import (
    AuthenticationAuditEventModel,
    AuthenticationSessionModel,
    LoginAttemptModel,
    UserCredentialModel,
    UserModel,
)
from musimack_tools.security.passwords import (
    hash_password,
    new_session_token,
    session_token_hash,
    verify_password,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

_MAXIMUM_PAGE_SIZE = 100
_MAXIMUM_CLEANUP_ROWS = 10_000
_MAXIMUM_DISPLAY_NAME = 128
_CONTROL_CHARACTER_BOUNDARY = 32
_SESSION_TOKEN_VERSION = "session-token-v1"  # noqa: S105 - version identifier.
_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Stable expected authentication failure without secret-bearing details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class IssuedSession:
    principal: AuthenticatedPrincipal
    raw_token: str


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    email: str
    display_name: str
    state: UserState
    role: UserRole
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    authentication_method: str
    current: bool
    revoked: bool
    client_label: str | None


class AuthenticationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        configuration: AuthenticationConfiguration,
    ) -> None:
        self._sessions = session_factory
        self.configuration = configuration

    def bootstrap_administrator(self, email: str, display_name: str, password: str) -> UserRecord:
        with self._sessions.begin() as database:
            existing = database.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.role == UserRole.ADMINISTRATOR.value)
            )
            if existing:
                raise AuthenticationError("authentication_bootstrap_already_completed")
            user = self._create_user(
                database, email, display_name, UserRole.ADMINISTRATOR, password, UserState.ACTIVE
            )
            self._audit(database, "user_bootstrapped", target_user_id=user.user_id)
            return _user_record(user)

    def create_user(  # noqa: PLR0913 - explicit administrative contract.
        self,
        email: str,
        display_name: str,
        role: UserRole,
        password: str,
        state: UserState = UserState.INACTIVE,
        *,
        actor: AuthenticatedPrincipal | None = None,
    ) -> UserRecord:
        with self._sessions.begin() as database:
            try:
                user = self._create_user(database, email, display_name, role, password, state)
                self._audit(
                    database,
                    "user_created",
                    actor=actor,
                    target_user_id=user.user_id,
                    role=role.value,
                )
                return _user_record(user)
            except IntegrityError:
                raise AuthenticationError("user_email_conflict") from None

    def list_users(self, *, limit: int = 50, offset: int = 0) -> tuple[UserRecord, ...]:
        if not 1 <= limit <= _MAXIMUM_PAGE_SIZE or offset < 0:
            raise AuthenticationError("user_page_invalid")
        with self._sessions() as database:
            rows = database.scalars(
                select(UserModel)
                .order_by(UserModel.normalized_email, UserModel.user_id)
                .limit(limit)
                .offset(offset)
            )
            return tuple(_user_record(row) for row in rows)

    def get_user(self, user_id: str) -> UserRecord:
        with self._sessions() as database:
            user = database.get(UserModel, user_id)
            if user is None:
                raise AuthenticationError("user_not_found")
            return _user_record(user)

    def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        actor: AuthenticatedPrincipal | None = None,
    ) -> UserRecord:
        with self._sessions.begin() as database:
            user = self._require_user(database, user_id)
            if email is not None:
                user.email = email.strip()
                user.normalized_email = normalize_email(email)
            if display_name is not None:
                user.display_name = _display_name(display_name)
            user.updated_at = _now()
            self._audit(database, "user_updated", actor=actor, target_user_id=user_id)
            try:
                database.flush()
            except IntegrityError:
                raise AuthenticationError("user_email_conflict") from None
            return _user_record(user)

    def set_user_state(
        self, user_id: str, state: UserState, *, actor: AuthenticatedPrincipal | None = None
    ) -> UserRecord:
        with self._sessions.begin() as database:
            user = self._require_user(database, user_id)
            if user.state == state.value:
                return _user_record(user)
            user.state = state.value
            user.updated_at = _now()
            user.disabled_at = user.updated_at if state is UserState.DISABLED else None
            if state is not UserState.ACTIVE:
                user.session_revocation_generation += 1
                self._revoke_user_sessions(database, user_id, f"user_{state.value}")
            event = {
                UserState.ACTIVE: "user_activated",
                UserState.INACTIVE: "user_deactivated",
                UserState.DISABLED: "user_disabled",
            }[state]
            self._audit(database, event, actor=actor, target_user_id=user_id)
            return _user_record(user)

    def change_role(
        self, user_id: str, role: UserRole, *, actor: AuthenticatedPrincipal | None = None
    ) -> UserRecord:
        with self._sessions.begin() as database:
            user = self._require_user(database, user_id)
            if user.role != role.value:
                user.role = role.value
                user.updated_at = _now()
                user.session_revocation_generation += 1
                self._revoke_user_sessions(database, user_id, "role_changed")
                self._audit(
                    database,
                    "user_role_changed",
                    actor=actor,
                    target_user_id=user_id,
                    role=role.value,
                )
            return _user_record(user)

    def sign_in(self, email: str, password: str, *, client_key: str = "unknown") -> IssuedSession:
        if (
            not self.configuration.enabled
            or self.configuration.mode is AuthenticationMode.SHARED_BEARER
        ):
            raise AuthenticationError("authentication_disabled")
        normalized = _safe_normalized_email(email)
        now = _now()
        client_hash = hashlib.sha256(client_key.encode("utf-8")).hexdigest()
        with self._sessions() as database:
            cutoff = now - timedelta(seconds=self.configuration.login_rate_limit_window_seconds)
            recent = database.scalar(
                select(func.count())
                .select_from(LoginAttemptModel)
                .where(
                    LoginAttemptModel.occurred_at >= cutoff,
                    or_(
                        LoginAttemptModel.normalized_account == normalized,
                        LoginAttemptModel.client_key_hash == client_hash,
                    ),
                )
            )
            if recent is not None and recent >= self.configuration.login_rate_limit_max_attempts:
                self._audit(database, "sign_in_failed", reason="authentication_rate_limited")
                database.commit()
                raise AuthenticationError("authentication_rate_limited")
            user = database.scalar(
                select(UserModel).where(UserModel.normalized_email == normalized)
            )
            credential = database.get(UserCredentialModel, user.user_id) if user else None
            valid = credential is not None and verify_password(password, _password_hash(credential))
            database.add(
                LoginAttemptModel(
                    normalized_account=normalized,
                    client_key_hash=client_hash,
                    succeeded=bool(valid and user and user.state == UserState.ACTIVE.value),
                    occurred_at=now,
                )
            )
            if user is None or not valid:
                if user is not None:
                    user.failed_login_count += 1
                    user.last_failed_login_at = now
                    if user.failed_login_count >= self.configuration.password_max_failed_attempts:
                        user.lockout_until = now + timedelta(
                            minutes=self.configuration.password_lockout_minutes
                        )
                        self._audit(database, "account_locked", target_user_id=user.user_id)
                self._audit(database, "sign_in_failed", reason="authentication_invalid_credentials")
                database.commit()
                raise AuthenticationError("authentication_invalid_credentials")
            if user.state != UserState.ACTIVE.value:
                self._audit(
                    database,
                    "sign_in_failed",
                    target_user_id=user.user_id,
                    reason="authentication_invalid_credentials",
                )
                database.commit()
                raise AuthenticationError("authentication_invalid_credentials")
            if user.lockout_until is not None and _aware(user.lockout_until) > now:
                self._audit(
                    database,
                    "sign_in_failed",
                    target_user_id=user.user_id,
                    reason="authentication_account_locked",
                )
                database.commit()
                raise AuthenticationError("authentication_account_locked")
            user.failed_login_count = 0
            user.lockout_until = None
            user.last_successful_login_at = now
            self._enforce_session_cap(database, user.user_id, now)
            issued = self._issue_session(database, user, now, client_key)
            self._audit(
                database,
                "sign_in_succeeded",
                target_user_id=user.user_id,
                session_id=issued.principal.session_id,
            )
            self._audit(
                database,
                "session_created",
                target_user_id=user.user_id,
                session_id=issued.principal.session_id,
            )
            database.commit()
            return issued

    def authenticate_session(self, raw_token: str) -> AuthenticatedPrincipal:
        return self.authenticate_and_rotate(raw_token, rotate=False).principal

    def authenticate_and_rotate(self, raw_token: str, *, rotate: bool = True) -> IssuedSession:
        if (
            not self.configuration.enabled
            or self.configuration.mode is AuthenticationMode.SHARED_BEARER
        ):
            raise AuthenticationError("authentication_disabled")
        try:
            token_hash = session_token_hash(raw_token)
        except ValueError:
            raise AuthenticationError("authentication_session_invalid") from None
        now = _now()
        with self._sessions.begin() as database:
            row = database.scalar(
                select(AuthenticationSessionModel).where(
                    AuthenticationSessionModel.token_hash == token_hash
                )
            )
            if row is None:
                raise AuthenticationError("authentication_session_invalid")
            user = database.get(UserModel, row.user_id)
            if row.revoked_at is not None:
                raise AuthenticationError("authentication_session_revoked")
            if _aware(row.expires_at) <= now or _aware(row.absolute_expires_at) <= now:
                raise AuthenticationError("authentication_session_expired")
            if (
                _aware(row.last_seen_at)
                + timedelta(minutes=self.configuration.session_idle_timeout_minutes)
                <= now
            ):
                raise AuthenticationError("authentication_session_expired")
            if (
                user is None
                or user.state != UserState.ACTIVE.value
                or row.user_revocation_generation != user.session_revocation_generation
            ):
                raise AuthenticationError("authentication_session_revoked")
            if _aware(row.last_seen_at) + timedelta(minutes=5) <= now:
                row.last_seen_at = now
            replacement = raw_token
            if (
                rotate
                and _aware(row.rotated_at)
                + timedelta(minutes=self.configuration.session_rotation_minutes)
                <= now
            ):
                replacement = new_session_token()
                row.token_hash = session_token_hash(replacement)
                row.rotated_at = now
                self._audit(
                    database,
                    "session_rotated",
                    target_user_id=user.user_id,
                    session_id=row.session_id,
                )
            return IssuedSession(_principal(user, row), replacement)

    def sign_out(self, raw_token: str, *, actor: AuthenticatedPrincipal | None = None) -> None:
        try:
            token_hash = session_token_hash(raw_token)
        except ValueError:
            return
        with self._sessions.begin() as database:
            row = database.scalar(
                select(AuthenticationSessionModel).where(
                    AuthenticationSessionModel.token_hash == token_hash
                )
            )
            if row is not None and row.revoked_at is None:
                row.revoked_at = _now()
                row.revocation_reason = "sign_out"
                self._audit(database, "session_revoked", actor=actor, session_id=row.session_id)
            self._audit(
                database, "sign_out", actor=actor, session_id=row.session_id if row else None
            )

    def list_sessions(
        self, user_id: str, *, current_session_id: str | None = None
    ) -> tuple[SessionRecord, ...]:
        with self._sessions() as database:
            rows = database.scalars(
                select(AuthenticationSessionModel)
                .where(AuthenticationSessionModel.user_id == user_id)
                .order_by(
                    AuthenticationSessionModel.created_at.desc(),
                    AuthenticationSessionModel.session_id,
                )
                .limit(100)
            )
            return tuple(
                SessionRecord(
                    row.session_id,
                    _aware(row.created_at),
                    _aware(row.last_seen_at),
                    _aware(row.expires_at),
                    _aware(row.absolute_expires_at),
                    row.authentication_method,
                    row.session_id == current_session_id,
                    row.revoked_at is not None,
                    row.client_label,
                )
                for row in rows
            )

    def revoke_session(
        self,
        session_id: str,
        user_id: str,
        *,
        actor: AuthenticatedPrincipal | None = None,
        allow_any: bool = False,
    ) -> None:
        with self._sessions.begin() as database:
            row = database.get(AuthenticationSessionModel, session_id)
            if row is None or (not allow_any and row.user_id != user_id):
                raise AuthenticationError("authentication_session_invalid")
            if row.revoked_at is None:
                row.revoked_at = _now()
                row.revocation_reason = "user_revoked"
                self._audit(
                    database,
                    "session_revoked",
                    actor=actor,
                    target_user_id=row.user_id,
                    session_id=session_id,
                )

    def revoke_user_sessions(
        self, user_id: str, *, actor: AuthenticatedPrincipal | None = None
    ) -> None:
        with self._sessions.begin() as database:
            self._require_user(database, user_id)
            self._revoke_user_sessions(database, user_id, "administrator_revoked")
            self._audit(database, "session_revoked", actor=actor, target_user_id=user_id)

    def change_password(self, principal: AuthenticatedPrincipal, current: str, new: str) -> None:
        if principal.user_id is None:
            raise AuthenticationError("authorization_denied")
        with self._sessions.begin() as database:
            user = self._require_user(database, principal.user_id)
            credential = database.get(UserCredentialModel, user.user_id)
            if credential is None or not verify_password(current, _password_hash(credential)):
                raise AuthenticationError("authentication_password_invalid")
            if verify_password(new, _password_hash(credential)):
                raise AuthenticationError("authentication_password_reused")
            validate_password(
                new,
                email=user.email,
                display_name=user.display_name,
                configuration=self.configuration,
            )
            replacement = hash_password(new, iterations=self.configuration.password_hash_iterations)
            credential.password_hash = replacement.encoded_hash
            credential.password_salt = replacement.salt_hex
            credential.password_iterations = replacement.iterations
            user.password_changed_at = _now()
            user.updated_at = user.password_changed_at
            user.session_revocation_generation += 1
            self._revoke_user_sessions(
                database, user.user_id, "password_changed", except_session_id=principal.session_id
            )
            if principal.session_id is not None:
                current_session = database.get(AuthenticationSessionModel, principal.session_id)
                if current_session is not None:
                    current_session.user_revocation_generation = user.session_revocation_generation
            self._audit(database, "password_changed", actor=principal, target_user_id=user.user_id)

    def audit_page(
        self, *, limit: int = 50, before_sequence: int | None = None
    ) -> tuple[AuthenticationAuditEventModel, ...]:
        if not 1 <= limit <= _MAXIMUM_PAGE_SIZE:
            raise AuthenticationError("authentication_audit_page_invalid")
        with self._sessions() as database:
            statement = select(AuthenticationAuditEventModel)
            if before_sequence is not None:
                statement = statement.where(
                    AuthenticationAuditEventModel.sequence < before_sequence
                )
            return tuple(
                database.scalars(
                    statement.order_by(AuthenticationAuditEventModel.sequence.desc()).limit(limit)
                )
            )

    def cleanup(self, *, before: datetime, maximum_rows: int = 1000) -> int:
        if not 1 <= maximum_rows <= _MAXIMUM_CLEANUP_ROWS:
            raise AuthenticationError("authentication_cleanup_bound_invalid")
        with self._sessions.begin() as database:
            sequences = tuple(
                database.scalars(
                    select(LoginAttemptModel.sequence)
                    .where(LoginAttemptModel.occurred_at < before)
                    .order_by(LoginAttemptModel.sequence)
                    .limit(maximum_rows)
                )
            )
            if sequences:
                database.execute(
                    delete(LoginAttemptModel).where(LoginAttemptModel.sequence.in_(sequences))
                )
            return len(sequences)

    def cleanup_sessions(self, *, now: datetime | None = None, maximum_rows: int = 1000) -> int:
        if not 1 <= maximum_rows <= _MAXIMUM_CLEANUP_ROWS:
            raise AuthenticationError("authentication_cleanup_bound_invalid")
        effective_now = now or _now()
        with self._sessions.begin() as database:
            session_ids = tuple(
                database.scalars(
                    select(AuthenticationSessionModel.session_id)
                    .where(
                        or_(
                            AuthenticationSessionModel.revoked_at.is_not(None),
                            AuthenticationSessionModel.absolute_expires_at <= effective_now,
                        )
                    )
                    .order_by(
                        AuthenticationSessionModel.absolute_expires_at,
                        AuthenticationSessionModel.session_id,
                    )
                    .limit(maximum_rows)
                )
            )
            if session_ids:
                database.execute(
                    delete(AuthenticationSessionModel).where(
                        AuthenticationSessionModel.session_id.in_(session_ids)
                    )
                )
            return len(session_ids)

    def diagnostics(self) -> AuthenticationDiagnostics:
        now = _now()
        recent = now - timedelta(seconds=self.configuration.login_rate_limit_window_seconds)
        with self._sessions() as database:
            active_users = database.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.state == UserState.ACTIVE.value)
            )
            administrators = database.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.role == UserRole.ADMINISTRATOR.value)
            )
            active_sessions = database.scalar(
                select(func.count())
                .select_from(AuthenticationSessionModel)
                .where(
                    AuthenticationSessionModel.revoked_at.is_(None),
                    AuthenticationSessionModel.absolute_expires_at > now,
                )
            )
            expired_sessions = database.scalar(
                select(func.count())
                .select_from(AuthenticationSessionModel)
                .where(AuthenticationSessionModel.absolute_expires_at <= now)
            )
            revoked_sessions = database.scalar(
                select(func.count())
                .select_from(AuthenticationSessionModel)
                .where(AuthenticationSessionModel.revoked_at.is_not(None))
            )
            locked_users = database.scalar(
                select(func.count()).select_from(UserModel).where(UserModel.lockout_until > now)
            )
            failures = database.scalar(
                select(func.count())
                .select_from(LoginAttemptModel)
                .where(
                    LoginAttemptModel.succeeded.is_(False), LoginAttemptModel.occurred_at >= recent
                )
            )
        return AuthenticationDiagnostics(
            enabled=self.configuration.enabled,
            mode=self.configuration.mode,
            authentication_version=self.configuration.authentication_version,
            authorization_version=self.configuration.authorization_version,
            session_version=self.configuration.session_version,
            auth_audit_version=self.configuration.auth_audit_version,
            shared_bearer_compatibility_enabled=(
                self.configuration.shared_bearer_compatibility_enabled
            ),
            user_session_capable=self.configuration.mode
            in {AuthenticationMode.USER_SESSION, AuthenticationMode.HYBRID},
            active_users=active_users or 0,
            administrators=administrators or 0,
            active_sessions=active_sessions or 0,
            expired_sessions=expired_sessions or 0,
            revoked_sessions=revoked_sessions or 0,
            locked_users=locked_users or 0,
            recent_login_failures=failures or 0,
            audit_ready=True,
            migration_ready=True,
            database_ready=True,
            cookie_security_ready=self.configuration.require_secure_cookie,
            bootstrap_ready=(administrators or 0) == 0,
        )

    def record_authorization_denied(
        self, principal: AuthenticatedPrincipal, permission: str
    ) -> None:
        _LOGGER.info(
            "authentication_event",
            extra={
                "authentication_event_type": "authorization_denied",
                "actor_user_id": principal.user_id,
                "session_id": principal.session_id,
                "role": principal.role.value,
                "permission": permission,
            },
        )
        with self._sessions.begin() as database:
            database.add(
                AuthenticationAuditEventModel(
                    event_id=secrets.token_hex(16),
                    event_type="authorization_denied",
                    actor_principal_type=principal.principal_type.value,
                    actor_user_id=principal.user_id,
                    target_user_id=None,
                    session_id=principal.session_id,
                    role=principal.role.value,
                    permission=permission,
                    success=False,
                    reason_code="authorization_denied",
                    correlation_id=None,
                    occurred_at=_now(),
                    audit_version=AUTH_AUDIT_VERSION,
                )
            )

    def record_shared_bearer_use(self) -> None:
        with self._sessions.begin() as database:
            self._audit(database, "shared_bearer_used")

    def _create_user(  # noqa: PLR0913 - explicit persistence mapping.
        self,
        database: Session,
        email: str,
        display_name: str,
        role: UserRole,
        password: str,
        state: UserState,
    ) -> UserModel:
        normalized = normalize_email(email)
        name = _display_name(display_name)
        validate_password(
            password, email=normalized, display_name=name, configuration=self.configuration
        )
        now = _now()
        user = UserModel(
            user_id=secrets.token_hex(16),
            email=email.strip(),
            normalized_email=normalized,
            display_name=name,
            state=state.value,
            role=role.value,
            credential_state="active",
            password_changed_at=now,
            created_at=now,
            updated_at=now,
            disabled_at=None,
            last_successful_login_at=None,
            last_failed_login_at=None,
            failed_login_count=0,
            lockout_until=None,
            session_revocation_generation=0,
            model_version=AUTHENTICATION_VERSION,
        )
        password_hash = hash_password(
            password, iterations=self.configuration.password_hash_iterations
        )
        database.add(user)
        database.add(
            UserCredentialModel(
                user_id=user.user_id,
                password_hash=password_hash.encoded_hash,
                password_salt=password_hash.salt_hex,
                password_algorithm=password_hash.algorithm,
                password_iterations=password_hash.iterations,
                password_version=password_hash.version,
            )
        )
        database.flush()
        return user

    def _issue_session(
        self, database: Session, user: UserModel, now: datetime, client_label: str
    ) -> IssuedSession:
        raw_token = new_session_token()
        row = AuthenticationSessionModel(
            session_id=secrets.token_hex(16),
            user_id=user.user_id,
            token_hash=session_token_hash(raw_token),
            token_algorithm=SESSION_TOKEN_ALGORITHM,
            token_version=_SESSION_TOKEN_VERSION,
            created_at=now,
            last_seen_at=now,
            rotated_at=now,
            expires_at=now + timedelta(minutes=self.configuration.session_lifetime_minutes),
            absolute_expires_at=now
            + timedelta(minutes=self.configuration.session_absolute_max_minutes),
            revoked_at=None,
            revocation_reason=None,
            user_revocation_generation=user.session_revocation_generation,
            authentication_method=AuthenticationMethod.PASSWORD_SESSION.value,
            principal_role_at_issue=user.role,
            client_label=f"client-{hashlib.sha256(client_label.encode('utf-8')).hexdigest()[:12]}",
            session_version=SESSION_VERSION,
        )
        database.add(row)
        database.flush()
        return IssuedSession(_principal(user, row), raw_token)

    def _enforce_session_cap(self, database: Session, user_id: str, now: datetime) -> None:
        rows = tuple(
            database.scalars(
                select(AuthenticationSessionModel)
                .where(
                    AuthenticationSessionModel.user_id == user_id,
                    AuthenticationSessionModel.revoked_at.is_(None),
                    AuthenticationSessionModel.absolute_expires_at > now,
                )
                .order_by(
                    AuthenticationSessionModel.created_at.desc(),
                    AuthenticationSessionModel.session_id,
                )
            )
        )
        for row in rows[self.configuration.session_max_active_per_user - 1 :]:
            row.revoked_at = now
            row.revocation_reason = "session_cap"

    @staticmethod
    def _require_user(database: Session, user_id: str) -> UserModel:
        user = database.get(UserModel, user_id)
        if user is None:
            raise AuthenticationError("user_not_found")
        return user

    @staticmethod
    def _revoke_user_sessions(
        database: Session, user_id: str, reason: str, *, except_session_id: str | None = None
    ) -> None:
        statement = update(AuthenticationSessionModel).where(
            AuthenticationSessionModel.user_id == user_id,
            AuthenticationSessionModel.revoked_at.is_(None),
        )
        if except_session_id is not None:
            statement = statement.where(AuthenticationSessionModel.session_id != except_session_id)
        database.execute(statement.values(revoked_at=_now(), revocation_reason=reason))

    @staticmethod
    def _audit(  # noqa: PLR0913 - explicit bounded audit evidence.
        database: Session,
        event_type: str,
        *,
        actor: AuthenticatedPrincipal | None = None,
        target_user_id: str | None = None,
        session_id: str | None = None,
        role: str | None = None,
        reason: str | None = None,
    ) -> None:
        _LOGGER.info(
            "authentication_event",
            extra={
                "authentication_event_type": event_type,
                "actor_user_id": actor.user_id if actor else None,
                "target_user_id": target_user_id,
                "session_id": session_id,
                "role": role,
                "reason_code": reason,
            },
        )
        database.add(
            AuthenticationAuditEventModel(
                event_id=secrets.token_hex(16),
                event_type=event_type,
                actor_principal_type=actor.principal_type.value if actor else None,
                actor_user_id=actor.user_id if actor else None,
                target_user_id=target_user_id,
                session_id=session_id,
                role=role,
                permission=None,
                success=reason is None,
                reason_code=reason,
                correlation_id=None,
                occurred_at=_now(),
                audit_version=AUTH_AUDIT_VERSION,
            )
        )


def _principal(user: UserModel, session: AuthenticationSessionModel) -> AuthenticatedPrincipal:
    role = UserRole(user.role)
    return AuthenticatedPrincipal(
        PrincipalType.USER,
        AuthenticationMethod.PASSWORD_SESSION,
        role,
        permissions_for_role(role),
        user.user_id,
        user.email,
        user.display_name,
        session.session_id,
        _aware(session.created_at),
        _aware(session.expires_at),
        _aware(session.absolute_expires_at),
    )


def _user_record(user: UserModel) -> UserRecord:
    return UserRecord(
        user.user_id,
        user.email,
        user.display_name,
        UserState(user.state),
        UserRole(user.role),
        _aware(user.created_at),
        _aware(user.updated_at),
    )


def _password_hash(row: UserCredentialModel) -> PasswordHash:
    return PasswordHash(
        row.password_hash,
        row.password_salt,
        row.password_iterations,
        row.password_algorithm,
        row.password_version,
    )


def _display_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= _MAXIMUM_DISPLAY_NAME or any(
        ord(character) < _CONTROL_CHARACTER_BOUNDARY for character in name
    ):
        raise AuthenticationError("user_display_name_invalid")
    return name


def _safe_normalized_email(value: str) -> str:
    try:
        return normalize_email(value)
    except ValueError:
        return value.strip().casefold()[:320]


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
