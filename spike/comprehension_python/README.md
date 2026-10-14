# Spike: comprehension on Python (DO NOT MERGE)

Throwaway code for the two-day trial in `docs/design/comprehension-python.md`, section 8. Nothing here is part of
agenttalk, nothing imports it, and no product file is changed on this branch. The result, in plain words, is in
`RESULT.md` beside this file; the attached output is in `output/`.

## What is here

| File | Spike question | What it does |
|---|---|---|
| `claims.py` | S4 | The shared claim types (`FileClaims` and four claim types) and their JSON wire form |
| `java_convert.py` | S4 | Java result to `FileClaims` and back, with `adapters/java.py` untouched |
| `roundtrip_plugin.py` | S4 | A pytest plugin: every Java result the comprehension tests produce at a public boundary goes through the round trip |
| `py_reader.py` | S1, S3, S6 | The prototype Python reader: decoding, dialect markers, line-preserving Python 2 repairs, `ast` extraction, token outline |
| `project.py` | S1 | The file walk, packaging evidence, the dialect decision (rules 1-4) and module names from the import roots |
| `resolve.py` | S2, S3, S6 | Import resolution, inheritance and models, views, Django URL composition, the S2 oracle, by-name strings |
| `run_spike.py` | S1-S6 | Runs one codebase and writes the outputs |

## How it was run

Read-only on scratch copies of the two codebases; nothing of theirs is imported or run.

    PYTHONPATH="src;spike" python -m comprehension_python.run_spike --root <copy> --label satchmo \
        --own-packages <oracle list> --out <dir>
    PYTHONPATH="src;spike" SPIKE_ROUNDTRIP_OUT=<file> python -m pytest -p comprehension_python.roundtrip_plugin \
        tests/test_*comprehension*.py

The same commands ran on Python 3.10.11 (`py -3.10`) and Python 3.14.6.
