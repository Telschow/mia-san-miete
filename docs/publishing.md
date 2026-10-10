# Before making the repository public

A checklist for the owner. The automated scan covers generic patterns only. Your personal terms (employers, addresses, names, income) can only be checked on your own machine.

## 1. Scan the whole history

```bash
git fetch --all --unshallow   # a shallow clone does not pass
mia check-history             # generic patterns
mia check-history --terms .private-terms   # plus your own terms, run locally only
```

The scanner reads every file version reachable from any ref, all commit messages, author and committer names and emails, and ref names. It reports commit, path and line, never the matched text. Binary files are listed so you can look at them by hand. CI runs the generic scan on every push.

Result of the scan on 2026-10-10 (22 commits, all refs):

- No emails, phone numbers or IBANs found.
- No token or key patterns found.
- 10 PNG screenshot versions and 7 font files are listed as binaries. The screenshots are generated from the fictional demo data.
- Issues, comments, pull requests and milestones were checked as well. Nothing found.

What this does not cover: anything specific to you. Run the `--terms` line above once, locally.

## 2. Decide about the session links

20 commit messages end with a `Claude-Session:` link. The link points to a private session, so it is not a leak, but it is noise on a public repo. Options:

1. Accept it.
2. Publish a fresh repository with one squashed commit.
3. Rewrite the messages with `git filter-repo` and force-push. You must run this yourself.

## 3. Housekeeping

- Get the `LICENSE` (MIT) onto `main`.
- Set a repository description and topics.
- Read the issue texts once before going public.
- Make sure the old repository `Telschow/mia-san-miete` is deleted.
- Enable GitHub secret scanning and push protection after it is public.
- Polish the README. Optionally add a `SECURITY.md`.

## 4. Be honest about scope

Portal automation is not implemented (ADR 0006). The README, the video and any post must say: finds, scores and drafts; sending through portals is manual for now.
