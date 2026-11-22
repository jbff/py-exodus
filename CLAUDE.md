# py-exodus: working rules

## Keep the README in sync

Whenever a change makes anything in `README.md` out of date (features,
controls, command-line flags, rules ported from LairWare, autoplay behaviour,
batch results, test counts, branch or workflow), update `README.md` in the
same commit, or in a follow-up commit pushed with it. Don't wait to be asked.

## Other standing rules

- LairWare (`refs/ultima3`) is the correct implementation in any rules
  dispute. Port differences from it as they are found.
- Work on `master`. Never force-push or rewrite it.
- Push only after the full test suite passes with exit code 0
  (check the exit code itself, not a piped tail).
