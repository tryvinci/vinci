/**
 * Vinci mark and wordmark from the tryvinci.com header.
 *
 * Files are tight crops of apps/vinci-frontend/public/images/logo.png,
 * logo-name-dark.png, and logo-name-light.png. Do not redraw the mark.
 */
export function VinciLogo({ variant = "lockup" }: { variant?: "lockup" | "mark" }) {
  if (variant === "mark") {
    return (
      <span className="vinci-logo vinci-logo-mark-only">
        <img src="/brand/mark.png" alt="Vinci" width={28} height={28} />
      </span>
    );
  }
  return (
    <span className="vinci-logo" data-testid="vinci-logo">
      <img className="vinci-logo-mark" src="/brand/mark.png" alt="Vinci" width={28} height={28} />
      <img className="vinci-logo-word" src="/brand/lockup-dark.png" alt="Vinci" width={86} height={28} />
    </span>
  );
}
