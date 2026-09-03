import os

# Dummy but syntactically valid — no real DB/Supabase project exists yet at Phase 1. Set before any
# `app.*` import so `Settings()` (instantiated at module import time) doesn't fail validation.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("MIGRATIONS_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "sb_secret_test")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost"]')
