// Fails fast at startup on a missing var, same reasoning as backend/app/core/config.py's
// Settings(BaseSettings) — a misconfigured deploy should error loudly here, not surface as a
// confusing runtime failure the first time supabase-client.ts or api-client.ts is used.
function requireEnv(key: string): string {
  const value = import.meta.env[key];
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

export const env = {
  SUPABASE_URL: requireEnv("VITE_SUPABASE_URL"),
  SUPABASE_ANON_KEY: requireEnv("VITE_SUPABASE_ANON_KEY"),
  API_BASE_URL: requireEnv("VITE_API_BASE_URL"),
};
