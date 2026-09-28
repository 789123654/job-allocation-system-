import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// Real bug, 2026-09-17: SelectContent (and the Dialog's Overlay in dialog.tsx) had no explicit
// z-index, so a Select opened inside a Dialog stacked purely by DOM insertion order — which
// resolved with the Dialog's Overlay winning the hit-test, silently swallowing every click meant
// for a SelectItem. Confirmed live via a document-level pointerdown-target log in the real Tauri
// app (not reproducible in jsdom — Testing Library dispatches events directly on the queried
// element, bypassing real hit-testing). This test only guards the part jsdom *can* verify: that
// SelectContent keeps an explicit z-index class, so a future edit can't silently drop it back to
// z-index:auto and reintroduce the stacking race.
describe("SelectContent", () => {
  it("renders with an explicit z-index so it can never lose the stacking order to a Dialog's overlay", async () => {
    render(
      <Select open>
        <SelectTrigger>
          <SelectValue placeholder="Pick one" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">Option A</SelectItem>
        </SelectContent>
      </Select>,
    );

    const option = await screen.findByRole("option", { name: "Option A" });
    const contentEl = option.closest('[role="listbox"]');
    expect(contentEl?.className).toMatch(/\bz-50\b/);
  });
});
