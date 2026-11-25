import { effectTile } from "../../lib/tiles";

/** Effects preset art: the photo tile when one exists (lib/tiles.ts), else the CSS `.thumb-*` art. */
export function EffectArt({ id }: { id: string }) {
  const src = effectTile(id);
  return src ? <img className="apps-thumb-art apps-thumb-img" src={src} alt="" loading="lazy" /> : <div className={`apps-thumb-art thumb-${id}`} />;
}
