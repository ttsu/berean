-- Reverse of 000001, dropped in dependency order. Grants go with the objects
-- they were made on; the schemas themselves are the init script's and survive.
DROP VIEW IF EXISTS corpus.chunk_metadata;
DROP TABLE IF EXISTS corpus.chunk_embeddings;
DROP TABLE IF EXISTS corpus.chunks;
DROP TABLE IF EXISTS corpus.works;
DROP TYPE IF EXISTS corpus.text_form;
DROP TYPE IF EXISTS corpus.license;
