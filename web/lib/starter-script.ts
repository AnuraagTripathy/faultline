export const ONBOARDING_API_KEY_STORAGE = "faultline_onboarding_api_key";
export const ONBOARDING_SNIPPET_COPIED_STORAGE = "faultline_snippet_copied";

/** Public URL of the Cloud API as seen from your training machine (Docker maps :8080). */
export const DEFAULT_API_BASE_URL =
  process.env.NEXT_PUBLIC_FAULTLINE_API_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8080";

export function buildStarterScript(
  apiKey: string,
  baseUrl = DEFAULT_API_BASE_URL
): string {
  return `# pip install faultline-sdk
import faultline

run = faultline.start(
    "my-first-run",
    project="demo",
    api_key="${apiKey}",
    base_url="${baseUrl}",
)

start_step = run.restore_latest(model=model, optimizer=optimizer)

for step in range(start_step, 100):
    run.log(loss=0.5, step=step)
    if step % 10 == 0:
        run.save(model=model, optimizer=optimizer, step=step)

run.complete()`;
}

/** @deprecated use buildStarterScript */
export const STARTER_SCRIPT = buildStarterScript("YOUR_API_KEY");
