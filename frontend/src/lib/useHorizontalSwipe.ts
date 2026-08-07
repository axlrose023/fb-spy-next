import { useRef, type MouseEvent as ReactMouseEvent, type TouchEvent as ReactTouchEvent } from "react";

const INTERACTIVE_SELECTOR = "button,a,input,select,textarea,video,[role='button']";

type SwipeOptions = {
  enabled: boolean;
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  ignoreSelector?: string;
  threshold?: number;
};

type TouchStart = {
  x: number;
  y: number;
};

export function useHorizontalSwipe({
  enabled,
  onSwipeLeft,
  onSwipeRight,
  ignoreSelector,
  threshold = 56,
}: SwipeOptions) {
  const touchStart = useRef<TouchStart | null>(null);
  const suppressClick = useRef(false);

  const shouldIgnore = (target: EventTarget | null) => {
    if (!(target instanceof Element)) return false;
    const selector = ignoreSelector
      ? `${INTERACTIVE_SELECTOR},${ignoreSelector}`
      : INTERACTIVE_SELECTOR;
    return Boolean(target.closest(selector));
  };

  const onTouchStart = (event: ReactTouchEvent<HTMLElement>) => {
    touchStart.current = null;
    if (!enabled || event.touches.length !== 1 || shouldIgnore(event.target)) return;
    const touch = event.touches[0];
    touchStart.current = { x: touch.clientX, y: touch.clientY };
  };

  const onTouchEnd = (event: ReactTouchEvent<HTMLElement>) => {
    const start = touchStart.current;
    touchStart.current = null;
    if (!enabled || !start || event.changedTouches.length !== 1) return;

    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    const horizontal = Math.abs(dx);
    const vertical = Math.abs(dy);
    if (horizontal < threshold || horizontal <= vertical * 1.25) return;

    suppressClick.current = true;
    if (dx < 0) onSwipeLeft?.();
    else onSwipeRight?.();
    window.setTimeout(() => {
      suppressClick.current = false;
    }, 350);
  };

  const onTouchCancel = () => {
    touchStart.current = null;
  };

  const onClickCapture = (event: ReactMouseEvent<HTMLElement>) => {
    if (!suppressClick.current) return;
    suppressClick.current = false;
    event.preventDefault();
    event.stopPropagation();
  };

  return { onTouchStart, onTouchEnd, onTouchCancel, onClickCapture };
}
