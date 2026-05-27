import Image from "next/image";
import Link from "next/link";
import { cn } from "@/lib/cn";

export function Logo({
  href = "/",
  className,
  iconSize = 42,
  textClassName,
}: {
  href?: string;
  className?: string;
  iconSize?: number;
  textClassName?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex shrink-0 items-center gap-3 no-underline hover:no-underline",
        className
      )}
    >
      <Image
        src="/faultline-icon.png"
        alt=""
        aria-hidden
        width={iconSize}
        height={iconSize}
        className="h-auto w-auto rounded-xl"
        priority
      />
      <span
        className={cn(
          "text-[20px] font-semibold leading-none tracking-tight text-foreground",
          textClassName
        )}
      >
        Faultline
      </span>
    </Link>
  );
}
