/** 16px stroke icon for the canvas dock. `d` is one path in a 16 viewBox. */
export function DockIcon({ d }: { d: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export const DOCK_ICON = {
  select: "M4 2.5l8 5.2-3.4.6L7 13.2 4 2.5z",
  pan: "M8 2.5v11M2.5 8h11M4.2 4.2L2.5 8l1.7 3.8M11.8 4.2L13.5 8l-1.7 3.8M4.2 4.2L8 2.5l3.8 1.7M4.2 11.8L8 13.5l3.8-1.7",
  frame: "M3 4.5h10v7H3z",
  text: "M3.5 4h9M8 4v8.5M5.5 12.5h5",
  pen: "M9.5 3.2l3.3 3.3L6.2 13H3v-3.2L9.5 3.2z",
  grid: "M3 3h4v4H3zM9 3h4v4H9zM3 9h4v4H3zM9 9h4v4H9z",
  add: "M8 3v10M3 8h10",
  zoom: "M7 3.2a3.8 3.8 0 1 1 0 7.6 3.8 3.8 0 0 1 0-7.6zM10.2 10.2L13 13",
  undo: "M6.5 4.5L3.5 7.5 6.5 10.5M3.5 7.5h6.2a3 3 0 0 1 0 6H8",
  redo: "M9.5 4.5L12.5 7.5 9.5 10.5M12.5 7.5H6.3a3 3 0 0 0 0 6H8",
  more: "M3.5 8h.01M8 8h.01M12.5 8h.01",
  link: "M6.5 9.5l3-3M7.2 4.8l1-1a2.3 2.3 0 0 1 3.3 3.3l-1 1M8.8 11.2l-1 1a2.3 2.3 0 0 1-3.3-3.3l1-1",
  help: "M6.1 6.1a1.9 1.9 0 1 1 2.6 1.8c-.6.3-.9.7-.9 1.3M8 12h.01",
  gear: "M8 5.4a2.6 2.6 0 1 1 0 5.2 2.6 2.6 0 0 1 0-5.2zM8 2.2v1.3M8 12.5v1.3M2.6 4.4l1.1.7M12.3 10.9l1.1.7M2.6 11.6l1.1-.7M12.3 5.1l1.1-.7",
  heart: "M8 13.2S3.2 10.2 3.2 6.8A2.6 2.6 0 0 1 8 5.6a2.6 2.6 0 0 1 4.8 1.2c0 3.4-4.8 6.4-4.8 6.4z",
  download: "M8 2.5v7M5.2 7.2L8 10l2.8-2.8M3.5 12.5h9",
  copy: "M6 5.5h6.5V13H6zM4 3.5h6.5",
  reference: "M3 4.5h10v7H3zM3 9.5l2.2-2 1.6 1.5L8.6 7 13 10",
  pin: "M8 2.5l1.6 3.2 3.5.5-2.5 2.5.6 3.5L8 10.6 4.8 12.2l.6-3.5L2.9 6.2l3.5-.5z",
  close: "M4 4l8 8M12 4l-8 8",
} as const;