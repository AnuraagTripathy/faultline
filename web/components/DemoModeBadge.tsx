import Link from "next/link";

export function DemoModeBadge({ className = "" }: { className?: string }) {
  return (
    <p className={`text-sm text-muted ${className}`}>
      <span className="font-medium text-foreground">Demo mode</span>
      {" — "}
      sample data only.{" "}
      <Link href="/signup" className="text-accent font-medium no-underline hover:underline">
        Sign up
      </Link>{" "}
      to connect real training runs.
    </p>
  );
}
