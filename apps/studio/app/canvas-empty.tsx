"use client";

import { START_CARDS } from "../lib/canvas-node";

/**
 * Magnific empty space: "Choose your first node" plus the five starter cards.
 *
 * Clicking a card inserts that capability. N / + opens the add-node popover.
 * `canAdd` (on a host) hides a card that no model can run: Voiceover and Upscaler have none on Vinci
 * Platform, and their model menu opened empty (fixed 2026-11-12, live UI check).
 */
export function CanvasEmpty({ onPick, canAdd }: { onPick: (capability: string) => void; canAdd?: (capability: string) => boolean }) {
  return (
    <div className="empty first-node" data-testid="choose-first-node">
      <div className="first-node-inner">
        <h2>Choose your first node</h2>
        <div className="first-node-cards">
          {START_CARDS.filter((card) => !canAdd || canAdd(card.capability)).map((card) => (
            <button
              key={card.capability}
              type="button"
              className="first-node-card"
              data-start={card.capability}
              onClick={() => onPick(card.capability)}
            >
              <strong>{card.label}</strong>
              <span>{card.blurb}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
