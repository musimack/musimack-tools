# 0052: Live job polling

Status: Accepted for `seo-toolkit-job-monitor-ui-v1` and `seo-toolkit-frontend-polling-v1`.

## Decision

Poll queued jobs every three seconds and active jobs every two seconds, with bounded retry backoff,
reduced hidden-document frequency, one in-flight cycle, abort on unmount, manual refresh, and a
hard stop for terminal states. Poll status and the bounded progress-event projection only.

## Consequences

The monitor is responsive without becoming a task authority. A page close, navigation, transient
failure, or terminal result deterministically ends or slows requests without persisting state.
