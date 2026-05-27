import { CodeBlock } from "@/components/CodeBlock";
import { MediaFrame } from "@/components/MediaFrame";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteNav } from "@/components/SiteNav";
import Link from "next/link";

const SNIPPET = `pip install faultline-sdk
export FAULTLINE_API_KEY=fl_...
export FAULTLINE_API_URL=https://your-api.onrender.com
python train.py`;

const PROBLEMS = [
  ["Spot preemption", "Your GPU job disappears mid-epoch — hours of spend at risk."],
  ["Slurm eviction", "The cluster requeues without your checkpoint path handy."],
  ["Process crash", "OOM, Ctrl+C, or a bug — progress scattered across logs."],
];

const INTEGRATIONS = [
  ["HuggingFace", "FaultlineTrainerCallback"],
  ["PyTorch Lightning", "FaultlineLightningCallback"],
  ["Raw PyTorch", "faultline.auto_resume()"],
];

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      <SiteNav />

      <main className="flex-1">
        {/* Hero — product overview is the primary media */}
        <section className="mx-auto max-w-content px-6 pt-16 pb-20 md:pt-24 md:pb-24">
          <div className="mb-12 md:mb-16">
            <div className="mx-auto max-w-5xl text-center">
              <p className="section-label mb-6">Training continuity</p>
              <h1 className="font-serif text-[3.2rem] sm:text-[4rem] md:text-[5.5rem] leading-[0.98] tracking-tight text-foreground mb-8">
                Never lose days of ML training again.
              </h1>
              <p className="mx-auto max-w-3xl text-[20px] md:text-[24px] text-muted leading-relaxed mb-10">
                Faultline monitors long-running jobs, stores checkpoints, and shows you
                exactly how to resume training on a laptop, HPC cluster, or cloud GPUs.
              </p>
              <div className="flex flex-wrap justify-center items-center gap-4">
                <Link href="/signup" className="btn-primary">
                  Get started
                </Link>
                <Link href="/demo" className="btn-ghost">
                  View demo →
                </Link>
              </div>
            </div>
          </div>
          <MediaFrame
            kind="video"
            title="Product overview"
            aspect="wide"
            className="w-full shadow-md max-w-6xl mx-auto"
          />
          <p className="text-center text-xs text-subtle mt-3">
            Replace with your screen recording at{" "}
            <code className="font-mono">public/assets/videos/product-overview.mp4</code>
          </p>
        </section>

        {/* Architecture — text only */}
        <section className="bg-surface border-y border-border py-14 md:py-20">
          <div className="mx-auto max-w-content px-6">
            <div className="grid md:grid-cols-2 gap-8 md:gap-16">
              <div>
                <p className="section-label mb-3">How it works</p>
                <h2 className="font-serif text-2xl md:text-3xl text-foreground leading-snug">
                  From your trainer to durable checkpoints
                </h2>
              </div>
              <p className="text-muted text-[15px] leading-relaxed md:pt-8">
                SDK or framework callbacks stream metrics and state to the Cloud API. Postgres
                stores run metadata; object storage holds checkpoint blobs. The dashboard is
                your recovery control plane — not another experiment charting tool.
              </p>
            </div>
          </div>
        </section>

        {/* Problems — list only */}
        <section className="mx-auto max-w-content px-6 py-16 md:py-20">
          <p className="section-label mb-3">When training fails</p>
          <h2 className="font-serif text-2xl md:text-3xl text-foreground mb-10 max-w-lg">
            Built for failures trackers weren&apos;t designed to fix
          </h2>
          <ul className="divide-y divide-border max-w-prose">
            {PROBLEMS.map(([title, desc]) => (
              <li key={title} className="py-5 first:pt-0 last:pb-0">
                <p className="font-semibold text-foreground mb-1">{title}</p>
                <p className="text-muted text-[15px] leading-relaxed">{desc}</p>
              </li>
            ))}
          </ul>
        </section>

        {/* Recovery — one supporting GIF */}
        <section className="bg-accent-soft/40 border-y border-accent-muted/50">
          <div className="mx-auto max-w-content px-6 py-16 md:py-20">
            <div className="grid lg:grid-cols-2 gap-10 lg:gap-14 items-center mb-10">
              <div>
                <p className="section-label mb-4">Recovery</p>
                <h2 className="font-serif text-3xl md:text-[2.5rem] text-foreground leading-snug mb-6">
                  Checkpoint. Crash. Resume.
                </h2>
                <p className="text-muted text-[15px] leading-relaxed mb-6">
                  <code className="font-mono text-sm text-accent bg-surface-elevated px-1.5 py-0.5 rounded border border-border">
                    save(step)
                  </code>{" "}
                  streams state to object storage. When the node dies, the dashboard shows lost
                  steps, checkpoint health, and a copy-paste{" "}
                  <code className="font-mono text-sm text-accent bg-surface-elevated px-1.5 py-0.5 rounded border border-border">
                    auto_resume()
                  </code>{" "}
                  path.
                </p>
                <Link href="/demo" className="btn-ghost text-accent">
                  Try the interactive demo →
                </Link>
              </div>
            </div>
            <MediaFrame
              kind="gif"
              title="Crash → resume walkthrough"
              aspect="video"
            />
          </div>
        </section>

        {/* Dashboard — copy only (shown in product overview video) */}
        <section className="mx-auto max-w-content px-6 py-16 md:py-20">
          <p className="section-label mb-3">Dashboard</p>
          <h2 className="font-serif text-2xl md:text-3xl text-foreground leading-snug max-w-xl mb-4">
            Metrics, checkpoints, and resume commands in one place
          </h2>
          <p className="text-muted text-[15px] leading-relaxed max-w-prose">
            Live loss curves while jobs run. Checkpoint timeline, recovery readiness badges,
            and relaunch when you&apos;ve registered a launch config. Covered in the product
            overview above.
          </p>
        </section>

        {/* Integrations — text only */}
        <section className="bg-surface border-y border-border py-14 md:py-20">
          <div className="mx-auto max-w-content px-6">
            <p className="section-label mb-3">Integrations</p>
            <h2 className="font-serif text-2xl text-foreground mb-10">
              Drop into the stack you already use
            </h2>
            <ul className="grid sm:grid-cols-3 gap-8 sm:gap-12">
              {INTEGRATIONS.map(([name, api]) => (
                <li key={name}>
                  <p className="font-semibold text-foreground mb-1">{name}</p>
                  <p className="font-mono text-[11px] text-subtle">{api}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Quickstart */}
        <section className="mx-auto max-w-content px-6 py-16 md:py-20">
          <div className="grid md:grid-cols-2 gap-10 md:gap-14 items-start">
            <div>
              <p className="section-label mb-4">Quickstart</p>
              <h2 className="font-serif text-2xl text-foreground mb-4">Up and running locally</h2>
              <p className="text-muted text-[15px] leading-relaxed mb-4">
                Docker Compose brings up Postgres, MinIO, the API, and this UI. Pre-seeded demo
                runs — explore without writing a training script.
              </p>
              <p className="font-mono text-xs text-subtle">
                demo@faultline.local · faultlinedemo
              </p>
            </div>
            <CodeBlock code={SNIPPET} />
          </div>
        </section>

        {/* CTA — no media */}
        <section className="bg-foreground text-surface-elevated">
          <div className="mx-auto max-w-prose px-6 py-16 md:py-20 text-center md:text-left">
            <h2 className="font-serif text-2xl md:text-3xl mb-4 leading-snug">
              Try it in two minutes
            </h2>
            <p className="text-surface-2 text-[15px] leading-relaxed mb-8 opacity-90">
              <code className="font-mono text-sm text-accent-muted">
                docker compose -f docker-compose.cloud.yml up --build
              </code>
            </p>
            <div className="flex flex-wrap justify-center md:justify-start gap-4">
              <Link
                href="/login"
                className="inline-block font-medium bg-accent text-surface-elevated px-5 py-2.5 rounded-lg no-underline hover:no-underline hover:bg-accent-hover transition-colors text-sm"
              >
                Open dashboard
              </Link>
              <Link
                href="/signup"
                className="text-sm text-surface-2 no-underline hover:no-underline hover:text-white opacity-90"
              >
                Create account →
              </Link>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
