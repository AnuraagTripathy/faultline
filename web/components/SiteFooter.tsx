import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-border mt-auto">
      <div className="mx-auto max-w-content px-6 py-12 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6 text-sm text-muted">
        <p>© {new Date().getFullYear()} Faultline</p>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Link href="/demo" className="no-underline hover:underline text-muted hover:text-foreground">
            Demo
          </Link>
          <Link href="/architecture" className="no-underline hover:underline text-muted hover:text-foreground">
            Architecture
          </Link>
          <Link href="/security" className="no-underline hover:underline text-muted hover:text-foreground">
            Security
          </Link>
          <Link href="/reliability" className="no-underline hover:underline text-muted hover:text-foreground">
            Reliability
          </Link>
          <Link href="/how-recovery-works" className="no-underline hover:underline text-muted hover:text-foreground">
            How recovery works
          </Link>
          <Link href="/signup" className="no-underline hover:underline text-muted hover:text-foreground">
            Sign up
          </Link>
        </div>
      </div>
    </footer>
  );
}
