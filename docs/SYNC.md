# The sync algorithm

`python3 -m octopus.sync` reconciles the board with every active source in `sources.json`.

## For each source

1. **Skip** it if `"active": false`.
2. **Parse** its `status_doc`. Under headings containing *Done*, *Ongoing* / *In progress*, or *Upcoming* / *Backlog* / *Next up*, every **top-level** bullet whose text starts with `**bold**` is one item. Nested bullets are detail. A heading that matches none of these (for example `## Notes`) ends tracking until the next matching one. A struck-through item (`~~**x**~~`) counts as done wherever it sits.
3. **Target status** for each item:

   | Section | Wording | Status |
   |---|---|---|
   | Done | any | Done (issue closed) |
   | Ongoing | "blocked on/by", "waiting for/on", "stuck on" | Blocked |
   | Ongoing | starts with "Next:", "need to", "todo" | Todo |
   | Ongoing | anything else | In Progress |
   | Upcoming | any | Backlog |

4. **Load the epic's sub-issues** (REST) and each one's current board Status (GraphQL, paginated).
5. **Plan** (a pure function, unit-tested). Match items to issues by normalised title: leading `[tags]`, case and punctuation are ignored.
   - No match → **create** the issue, link it as a sub-issue of the epic, add it to the board, and set Status, Context, Priority and Effort.
   - Match not on the board → **add** it.
   - Status differs → **move** it.
   - Target Done and issue open → **close**. Target not Done and issue closed → **reopen**.
   - Issue in the epic but not in the doc → **report only**.
   - The same title twice in a doc → keep the first, report the duplicate.
6. **Apply** the plan, or print it with `--dry-run`.

## Guarantees

- **Idempotent.** A second run straight after the first makes no writes.
- **Restartable.** If a run dies halfway, re-running finishes the job without duplicates, because issues are found by title in the epic, not remembered locally.
- **Scoped.** A source only ever touches sub-issues of its own epic.
- **Non-destructive.** Nothing is deleted.
