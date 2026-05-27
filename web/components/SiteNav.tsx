import { Logo } from "@/components/Logo";
import Link from "next/link";

export function SiteNav({
  ctaHref = "/signup",
  ctaLabel = "Get started",
}: {
  ctaHref?: string;
  ctaLabel?: string;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-surface-elevated/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-content items-center justify-between px-6 py-4">
        <Logo href="/" />
        <nav className="flex items-center gap-5 sm:gap-7">
          <Link href="/demo" className="site-nav-link hidden sm:inline">
            Demo
          </Link>
          <Link href="/architecture" className="site-nav-link hidden md:inline">
            Docs
          </Link>
          <Link href="/login" className="site-nav-link">
            Log in
          </Link>
          <Link href={ctaHref} className="btn-primary !py-2 !px-4">
            {ctaLabel}
          </Link>
        </nav>
      </div>
    </header>
  );
}
