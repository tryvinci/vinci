/**
 * Media tiles: photographic thumbnails for template cards (Home, Explore, Templates) and Effects
 * presets. Files are 720x450 WebP in public/tiles/, generated with gpt-image-2.6-sunburst and graded
 * to the Vinci stills (UI jam, 2026-11). An id with no tile keeps its drawn art (the daemon's
 * preview.svg for templates, the CSS .thumb-* art for effects).
 */

/** Base path of a static build; plain <img> paths do not get it from Next. */
const BASE = process.env.NEXT_PUBLIC_VINCI_STUDIO_BASE_PATH || "";

const TEMPLATE_TILES = new Set([
  "captions", "cinema-sequence", "cinema-still", "clip-select", "emote", "first-last-frame", "lipsync", "motion",
  "podcast-to-shorts", "product-reveal", "reframe", "soul-character", "speak-car", "speak-podcast", "speak-selfie",
  "still-image", "still-to-4k", "still-to-talk", "streamer-split", "talking-photo", "tts", "upscale-still",
  "video-upscale", "voice-clone",
]);
const EFFECT_TILES = new Set([
  "adapts", "cinema-still", "editorial-portrait", "motion-clip", "product-hero", "product-reveal", "renaissance-still",
  "still-4k", "talking-photo", "voiceover",
]);

/**
 * Tile URL for a template card.
 *
 * Args:
 *   id: Template id from GET /templates.
 *   fallback: URL to use when the template has no tile (the daemon's preview.svg).
 * Returns:
 *   The tile URL, else `fallback`.
 */
export function templateTile(id: string, fallback: string): string {
  return TEMPLATE_TILES.has(id) ? `${BASE}/tiles/templates/${id}.webp` : fallback;
}

/**
 * Tile URL for an Effects preset, or null when the effect keeps its CSS art.
 *
 * Args:
 *   id: Effect id from lib/apps-catalog.ts.
 */
export function effectTile(id: string): string | null {
  return EFFECT_TILES.has(id) ? `${BASE}/tiles/effects/${id}.webp` : null;
}
