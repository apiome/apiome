-- Dev seed: sample user.
--
-- Login:    ada@example.com
-- Password: apiome-dev   (bcrypt hash below; DEV ONLY — never load in production)
--
-- Idempotent: re-running leaves the existing row untouched (ON CONFLICT on the fixed id).

INSERT INTO apiome.users (id, name, email, password, verified, enabled)
VALUES (
  '00000000-0000-4000-8000-000000000001',
  'Ada Lovelace',
  'ada@example.com',
  '$2b$10$ubOFS2D0e.u2pYFxsDowfOgqXTOHv6fSF1ZuKi.VVaz301rnaLqVG',
  true,
  true
)
ON CONFLICT (id) DO NOTHING;
