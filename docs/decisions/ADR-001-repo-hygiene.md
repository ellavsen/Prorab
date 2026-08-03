# ADR-001. Clean repository instead of history rewrite

**Status:** accepted · **Date:** 2026-07-29 · **Sprint:** 0

## Context

The git repository root was the developer's home directory rather than the
project. It held **zero commits** but a 7.2 GB object store: a background
`git add -A` started by an editor extension had been packing unrelated files
from the home directory into `.git/objects`. The working tree also contained a
production SQLite database with real Telegram `user_id`s and an exported XLSX
carrying a `user_id` in its filename.

## Decision

1. Move the stray `.git` out of the home directory rather than rewrite history —
   with zero commits there is no history to rewrite, and `git filter-repo` would
   have nothing to operate on.
2. Initialise a fresh repository scoped to the project directory.
3. Delete the production database and exported XLSX outright; no seed data is
   carried over. Test fixtures are synthetic from Sprint 1 onwards.
4. `.env.example` is committed and must hold empty values only; real secrets live
   in `.env`, which is git-ignored.

## Consequences

- No personal data and no secret has ever entered a commit — the public
  repository starts genuinely clean, which `git filter-repo` cannot guarantee.
- Historical estimates are unrecoverable. Accepted: they were real users' data,
  not fixtures.
- The project's history therefore begins at Sprint 0. That is deliberate, not a
  squashed past.

## Amendment, Sprint 7: the symptom was closed, the cause was not

Decision 3 deleted the exported XLSX **file**. It did not touch the code that
produced its name, and `f"estimate_{uid}_no{number}_{stamp}.xlsx"` kept
stamping the owner's Telegram id into every generated document for six
sprints. While documents only went back to their author this was nearly
harmless; Sprint 7 sends documents to the customer, and the id would have
travelled with them.

Fixed by making the name a function (`smeta_export.document_filename`) with no
parameter to pass an id into, and by testing the handler's output rather than
the helper alone.

Worth recording as a pattern, not just a fix: an ADR that removes an artefact
has not removed the code that generates it. "The file is gone" and "it cannot
come back" are different claims, and only the second one is a decision.
