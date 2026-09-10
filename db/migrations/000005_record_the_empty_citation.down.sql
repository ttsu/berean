-- Re-asserting these will fail if any recorded fabrication carried an empty
-- corpus ID or locator, which is the case the up migration exists for. Delete
-- those rows first, knowing that deleting them is deleting the record of a
-- fabricated citation.
ALTER TABLE trace.verification_results
    ADD CONSTRAINT verification_results_corpus_id_check CHECK (btrim(corpus_id) <> '');

ALTER TABLE trace.verification_results
    ADD CONSTRAINT verification_results_locator_check CHECK (btrim(locator) <> '');
