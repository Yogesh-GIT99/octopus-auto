# Lessons from real use

Each of these broke a run on my real board at least once. Each now has a fix in the code and a note here.

**Project item lists truncate silently.** `gh project item-list` returns one page by default. Past about 50 items, the newest tickets were missing, so freshly created issues looked like they had failed. Fix: always paginate the GraphQL `items` connection (`Board._load_items`).

**Auto-add races the sync.** A board with an auto-add workflow adds a new issue on its own a moment after it's created. The explicit add then fails with "Content already exists in this project". Fix: catch that error and look up the existing item through the issue's `projectItems` (`Board.add`). This was caught again while building this demo, before the fix landed here.

**Done auto-closes the issue.** A board workflow closes an issue when its Status becomes Done, so a following `gh issue close` fails with "Could not close the issue". Fix: close and reopen with a REST `PATCH` to the target state, which is idempotent.

**Interrupted runs must be re-runnable.** A network drop halfway through a big sync left some issues created but without fields. Fix: never remember state locally. Every run re-derives the plan from the doc and the epic's current sub-issues, so the next run fills in what's missing.

**Several `gh` accounts on one machine.** With work and personal accounts both logged in, the active account decides which repos are visible. Board and git operations failed with "Repository not found". Fix: run with the intended account's token explicitly (`GH_TOKEN=$(gh auth token -u <user>)`) instead of switching the global active account.

**Writing Projects v2 fields needs the `project` scope.** The base `repo` scope covers issues only. Run `gh auth refresh -s project` once.

**Some status docs are gitignored.** A source repo can keep its status doc local only. Reading it from GitHub then returns 404, so read the local checkout (`status_doc` is a local path).

**Position is not identity.** Matching on position ("task 5 is issue 7") went wrong as soon as an epic offset the numbering. Fix: match only on normalised titles.
