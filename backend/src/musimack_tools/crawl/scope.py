"""Network-free crawl host and origin scope policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from musimack_tools.crawl.normalization import normalize_hostname, normalize_url
from musimack_tools.domain.urls import (
    AllowedOrigin,
    CrawlScopeDecision,
    CrawlScopePolicy,
    NormalizedUrl,
    ScopeMode,
    ScopeReasonCode,
    UrlErrorCode,
    UrlNormalizationError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class _DecisionEvidence:
    allowed: bool
    reason: ScopeReasonCode
    explanation: str
    configured_host: str


def create_scope_policy(
    seed: NormalizedUrl,
    *,
    mode: ScopeMode = ScopeMode.EXACT_HOST,
    approved_hosts: Iterable[str] = (),
    allowed_origins: Iterable[AllowedOrigin] = (),
) -> CrawlScopePolicy:
    """Create a validated policy; the seed host and origin are always allowed."""
    normalized_hosts = frozenset(normalize_hostname(host) for host in approved_hosts)
    origins = frozenset(
        {
            AllowedOrigin(seed.scheme, seed.effective_port),
            *allowed_origins,
        }
    )
    return CrawlScopePolicy(
        seed=seed,
        mode=mode,
        approved_hosts=normalized_hosts,
        allowed_origins=origins,
    )


def evaluate_scope(
    policy: CrawlScopePolicy,
    destination: str | NormalizedUrl,
) -> CrawlScopeDecision:
    """Evaluate a destination against a policy and return stable decision evidence."""
    try:
        target = (
            destination if isinstance(destination, NormalizedUrl) else normalize_url(destination)
        )
    except UrlNormalizationError as error:
        reason = (
            ScopeReasonCode.DENIED_SCHEME
            if error.code is UrlErrorCode.UNSUPPORTED_SCHEME
            else ScopeReasonCode.DENIED_INVALID_URL
        )
        return _decision(
            policy=policy,
            target=None,
            evidence=_DecisionEvidence(
                allowed=False,
                reason=reason,
                explanation=str(error),
                configured_host=policy.seed.hostname,
            ),
        )

    return _evaluate_valid_target(policy, target)


def _evaluate_valid_target(
    policy: CrawlScopePolicy,
    target: NormalizedUrl,
) -> CrawlScopeDecision:
    origin_denial = _evaluate_origin(policy, target)
    if origin_denial is not None:
        return origin_denial
    return _evaluate_host(policy, target)


def _evaluate_origin(
    policy: CrawlScopePolicy,
    target: NormalizedUrl,
) -> CrawlScopeDecision | None:

    origin_schemes = {origin.scheme for origin in policy.allowed_origins}
    if target.scheme not in origin_schemes:
        return _decision(
            policy=policy,
            target=target,
            evidence=_DecisionEvidence(
                allowed=False,
                reason=ScopeReasonCode.DENIED_SCHEME,
                explanation=f"Scheme {target.scheme!r} is not allowed by this crawl scope",
                configured_host=policy.seed.hostname,
            ),
        )

    matching_origin = next(
        (
            origin
            for origin in policy.allowed_origins
            if origin.scheme == target.scheme and origin.effective_port == target.effective_port
        ),
        None,
    )
    if matching_origin is None:
        return _decision(
            policy=policy,
            target=target,
            evidence=_DecisionEvidence(
                allowed=False,
                reason=ScopeReasonCode.DENIED_PORT_MISMATCH,
                explanation=(
                    f"Effective port {target.effective_port} is not allowed for scheme "
                    f"{target.scheme}"
                ),
                configured_host=policy.seed.hostname,
            ),
        )
    return None


def _evaluate_host(policy: CrawlScopePolicy, target: NormalizedUrl) -> CrawlScopeDecision:

    seed_host = policy.seed.hostname
    target_host = target.hostname
    if target_host == seed_host:
        return _decision(
            policy=policy,
            target=target,
            evidence=_DecisionEvidence(
                allowed=True,
                reason=ScopeReasonCode.ALLOWED_EXACT_HOST,
                explanation="Destination hostname exactly matches the configured seed hostname",
                configured_host=seed_host,
            ),
        )

    if policy.mode is ScopeMode.INCLUDE_SUBDOMAINS:
        if target_host.endswith(f".{seed_host}"):
            return _decision(
                policy=policy,
                target=target,
                evidence=_DecisionEvidence(
                    allowed=True,
                    reason=ScopeReasonCode.ALLOWED_SUBDOMAIN,
                    explanation="Destination is a true subdomain of the configured seed hostname",
                    configured_host=seed_host,
                ),
            )
        if target_host.endswith(seed_host):
            return _decision(
                policy=policy,
                target=target,
                evidence=_DecisionEvidence(
                    allowed=False,
                    reason=ScopeReasonCode.DENIED_FALSE_SUFFIX_MATCH,
                    explanation="Destination only shares a textual suffix with the seed hostname",
                    configured_host=seed_host,
                ),
            )

    if policy.mode is ScopeMode.APPROVED_HOSTS and target_host in policy.approved_hosts:
        return _decision(
            policy=policy,
            target=target,
            evidence=_DecisionEvidence(
                allowed=True,
                reason=ScopeReasonCode.ALLOWED_APPROVED_HOST,
                explanation="Destination hostname is in the explicit approved-host set",
                configured_host=target_host,
            ),
        )

    return _decision(
        policy=policy,
        target=target,
        evidence=_DecisionEvidence(
            allowed=False,
            reason=ScopeReasonCode.DENIED_HOST_MISMATCH,
            explanation="Destination hostname is outside the configured crawl host scope",
            configured_host=seed_host,
        ),
    )


def _decision(
    *,
    policy: CrawlScopePolicy,
    target: NormalizedUrl | None,
    evidence: _DecisionEvidence,
) -> CrawlScopeDecision:
    scheme = target.scheme if target is not None else policy.seed.scheme
    port = target.effective_port if target is not None else policy.seed.effective_port
    return CrawlScopeDecision(
        allowed=evidence.allowed,
        reason_code=evidence.reason,
        explanation=evidence.explanation,
        evaluated_hostname=target.hostname if target is not None else None,
        evaluated_effective_port=target.effective_port if target is not None else None,
        configured_host=evidence.configured_host,
        configured_origin=_format_origin(scheme, evidence.configured_host, port),
    )


def _format_origin(scheme: str, hostname: str, port: int) -> str:
    host_for_authority = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    authority = host_for_authority if port == default_port else f"{host_for_authority}:{port}"
    return f"{scheme}://{authority}"
