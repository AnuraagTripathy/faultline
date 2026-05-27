import { SiteFooter } from "@/components/SiteFooter";
import { SiteNav } from "@/components/SiteNav";

export default function DemoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-surface">
      <SiteNav ctaHref="/signup" ctaLabel="Sign up" />
      <main className="flex-1 mx-auto max-w-content w-full px-6 py-10 md:py-14">{children}</main>
      <SiteFooter />
    </div>
  );
}
