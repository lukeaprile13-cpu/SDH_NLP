# NLP snapshot used for the preliminary phenotype work

`NLP_v5_snapshot.ipynb` is a copy of `NLP_v5.ipynb` as it stood on branch
`claude/peaceful-lovelace-5czfzi` at commit `8c49931` (v1.3 in progress, not
the frozen v1.2). It is fixed here so the preliminary phenotype datasets are
reproducible while the NLP itself keeps changing; nothing in this folder is
edited by hand.

- SHA-256: `97211fef9e47b0f2bb62c543e3ef46af26c125fb9999f557b07b9982a9bbf3e4`
- Run with `run_nlp.py` (see its header). Needs `spacy` installed; the
  downloaded English model is optional (the notebook falls back to
  `spacy.blank("en")`, same tokens and results).

When the validated (frozen) NLP is ready, replace the snapshot with it,
update this file, and rerun from `run_nlp.py` onwards.
