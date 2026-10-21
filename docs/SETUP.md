# Setting up your own board

## 1. Create the board

```bash
gh auth refresh -s project
gh project create --owner <you> --title "My board"
gh project link <number> --owner <you> --repo <you>/<issues-repo>
for spec in "Context:Fleet,Platform,Learning" "Priority:High,Med,Low" "Effort:S,M,L"; do
  gh project field-create <number> --owner <you> --name "${spec%%:*}" \
    --data-type SINGLE_SELECT --single-select-options "${spec#*:}"
done
```

The built-in **Status** field needs five options: Backlog, Todo, In Progress, Blocked, Done. Set them in the board's field settings, or with the `updateProjectV2Field` GraphQL mutation.

## 2. Create one epic per source

```bash
gh issue create -R <you>/<issues-repo> --title "[Platform] Deploy platform" --body "Epic."
```

## 3. Register the source in `sources.json`

```json
{ "name": "deploy-platform", "status_doc": "../deploy-platform/STATUS.md",
  "context": "Platform", "epic_issue": 2, "title_prefix": "[Platform] " }
```

`status_doc` is relative to `sources.json`, so point it at the local checkout. Field names are resolved at runtime, so no IDs go in the config. Optional per-source keys are `priority`, `effort` and `active`.

## 4. Run it

```bash
python3 -m octopus.sync --dry-run
python3 -m octopus.sync
python3 -m octopus.sync -s deploy-platform   # one source only
```
