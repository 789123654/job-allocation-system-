import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

export type LoginInput = z.infer<typeof loginSchema>;

// ARCHITECTURE.md §4 password policy: ASVS 6.2.1 minimum length 8 (15+ recommended), ASVS 6.2.5 no
// forced composition rules — deliberately not adding upper/lower/digit/symbol requirements.
const newPasswordField = z.string().min(8, "Password must be at least 8 characters");

// Set New Password (forced, one-time) and Change Password (self-service) share the same fields —
// both call supabase.auth.updateUser({ current_password, password }) per ARCHITECTURE.md §4,
// which requires the current password even for the forced first-login change (ASVS 6.2.3).
export const passwordChangeSchema = z.object({
  currentPassword: z.string().min(1, "Current password is required"),
  newPassword: newPasswordField,
});

export type PasswordChangeInput = z.infer<typeof passwordChangeSchema>;
