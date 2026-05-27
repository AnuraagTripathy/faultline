import { cn } from "@/lib/cn";
import { ImageIcon, Play, Film } from "lucide-react";
import type { ReactNode } from "react";

type MediaKind = "diagram" | "gif" | "video" | "screenshot";

const KIND_CONFIG: Record<
  MediaKind,
  { label: string; icon: typeof ImageIcon; hint: string }
> = {
  diagram: {
    label: "Diagram",
    icon: ImageIcon,
    hint: "Architecture or flow diagram",
  },
  gif: {
    label: "GIF",
    icon: Film,
    hint: "Animated product walkthrough",
  },
  video: {
    label: "Video",
    icon: Play,
    hint: "Screen recording or demo reel",
  },
  screenshot: {
    label: "Screenshot",
    icon: ImageIcon,
    hint: "Dashboard or UI capture",
  },
};

export function MediaFrame({
  kind = "screenshot",
  title,
  aspect = "video",
  className,
  children,
}: {
  kind?: MediaKind;
  title?: string;
  aspect?: "video" | "wide" | "square" | "tall";
  className?: string;
  /** When set, replaces the placeholder (e.g. img, video, iframe). */
  children?: ReactNode;
}) {
  const config = KIND_CONFIG[kind];
  const Icon = config.icon;

  const aspectClass = {
    video: "aspect-video",
    wide: "aspect-[21/9]",
    square: "aspect-square",
    tall: "aspect-[4/5]",
  }[aspect];

  return (
    <figure className={cn("group", className)}>
      <div
        className={cn(
          "relative overflow-hidden rounded-media border border-border bg-surface-elevated shadow-sm",
          aspectClass
        )}
      >
        {children ? (
          <div className="absolute inset-0">{children}</div>
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-gradient-to-br from-accent-soft/80 via-surface-elevated to-surface-2 p-6 text-center">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-accent/10 text-accent">
              <Icon className="h-5 w-5" strokeWidth={1.5} />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-accent">
                {config.label}
              </p>
              <p className="text-[11px] text-subtle mt-1 max-w-[14rem] leading-snug">
                {title ?? config.hint}
              </p>
            </div>
            <p className="absolute bottom-3 left-3 right-3 text-[10px] text-subtle/80 font-mono truncate">
              public/assets/{kind}s/…
            </p>
          </div>
        )}
      </div>
    </figure>
  );
}
