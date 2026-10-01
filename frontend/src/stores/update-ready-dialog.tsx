import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

// Global, not feature-local (bulletproof-react "Application state": must be able to interrupt
// any route) — mounted once from app/provider.tsx, same placement as SessionProvider.
//
// Rust side (src-tauri/src/lib.rs) downloads+installs the update BEFORE emitting this event —
// "Restart Now" below only ever triggers the restart itself, never a second install (reviewed
// 2026-10-02, Business_Logic_Security_Cheat_Sheet.md's race-condition guidance). "Later" is the
// only way to dismiss — outside-click/Escape are deliberately disabled so the choice is explicit,
// not accidental.
export function UpdateReadyDialog() {
  const [open, setOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    const unlisten = listen("update-ready", () => setOpen(true));
    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);

  async function handleRestart() {
    setRestarting(true);
    try {
      await invoke("confirm_restart");
    } catch {
      // Success means the process exits and this call never resolves — an error here means the
      // restart itself failed to fire; nothing more to do client-side than let them retry.
      setRestarting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent>
        <DialogTitle>Update ready</DialogTitle>
        <div className="flex flex-col gap-4">
          <p className="text-sm text-(--color-ledger-text-muted)">
            A new version has been downloaded. Restart now to apply it, or continue working and
            restart later.
          </p>
          <div className="flex gap-2">
            <Button type="button" onClick={handleRestart} disabled={restarting}>
              {restarting ? "Restarting…" : "Restart Now"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Later
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
