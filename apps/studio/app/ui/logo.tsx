/**
 * Vinci mark and wordmark from the tryvinci.com header.
 *
 * Files are tight crops of apps/vinci-frontend/public/images/logo.png,
 * logo-name-dark.png, and logo-name-light.png. Do not redraw the mark.
 */

/** Base path of a static build (`npm run build:static`); plain <img> paths do not get it from Next. */
const BASE = process.env.NEXT_PUBLIC_VINCI_STUDIO_BASE_PATH || "";

/**
 * The Vinci logo. With `home` (a host's `host.home` from GET /doctor) it is a link that opens the
 * host app's home in the top window, outside the Studio frame. The local Studio has no host.
 */
export function VinciLogo({
  variant = "lockup",
  home,
}: {
  variant?: "lockup" | "mark";
  home?: { title: string; href: string };
}) {
  const logo =
    variant === "mark" ? (
      <span className="vinci-logo vinci-logo-mark-only">
        <img src={`${BASE}/brand/mark.png`} alt="Vinci" width={28} height={28} />
      </span>
    ) : (
      <span className="vinci-logo" data-testid="vinci-logo">
        <img className="vinci-logo-mark" src={`${BASE}/brand/mark.png`} alt="Vinci" width={28} height={28} />
        <img className="vinci-logo-word" src={`${BASE}/brand/lockup-dark.png`} alt="Vinci" width={86} height={28} />
      </span>
    );
  if (!home) return logo;
  const label = `Back to ${home.title}`;
  return (
    <a className="vinci-logo-home" href={home.href} target="_top" aria-label={label} title={label}>
      {logo}
    </a>
  );
}
