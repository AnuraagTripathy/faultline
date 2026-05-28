import { cn } from "@/lib/cn";

/** Autoplaying, muted, looping video — behaves like a high-quality GIF. */
export function LoopingVideo({
  src,
  className,
}: {
  src: string;
  className?: string;
}) {
  return (
    <video
      className={cn(
        "looping-video h-full w-full object-cover bg-black pointer-events-none",
        className
      )}
      src={src}
      autoPlay
      muted
      loop
      playsInline
      preload="auto"
      disablePictureInPicture
      controls={false}
      aria-hidden
    />
  );
}
