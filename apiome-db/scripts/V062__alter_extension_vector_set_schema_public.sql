ALTER EXTENSION vector SET SCHEMA public;

ALTER TABLE apiome.data_snapshot
  DROP COLUMN embedding,
  ADD COLUMN embedding vector(3072) NULL;
