# ADR 0027: SQLite persistence foundation

## Status

Accepted for `seo-toolkit-persistence-v1`.

## Decision

Provide optional, explicitly composed persistence through SQLAlchemy 2.x and SQLite. Persistence is
disabled by default, requires an absolute database path, and creates no engine or filesystem
artifact during module import or default FastAPI composition. The SQLAlchemy engine and session
factory are injected at the persistence boundary; domain and application contracts do not depend
on ORM models.

SQLite connections enable foreign keys and use configured busy-timeout, journal, synchronous, and
connection-timeout settings. The default journal mode is WAL and the default synchronous mode is
NORMAL. Database parent creation is explicit, and path validation rejects repository metadata,
directories, symbolic links, junctions, device paths, and network paths.

## Consequences

The internal deployment gains a bounded durable record layer without making persistence mandatory.
SQLite supports the current single-process deployment; PostgreSQL, multi-process coordination,
database encryption, backup automation, and high-availability operation remain deferred.
