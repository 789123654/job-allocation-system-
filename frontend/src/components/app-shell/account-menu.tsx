import { useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChangePasswordForm } from "@/features/auth/components/change-password-form";
import { supabase } from "@/lib/supabase-client";

export function AccountMenu() {
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="Account menu"
            className="rounded-full border border-(--color-ledger-border) px-3 py-1.5 text-sm"
          >
            Account
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={() => setChangePasswordOpen(true)}>
            Change password
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void supabase.auth.signOut()}>Log out</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={changePasswordOpen} onOpenChange={setChangePasswordOpen}>
        <DialogContent>
          <DialogTitle>Change password</DialogTitle>
          <ChangePasswordForm onSuccess={() => setChangePasswordOpen(false)} />
        </DialogContent>
      </Dialog>
    </>
  );
}
