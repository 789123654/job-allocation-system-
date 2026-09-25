import { act, fireEvent, render } from "@testing-library/react";
import { createPortal } from "react-dom";
import { describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

// Real bug, 2026-09-16: a Select's dropdown (components/ui/select.tsx) renders in its own Portal,
// positioned via @radix-ui/react-popper — a DOM sibling of the Dialog's own Portal under
// document.body, not a descendant of DialogContent, even though it appears "inside" the dialog
// visually. Radix's own outside-click detection (DismissableLayer's usePointerDownOutside, a
// pointerdown listener on the document) saw a click on the Select's dropdown as "outside" the
// Dialog and called onOpenChange(false), silently closing the dialog and wiping every field via
// its own reset — confirmed via a live stack trace captured from the real app. Reproduced here at
// the actual mechanism (a genuine `pointerdown` DOM event, which is what DismissableLayer listens
// for, not a synthetic click) rather than via user-event's higher-level API, which didn't trigger
// this path in earlier attempts.
function PopperLikePortal() {
  return createPortal(
    <div data-radix-popper-content-wrapper>
      <button type="button" data-testid="inside-popper">
        option
      </button>
    </div>,
    document.body,
  );
}

// @radix-ui/react-dismissable-layer (node_modules/@radix-ui/react-dismissable-layer/dist/
// index.mjs) attaches its "outside pointerdown" listener inside `window.setTimeout(fn, 0)`, one
// real macrotask after mount — deliberately, so the same click that opened the layer doesn't
// immediately close it. A `fireEvent.pointerDown` called synchronously right after `render()` can
// fire before that listener exists at all, making a "was not dismissed" assertion pass for the
// wrong reason (no listener, not a working guard). Both tests below wait out that exact timer
// first.
async function waitForOutsidePointerDownListener(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("DialogContent", () => {
  it("still dismisses on a real outside click (negative control, checked first — the guard added below must not swallow a genuine outside click)", async () => {
    const onOpenChange = vi.fn();
    render(
      <>
        <div data-testid="genuinely-outside">elsewhere on the page</div>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent>
            <DialogTitle>Test dialog</DialogTitle>
          </DialogContent>
        </Dialog>
      </>,
    );
    await waitForOutsidePointerDownListener();

    // Radix defers the actual dismiss until a subsequent `click` on the same target (it waits to
    // distinguish a real click from a drag-select) — a real pointer interaction always fires both,
    // so both are fired here too (found by reading handlePointerDown's deferPointerDownOutside
    // branch directly, same file as above).
    const outside = document.querySelector('[data-testid="genuinely-outside"]')!;
    fireEvent.pointerDown(outside);
    fireEvent.click(outside);

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not dismiss when a pointerdown lands inside a Radix popper-positioned popup (e.g. an open Select's portal) — the actual reported bug", async () => {
    const onOpenChange = vi.fn();
    render(
      <>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent>
            <DialogTitle>Test dialog</DialogTitle>
          </DialogContent>
        </Dialog>
        <PopperLikePortal />
      </>,
    );
    await waitForOutsidePointerDownListener();

    const insidePopper = document.querySelector('[data-testid="inside-popper"]')!;
    fireEvent.pointerDown(insidePopper);
    fireEvent.click(insidePopper);

    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
