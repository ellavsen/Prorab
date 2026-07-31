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
