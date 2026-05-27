import { formatTimestamp } from "@/lib/format";
import type { Event } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

const RESUME_TYPES = new Set([
  "faultline.run.resume_requested",
  "faultline.run.resume_started",
  "faultline.run.resume_completed",
  "faultline.run.resume_failed",
]);

export function EventsTimeline({
  events,
  filterResumeOnly = false,
}: {
  events: Event[];
  filterResumeOnly?: boolean;
}) {
  const sorted = [...events].sort(
    (a, b) => b.timestamp_ms - a.timestamp_ms
  );
  const filtered = filterResumeOnly
    ? sorted.filter((e) => RESUME_TYPES.has(e.event_type))
    : sorted;

  if (!filtered.length) {
    return (
      <p className="text-sm text-muted">No events yet.</p>
    );
  }

  return (
    <ul className="space-y-3">
      {filtered.map((event) => (
        <li
          key={event.event_id}
          className="flex gap-3 border-l-2 border-border pl-4 py-1"
        >
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <StatusBadge status={event.level} />
              <span className="text-xs font-mono text-muted">
                {event.event_type}
              </span>
              <span className="text-xs text-muted">
                {formatTimestamp(event.timestamp_ms)}
              </span>
            </div>
            <p className="text-sm text-foreground/90 break-words">{event.message}</p>
            {event.event_type === "faultline.run.resume_completed" ? (
              <p className="text-xs text-ok mt-1">Recovery successful</p>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
