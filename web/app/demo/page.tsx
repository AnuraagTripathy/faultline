import { DemoWalkthrough } from "@/components/DemoWalkthrough";

export default function DemoPage() {
  return (
    <div className="space-y-10">
      <header className="max-w-2xl">
        <p className="section-label mb-3">Interactive demo</p>
        <h1 className="font-serif text-3xl md:text-4xl text-foreground mb-4 tracking-tight leading-snug">
          From training to recovery in four steps
        </h1>
        <p className="text-muted text-[15px] leading-relaxed">
          This is a simulated run — no signup required. Click each step below (or let it
          auto-play) to see how Faultline tracks metrics, stores checkpoints, handles crashes,
          and tells you exactly how to resume.
        </p>
      </header>
      <DemoWalkthrough />
    </div>
  );
}
