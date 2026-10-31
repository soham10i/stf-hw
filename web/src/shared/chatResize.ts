import { useState, useRef } from "react";
import { usePersistent } from "./persist";

/**
 * Hook for resizing the pinned copilot inspector (horizontal spacing).
 * Just like the sidebar of the 3D twin (.side-grip), the user can drag
 * the left edge of the right-pinned copilot to adjust its horizontal width.
 */
export function useCopilotResize(defaultW = 400) {
  const [width, setWidth] = usePersistent<number>("stf.copilot.w", defaultW);
  const [dragW, setDragW] = useState<number | null>(null);
  const start = useRef<{ x: number; w: number; moved: boolean } | null>(null);

  const gripProps = {
    onPointerDown: (e: React.PointerEvent) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      start.current = { x: e.clientX, w: width, moved: false };
    },
    onPointerMove: (e: React.PointerEvent) => {
      const s = start.current;
      if (!s) return;
      const dx = e.clientX - s.x;
      if (Math.abs(dx) > 2) s.moved = true;
      if (s.moved) {
        const minW = 300;
        const maxW = Math.max(minW, Math.min(760, window.innerWidth - 300));
        // Moving pointer left (dx < 0) expands the right-docked panel
        setDragW(Math.max(minW, Math.min(maxW, s.w - dx)));
      }
    },
    onPointerUp: () => {
      const s = start.current;
      start.current = null;
      if (s?.moved && dragW !== null) {
        setWidth(dragW);
      }
      setDragW(null);
    },
    onPointerCancel: () => {
      start.current = null;
      setDragW(null);
    },
  };

  return {
    width: dragW ?? width,
    isDragging: dragW !== null,
    gripProps,
  };
}

export type Corner = "tl" | "tr" | "bl" | "br" | "custom";

/**
 * Hook for resizing and freely moving the floating chatbot window.
 * Allows the user to adjust both width and height via drag handles,
 * drag the window anywhere on screen via the header, or dock to any of the 4 corners.
 */
export function useFloatChatResize(defaultW = 440, defaultH = 640) {
  const [size, setSize] = usePersistent<{ w: number; h: number }>("stf.float.size", { w: defaultW, h: defaultH });
  const [pos, setPos] = usePersistent<{ x: number; y: number } | null>("stf.float.pos", null);
  const [corner, setCorner] = usePersistent<Corner>("stf.float.corner", "br");

  const [dragSize, setDragSize] = useState<{ w: number; h: number } | null>(null);
  const [dragPos, setDragPos] = useState<{ x: number; y: number } | null>(null);

  const startResize = useRef<{ x: number; y: number; w: number; h: number; dir: string; moved: boolean } | null>(null);
  const startDrag = useRef<{ startX: number; startY: number; posX: number; posY: number; moved: boolean } | null>(null);

  const currentW = dragSize?.w ?? size.w;
  const currentH = dragSize?.h ?? size.h;

  // Compute corner coordinates based on current window dimensions
  const getCornerPos = (c: Corner, w = currentW, h = currentH): { x: number; y: number } => {
    const pad = 24;
    const vpW = typeof window !== "undefined" ? window.innerWidth : 1280;
    const vpH = typeof window !== "undefined" ? window.innerHeight : 800;
    switch (c) {
      case "tl":
        return { x: pad, y: pad };
      case "tr":
        return { x: Math.max(pad, vpW - w - pad), y: pad };
      case "bl":
        return { x: pad, y: Math.max(pad, vpH - h - pad) };
      case "br":
      default:
        return { x: Math.max(pad, vpW - w - 8), y: Math.max(pad, vpH - h - 60) };
    }
  };

  // The active position: dragPos if actively dragging, else pos, else fallback to corner pos
  const position = dragPos ?? (pos ?? getCornerPos(corner));

  const snapToCorner = (c: Corner) => {
    const newPos = getCornerPos(c);
    setCorner(c);
    setPos(newPos);
  };

  const cycleCorner = () => {
    const corners: Corner[] = ["br", "bl", "tl", "tr"];
    const idx = corners.indexOf(corner === "custom" ? "br" : corner);
    const next = corners[(idx + 1) % corners.length];
    snapToCorner(next);
  };

  // Header drag handlers (allows moving window anywhere on screen)
  const headerDragProps = {
    onPointerDown: (e: React.PointerEvent) => {
      // Don't drag if user clicked a button or interactive child
      if ((e.target as HTMLElement).closest("button, a, input, select")) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      startDrag.current = {
        startX: e.clientX,
        startY: e.clientY,
        posX: position.x,
        posY: position.y,
        moved: false,
      };
    },
    onPointerMove: (e: React.PointerEvent) => {
      const s = startDrag.current;
      if (!s) return;
      const dx = e.clientX - s.startX;
      const dy = e.clientY - s.startY;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) s.moved = true;
      if (s.moved) {
        const vpW = window.innerWidth;
        const vpH = window.innerHeight;
        const minX = 12;
        const maxX = Math.max(12, vpW - currentW - 12);
        const minY = 12;
        const maxY = Math.max(12, vpH - currentH - 12);
        const nextX = Math.max(minX, Math.min(maxX, s.posX + dx));
        const nextY = Math.max(minY, Math.min(maxY, s.posY + dy));
        setDragPos({ x: nextX, y: nextY });
      }
    },
    onPointerUp: () => {
      const s = startDrag.current;
      startDrag.current = null;
      if (s?.moved && dragPos) {
        setPos(dragPos);
        setCorner("custom");
      }
      setDragPos(null);
    },
    onPointerCancel: () => {
      startDrag.current = null;
      setDragPos(null);
    },
  };

  // Resizing grips (left, right, top, bottom, corner)
  const getGripProps = (dir: "left" | "top" | "corner") => ({
    onPointerDown: (e: React.PointerEvent) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      e.stopPropagation();
      startResize.current = { x: e.clientX, y: e.clientY, w: currentW, h: currentH, dir, moved: false };
    },
    onPointerMove: (e: React.PointerEvent) => {
      const s = startResize.current;
      if (!s) return;
      const dx = e.clientX - s.x;
      const dy = e.clientY - s.y;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) s.moved = true;
      if (s.moved) {
        const minW = 340;
        const maxW = Math.max(minW, Math.min(900, window.innerWidth - 32));
        const minH = 400;
        const maxH = Math.max(minH, Math.min(960, window.innerHeight - 80));

        let newW = s.w;
        let newH = s.h;

        // If anchored on right side: dragging left expands
        // If anchored on left side: dragging right expands
        const isLeftSide = position.x < (window.innerWidth / 2) - 100;
        if (s.dir === "left" || s.dir === "corner") {
          newW = isLeftSide ? Math.max(minW, Math.min(maxW, s.w + dx)) : Math.max(minW, Math.min(maxW, s.w - dx));
        }
        const isTopSide = position.y < (window.innerHeight / 2) - 100;
        if (s.dir === "top" || s.dir === "corner") {
          newH = isTopSide ? Math.max(minH, Math.min(maxH, s.h + dy)) : Math.max(minH, Math.min(maxH, s.h - dy));
        }
        setDragSize({ w: newW, h: newH });
      }
    },
    onPointerUp: () => {
      const s = startResize.current;
      startResize.current = null;
      if (s?.moved && dragSize !== null) {
        setSize(dragSize);
      }
      setDragSize(null);
    },
    onPointerCancel: () => {
      startResize.current = null;
      setDragSize(null);
    },
  });

  return {
    width: currentW,
    height: currentH,
    position,
    corner,
    isDragging: dragSize !== null,
    isMoving: dragPos !== null,
    headerDragProps,
    snapToCorner,
    cycleCorner,
    getGripProps,
  };
}
