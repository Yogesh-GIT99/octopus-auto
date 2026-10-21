# Example status docs

**These are made-up projects for the demo board.** They follow the same format as the real status docs octopus-auto syncs from, so anyone can run the tool end to end without access to private repos.

| Folder | Pretend project | Board context |
|---|---|---|
| [edge-fleet/](edge-fleet/STATUS.md) | Moving a web server fleet to ARM, managed as code | Fleet |
| [deploy-platform/](deploy-platform/STATUS.md) | A container deployment platform | Platform |
| [terraform-prep/](terraform-prep/STATUS.md) | Interview prep, tracked the same way | Learning |

Edit any of them (move a bullet from Ongoing to Done, add one under Upcoming), run `python3 -m octopus.sync`, and the board follows.
