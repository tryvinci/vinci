/**
 * Vinci mark and wordmark from the tryvinci.com header.
 *
 * Files are tight crops of apps/vinci-frontend/public/images/logo.png,
 * logo-name-dark.png, and logo-name-light.png. Do not redraw the mark.
 */

/** Base path of a static build (`npm run build:static`); plain <img> paths do not get it from Next. */
const BASE = process.env.NEXT_PUBLIC_VINCI_STUDIO_BASE_PATH || "";

export function VinciLogo({ variant = "lockup" }: { variant?: "lockup" | "mark" }) {
  if (variant === "mark") {
    return (
      <span className="vinci-logo vinci-logo-mark-only">
        <img src={`${BASE}/brand/mark.png`} alt="Vinci" width={28} height={28} />
      </span>
    );
  }
  return (
    <span className="vinci-logo" data-testid="vinci-logo">
      <img className="vinci-logo-mark" src={`${BASE}/brand/mark.png`} alt="Vinci" width={28} height={28} />
      <img className="vinci-logo-word" src={`${BASE}/brand/lockup-dark.png`} alt="Vinci" width={86} height={28} />
    </span>
  );
}
