import { LazyStore } from "@tauri-apps/plugin-store";
import { createClient } from "@supabase/supabase-js";
import { env } from "@/config/env";

// Custom storage adapter (supabase/auth/sessions.md's customStorageObject pattern) backed by
// tauri-plugin-store instead of the SDK's own webview-localStorage default — ARCHITECTURE.md §4
// step 3 and FRONTEND_ARCHITECTURE.md §6 both already decided "Tauri secure storage" for the
// session token. LazyStore (not the plain load() function) so this file has no top-level await
// and behaves as a plain singleton like the rest of this module.
const store = new LazyStore("auth-session.json");

export const supabase = createClient(env.SUPABASE_URL, env.SUPABASE_ANON_KEY, {
  auth: {
    storage: {
      getItem: async (key: string) => (await store.get<string>(key)) ?? null,
      setItem: async (key: string, value: string) => {
        await store.set(key, value);
        await store.save();
      },
      removeItem: async (key: string) => {
        await store.delete(key);
        await store.save();
      },
    },
  },
});
