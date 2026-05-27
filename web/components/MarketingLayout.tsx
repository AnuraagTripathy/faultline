import { SiteFooter } from "@/components/SiteFooter";
import { SiteNav } from "@/components/SiteNav";

export function MarketingLayout({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col bg-surface">
      <SiteNav />
      <main className="flex-1 mx-auto max-w-prose px-6 py-12 md:py-16 w-full">
        <h1 className="font-serif text-3xl text-foreground mb-10 tracking-tight">{title}</h1>
        <div className="prose-faultline">{children}</div>
      </main>
      <SiteFooter />
    </div>
  );
}
