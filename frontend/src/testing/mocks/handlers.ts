import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

// VITE_SUPABASE_URL for the test environment (.env.test) — fake project, no real Supabase call
// ever happens in tests, every request below is intercepted.
const SUPABASE_URL = "https://test-project.supabase.co";

const fakeUser = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "owner@example.com",
  app_metadata: { firm_id: "22222222-2222-2222-2222-222222222222", role: "owner" },
};

const fakeSession = {
  access_token: "fake-access-token",
  refresh_token: "fake-refresh-token",
  expires_in: 3600,
  token_type: "bearer",
  user: fakeUser,
};

export const handlers = [
  http.post(`${SUPABASE_URL}/auth/v1/token`, () => HttpResponse.json(fakeSession)),
  http.put(`${SUPABASE_URL}/auth/v1/user`, () => HttpResponse.json(fakeUser)),
];

export const server = setupServer(...handlers);
