# ADR-001. Clean repository instead of history rewrite

**Status:** accepted · **Date:** 2026-07-29 · **Sprint:** 0

## Context

The git repository root was the developer's home directory (`/Users/mac`), not the
project. It held zero commits but a 7.2 GB object store: a background
`git add -A` launched by a VS Code extension had been packing `~/.ssh`, private
`.ppk` keys and credential files into `.git/objects`. The working tree also
contained a production SQLite database with three real Telegram `user_id`s and an
exported XLSX with a `user_id` in its filename.

## Decision

1. Move `/Users/mac/.git` out of the home directory rather than rewrite history —
   with zero commits there is no history to rewrite, and `git filter-repo` would
   have nothing to operate on.
2. Initialise a fresh repository scoped to the project directory.
3. Delete the production database and exported XLSX outright; no seed data is
   carried over. Test fixtures will be synthetic from Sprint 1 onwards.
4. `.env.example` is committed and must hold empty values only; real secrets live
   in `.env`, which is git-ignored.

## Consequences

- No personal data and no secret has ever entered a commit — the public repository
  starts genuinely clean, which `git filter-repo` cannot guarantee.
- Historical estimates are unrecoverable. Accepted: they were three users' real
  data, not fixtures.
- The stale 7.2 GB object store still sits at `~/Desktop/OLD-home-git-7GB-MOZHNO-UDALYAT`
  and must be deleted manually — it contains packed copies of private SSH keys.
