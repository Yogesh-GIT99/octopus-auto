# Operating rules for Claude

Claude Code runs the task board described in [README.md](README.md). These rules decide what it may do on its own and what needs my confirmation. Fast capture of new work is fine; anything that changes existing work or can't be undone needs a person.

## Do without asking
- Any read-only operation: list issues, query the board, read fields.
- Create **new** issues from what I describe, add them to the board, and set their Status, Context, Priority and Effort.
- Add sub-issues to an issue created in the same session.
- Comment on any issue.

## Ask first
- Changing the Status of an **existing** issue, especially to Done.
- Closing an issue, or editing or deleting an existing issue's title or body.
- Creating an issue that might duplicate an existing one.
- Any bulk operation touching 5 or more items.
- Anything uncertain.

**How to ask:** batch it. Show one summary of all proposed changes, for example "move #12 to Done, #15 to In Progress, close #8", and wait for a single yes. Never ask command by command.

## The one exception: "ticket sync"
When I say **"ticket sync"**, run `python3 -m octopus.sync` and apply its changes without the confirmation step, then report what changed. The status docs are already my decision, written in the repos. This exception covers only that command.

## Reading my intent
- "need to", "gotta", "todo" → **Todo**
- "working on", "started" → **In Progress**
- "blocked on", "waiting for", "stuck" → **Blocked**
- "finished", "done" → **Done** (confirm first, except during a sync)
- "someday", "check later", anything vague → **Backlog**

## Always
- After acting, give a short summary of what changed.
- Never delete issues. Items that leave a status doc are reported, not removed.
- When a GitHub API behaviour surprises us, fix the code and add the lesson to [docs/lessons.md](docs/lessons.md).
