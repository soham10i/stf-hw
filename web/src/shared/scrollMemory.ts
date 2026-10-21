// Where each page (or panel) was scrolled to, for this visit only: a page opens at the top the
// first time it is shown after a load, and where it was left when it is shown again. Kept in
// memory, never in storage, so a reload starts every page at the top.
import { useLayoutEffect, useRef } from "react";

const memory = new Map<string, number>();

// the browser must not restore the window's old scroll on a reload: every page starts at the top
if (typeof history !== "undefined" && "scrollRestoration" in history) history.scrollRestoration = "manual";

/** Remember the scroll of `key`'s page in a box (`box()`, an element) or in the window (no box),
    and put it back when `key` is shown again. An empty key (the box is not shown) does nothing.
    Content that is still loading is waited for (a few frames) before the position is given up. */
export function useScrollMemory(key: string, box?: () => HTMLElement | null) {
  const restoring = useRef(false);
  const get = useRef(box);
  get.current = box;
  useLayoutEffect(() => {
    if (!key) return;
    const el = get.current ? get.current() : null;
    if (get.current && !el) return;  // its box is not on the page
    const y = () => (el ? el.scrollTop : window.scrollY);
    const to = (v: number) => (el ? (el.scrollTop = v) : window.scrollTo(0, v));
    const on = () => { if (!restoring.current) memory.set(key, y()); };
    const target: EventTarget = el ?? window;
    target.addEventListener("scroll", on, { passive: true });
    // put the page back where it was left, or at the top
    const want = memory.get(key) ?? 0;
    restoring.current = true;
    let n = 0, raf = 0;
    const step = () => {
      to(want);
      if (Math.abs(y() - want) > 2 && n++ < 40) raf = requestAnimationFrame(step);
      else restoring.current = false;
    };
    step();
    return () => { cancelAnimationFrame(raf); restoring.current = false; target.removeEventListener("scroll", on); };
  }, [key]);
}
