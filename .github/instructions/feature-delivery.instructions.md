---
description: "Use when implementing or changing features in this repository; covers feature branches, scoped commits, pushing, pull requests, and delivery Definition of Done."
---

# Feature Delivery

- For feature changes, use a dedicated branch from the verified base branch;
  prefer `main` when it is the repository's established PR target. Reuse the
  current branch when it is already the task branch.
- Before editing, inspect the repository root, current branch, worktree status,
  staged diff, and upstream. Preserve unrelated and pre-existing staged work;
  never assume untracked files are part of the task.
- Validate the requested behavior with relevant project checks. Review the
  final diff, stage only explicit task paths, and verify the staged path list
  before committing.
- By default, finish feature delivery by committing with a concise conventional
  message, pushing to the verified upstream, and opening a PR to the verified
  base branch. Summarize the change and validation in the PR body.
- Verify the commit, pushed branch, and PR head/base/URL. If PR creation is
  unavailable, report the blocker and provide a compare URL without claiming
  the PR was opened. Honor explicit requests to leave work uncommitted,
  unpublished, or without a PR.
