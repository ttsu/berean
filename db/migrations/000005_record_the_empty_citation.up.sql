-- Let the audit log hold the fabrication it exists to hold.
--
-- `trace.verification_results` was created with `CHECK (btrim(corpus_id) <> '')`
-- and the same on `locator`, alongside a comment explaining why the table
-- carries **no** foreign key into `corpus.works`: "a citation to a corpus that
-- does not exist is precisely what check 1 records, and a foreign key would
-- make the fabrication unrecordable."
--
-- The two CHECKs do that very thing, one level down. Nothing constrains the
-- generator to a non-empty `corpus_id`: Catena's structured-output schema marks
-- the citation's fields required, meaning the key is present, and emits no
-- `minLength` -- so `"corpus_id": ""` is a valid generation. Verification
-- handles it correctly and records a check-1 failure against an empty
-- reference. Persistence then could not write that row, and because the whole
-- turn is one transaction, an empty `corpus_id` cost the entire trace:
-- the response, both attempts, every candidate and every other citation.
--
-- Under the rule that a turn is persisted before it is rendered, the user then
-- sees an error where the honest outcome was "I can't source this adequately" --
-- a fabricated citation turning into a crash at exactly the moment the system
-- was working as designed.
--
-- So the columns keep NOT NULL and lose the emptiness check. An empty string
-- here is not missing data; it is a faithful record of what the model emitted,
-- and it is the shape of fabrication that is hardest to see in a log.
ALTER TABLE trace.verification_results
    DROP CONSTRAINT IF EXISTS verification_results_corpus_id_check;

ALTER TABLE trace.verification_results
    DROP CONSTRAINT IF EXISTS verification_results_locator_check;

-- `trace.candidates` and `trace.answer_failures` keep theirs, and the
-- difference is not an oversight.
--
-- A candidate is retrieval's own output: the gateway never invents one, and a
-- blank `corpus_id` there would be a bug in Catena's retrieval rather than a
-- model fabrication worth recording.
--
-- Every `citation_ref` that reaches `answer_failures` comes from one of two
-- places, and neither can be blank: a `ContestedLocus` the gateway itself sent,
-- or the list of citations that passed all four checks -- which means they
-- resolved, which means they name a real corpus and a real locator. The
-- answer-level rules that are about a slot's emptiness carry no reference at
-- all, and `answer_failures_ref_is_whole_or_absent` is what holds that apart
-- from half of one.
