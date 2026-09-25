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
  // Optional, same as backend/app/core/config.py's SENTRY_DSN — unset (dev/test/CI) means Sentry
  // is never initialized, not a missing-config error.
  SENTRY_DSN: import.meta.env.VITE_SENTRY_DSN as string | undefined,
  // Optional build identifier stamped on Sentry events (e.g. a git SHA set by the build) — lets a
  // crash be tied to the exact desktop build that produced it. Unset just means no release tag.
  SENTRY_RELEASE: import.meta.env.VITE_SENTRY_RELEASE as string | undefined,
};
