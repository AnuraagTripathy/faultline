# Marketing assets

The landing page uses **two** media slots:

1. **`videos/product-overview.mp4`** — hero (main product walkthrough)
2. **`gifs/crash-resume.gif`** or `.mp4` — recovery section (optional but recommended)

Copy into `web/public/assets/` so they serve at `/assets/...`.

```
web/public/assets/
  videos/product-overview.mp4
  gifs/crash-resume.mp4
```

## Example — replace a placeholder in code

```tsx
<MediaFrame kind="gif" title="Crash to resume">
  <video
    src="/assets/gifs/crash-resume.mp4"
    autoPlay
    loop
    muted
    playsInline
    className="h-full w-full object-cover"
  />
</MediaFrame>
```

Or use Next.js `Image` for static screenshots:

```tsx
import Image from "next/image";

<MediaFrame kind="screenshot" aspect="wide">
  <Image src="/assets/screenshots/dashboard.png" alt="Dashboard" fill className="object-cover" />
</MediaFrame>
```

Copy files into `web/public/assets/` so they are served at `/assets/...`.
