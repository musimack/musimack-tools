# 0043: Password authentication and explicit bootstrap

Status: Accepted for `seo-toolkit-authentication-v1`.

## Decision

Use persisted internal users and PBKDF2-HMAC-SHA256 password credentials with random salts and a
600,000-iteration production floor. Create the first administrator only through an explicit,
network-free service call that requires an email, display name, and caller-supplied password and
refuses when an administrator already exists.

## Consequences

There is no default administrator, default password, import-time bootstrap, public bootstrap
endpoint, generated credential output, OAuth, recovery email, or new dependency. Failed sign-ins
return generic evidence and persist bounded rate-limit, lockout, and audit state.
