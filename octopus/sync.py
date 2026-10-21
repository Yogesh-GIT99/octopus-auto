"""Keep a GitHub Projects board in sync with the status docs in my repos.

A status doc has three sections, and each top-level bullet is one ticket:

    ## ✅ Done
    - **Server creation as code** — module, SG, EIP
    ## 🔄 Ongoing
    - **SSH lockdown** — blocked on the VPN CIDR
    ## 📋 Upcoming
    - **CI for the platform**

Running it twice in a row changes nothing the second time.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DONE = "Done"
IN_PROGRESS = "In Progress"
TODO = "Todo"
BLOCKED = "Blocked"
BACKLOG = "Backlog"

# The first match wins, so "Done" is checked before the others.
SECTIONS = [
    ("done", re.compile(r"\bdone\b", re.I)),
    ("ongoing", re.compile(r"\b(ongoing|in progress)\b", re.I)),
    ("upcoming", re.compile(r"\b(upcoming|backlog|next up|planned)\b", re.I)),
]
HEADING = re.compile(r"^(#{2,3})\s+(.*)$")
BULLET = re.compile(r"^[-*]\s+(~~)?\*\*(.+?)\*\*(?:~~)?\s*(?:[—–:-]+\s*(.*))?$")
BLOCKED_WORDS = re.compile(r"\b(blocked (on|by)|waiting (for|on)|stuck on)\b", re.I)
TODO_WORDS = re.compile(r"^(next:|need to\b|todo\b)", re.I)


# --- Reading the status doc ---

@dataclass
class Item:
    title: str
    description: str
    section: str  # "done", "ongoing" or "upcoming"

    @property
    def target_status(self) -> str:
        if self.section == "done":
            return DONE
        if self.section == "upcoming":
            return BACKLOG
        if BLOCKED_WORDS.search(self.description):
            return BLOCKED
        if TODO_WORDS.search(self.description.strip()):
            return TODO
        return IN_PROGRESS


def parse_status_doc(text: str) -> list[Item]:
    items = []
    section = None

    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            found = next((name for name, pattern in SECTIONS if pattern.search(title)), None)
            if found:
                section = found
            elif level == 2:
                section = None  # e.g. "## Notes": stop collecting until the next known section
            continue

        # Indented bullets are details of the item above, not items of their own.
        if section is None or line.startswith((" ", "\t")):
            continue

        bullet = BULLET.match(line.rstrip())
        if bullet:
            struck_out, title, description = bullet.groups()
            items.append(Item(
                title=title.strip(),
                description=(description or "").strip(),
                section="done" if struck_out else section,
            ))

    return items


def normalize(title: str) -> str:
    """'[Fleet] SSH lock-down!' and 'ssh lock down' should match."""
    title = re.sub(r"^(\s*\[[^\]]*\]\s*)+", "", title)
    return " ".join(re.sub(r"[^0-9a-z]+", " ", title.lower()).split())


# --- Working out what to change ---

@dataclass
class Issue:
    number: int
    title: str
    open: bool
    status: str | None  # None means the issue isn't on the board yet


@dataclass
class Action:
    kind: str  # "create", "add", "status", "close" or "reopen"
    title: str
    number: int | None = None
    to: str | None = None
    frm: str | None = None
    body: str = ""

    def __str__(self) -> str:
        ref = f"#{self.number}" if self.number else "new"
        if self.kind == "status":
            return f"  ~ {ref:>5}  {self.frm or '(none)'} -> {self.to}   {self.title}"
        symbol = {"create": "+", "add": "+", "close": "x", "reopen": "o"}[self.kind]
        target = f" [{self.to}]" if self.kind == "create" else ""
        return f"  {symbol} {ref:>5}  {self.kind}{target}   {self.title}"


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    vanished: list[Issue] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


def plan_source(items: list[Item], issues: list[Issue], prefix: str = "") -> Plan:
    """Compare the doc with the epic's issues. No API calls here, so it's easy to test."""
    plan = Plan()
    issues_by_title = {normalize(issue.title): issue for issue in issues}
    seen = set()

    for item in items:
        key = normalize(item.title)
        if key in seen:
            plan.duplicates.append(item.title)
            continue
        seen.add(key)

        target = item.target_status
        issue = issues_by_title.get(key)

        if issue is None:
            plan.actions.append(Action("create", prefix + item.title, to=target, body=item.description))
            continue
        if issue.status is None:
            plan.actions.append(Action("add", issue.title, issue.number))
        if issue.status != target:
            plan.actions.append(Action("status", issue.title, issue.number, to=target, frm=issue.status))
        if target == DONE and issue.open:
            plan.actions.append(Action("close", issue.title, issue.number))
        elif target != DONE and not issue.open:
            plan.actions.append(Action("reopen", issue.title, issue.number))

    # Removed from the doc: report it, never delete it.
    plan.vanished = [issue for issue in issues if normalize(issue.title) not in seen]
    return plan


# --- Talking to GitHub ---

def gh(*args: str, payload: dict | None = None):
    command = ["gh", "api", *args]
    if payload is not None:
        command += ["--input", "-"]

    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"gh api {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def graphql(query: str, **variables):
    response = gh("graphql", payload={"query": query, "variables": variables})
    if response.get("errors"):
        raise RuntimeError(response["errors"])
    return response["data"]


FIND_PROJECT = """
query($login: String!, $number: Int!) {
  %s(login: $login) {
    projectV2(number: $number) {
      id
      fields(first: 50) {
        nodes { ... on ProjectV2SingleSelectField { id name options { id name } } }
      }
    }
  }
}"""

LIST_ITEMS = """
query($id: ID!, $after: String) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content { ... on Issue { number repository { nameWithOwner } } }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { id } }
              }
            }
          }
        }
      }
    }
  }
}"""

ADD_ITEM = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } }
}"""

FIND_ITEM = """
query($content: ID!) {
  node(id: $content) {
    ... on Issue { projectItems(first: 50) { nodes { id project { id } } } }
  }
}"""

SET_FIELD = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field,
    value: {singleSelectOptionId: $option}
  }) { clientMutationId }
}"""


class Board:
    def __init__(self, owner: str, number: int, fields: dict[str, str]):
        project = self._find_project(owner, number)
        self.id = project["id"]

        # Fields are looked up by name, so the config never needs GitHub's IDs.
        by_name = {f["name"]: f for f in project["fields"]["nodes"] if f}
        self.fields = {}
        for key, name in fields.items():
            if name not in by_name:
                raise SystemExit(f"Board has no single-select field named {name!r}")
            options = {o["name"]: o["id"] for o in by_name[name]["options"]}
            self.fields[key] = (by_name[name]["id"], options)

        self.items = self._load_items()

    @staticmethod
    def _find_project(owner: str, number: int) -> dict:
        for owner_type in ("user", "organization"):
            try:
                project = graphql(FIND_PROJECT % owner_type, login=owner, number=number)[owner_type]["projectV2"]
            except (RuntimeError, TypeError):
                continue
            if project:
                return project
        raise SystemExit(f"Project {owner}#{number} not found")

    def _load_items(self) -> dict:
        """Map (repo, issue number) to (board item id, current Status)."""
        status_field_id = self.fields["status"][0]
        items, cursor = {}, None

        # Always page through: a single page silently drops items on a big board.
        while True:
            page = graphql(LIST_ITEMS, id=self.id, after=cursor)["node"]["items"]
            for node in page["nodes"]:
                content = node.get("content") or {}
                if "number" not in content:
                    continue  # draft notes, not issues
                status = next((value["name"] for value in node["fieldValues"]["nodes"]
                               if value and value.get("field", {}).get("id") == status_field_id), None)
                items[(content["repository"]["nameWithOwner"], content["number"])] = (node["id"], status)

            if not page["pageInfo"]["hasNextPage"]:
                return items
            cursor = page["pageInfo"]["endCursor"]

    def add(self, content_id: str) -> str:
        try:
            return graphql(ADD_ITEM, project=self.id, content=content_id)["addProjectV2ItemById"]["item"]["id"]
        except RuntimeError as error:
            # The board's auto-add workflow may have added it a moment ago.
            if "already exists" not in str(error):
                raise

        nodes = graphql(FIND_ITEM, content=content_id)["node"]["projectItems"]["nodes"]
        return next(node["id"] for node in nodes if node["project"]["id"] == self.id)

    def set(self, item_id: str, key: str, option: str) -> None:
        field_id, options = self.fields[key]
        if option not in options:
            raise SystemExit(f"Field {key!r} has no option {option!r} (has: {', '.join(options)})")
        graphql(SET_FIELD, project=self.id, item=item_id, field=field_id, option=options[option])


def epic_issues(repo: str, epic: int, board: Board) -> list[Issue]:
    issues, page = [], 1
    while True:
        batch = gh(f"repos/{repo}/issues/{epic}/sub_issues?per_page=100&page={page}")
        for issue in batch:
            _, status = board.items.get((repo, issue["number"]), (None, None))
            issues.append(Issue(issue["number"], issue["title"], issue["state"] == "open", status))
        if len(batch) < 100:
            return issues
        page += 1


def set_state(repo: str, number: int, state: str) -> None:
    # Setting a state rather than "closing" means no error if a board rule already closed it.
    payload = {"state": state}
    if state == "closed":
        payload["state_reason"] = "completed"
    gh(f"repos/{repo}/issues/{number}", "-X", "PATCH", payload=payload)


def apply(plan: Plan, repo: str, epic: int, board: Board, source: dict, defaults: dict) -> None:
    def fill_fields(item_id: str) -> None:
        board.set(item_id, "context", source["context"])
        board.set(item_id, "priority", source.get("priority", defaults["priority"]))
        board.set(item_id, "effort", source.get("effort", defaults["effort"]))

    for action in plan.actions:
        if action.kind == "create":
            body = f"{action.body}\n\n_Synced from `{source['status_doc']}`._"
            issue = gh(f"repos/{repo}/issues", "-X", "POST", payload={"title": action.title, "body": body})
            action.number = issue["number"]
            gh(f"repos/{repo}/issues/{epic}/sub_issues", "-X", "POST", payload={"sub_issue_id": issue["id"]})

            item_id = board.add(issue["node_id"])
            board.set(item_id, "status", action.to)
            fill_fields(item_id)
            if action.to == DONE:
                set_state(repo, action.number, "closed")

        elif action.kind == "add":
            node_id = gh(f"repos/{repo}/issues/{action.number}")["node_id"]
            item_id = board.add(node_id)
            board.items[(repo, action.number)] = (item_id, None)
            fill_fields(item_id)

        elif action.kind == "status":
            item_id, _ = board.items[(repo, action.number)]
            board.set(item_id, "status", action.to)

        elif action.kind == "close":
            set_state(repo, action.number, "closed")

        elif action.kind == "reopen":
            set_state(repo, action.number, "open")

        print(action)


# --- Command line ---

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync a GitHub Projects board with repo status docs.")
    parser.add_argument("-c", "--config", default="sources.json")
    parser.add_argument("-s", "--source", action="append", help="only sync this source (can repeat)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="show the changes, don't make them")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    board_config = config["board"]
    repo = board_config["issues_repo"]
    defaults = config.get("defaults", {"priority": "Med", "effort": "M"})
    board = Board(board_config["owner"], board_config["project_number"], board_config["fields"])

    for source in config["sources"]:
        if args.source and source["name"] not in args.source:
            continue
        if not source.get("active", True):
            print(f"== {source['name']}: paused, skipped")
            continue

        doc = (config_path.parent / source["status_doc"]).expanduser()
        plan = plan_source(
            parse_status_doc(doc.read_text()),
            epic_issues(repo, source["epic_issue"], board),
            source.get("title_prefix", ""),
        )

        count = len(plan.actions)
        summary = "no changes" if count == 0 else f"{count} change" + ("s" if count > 1 else "")
        if args.dry_run and count:
            summary += " (dry run)"
        print(f"== {source['name']} (epic #{source['epic_issue']}): {summary}")

        if args.dry_run:
            for action in plan.actions:
                print(action)
        else:
            apply(plan, repo, source["epic_issue"], board, source, defaults)

        for issue in plan.vanished:
            print(f"  ? #{issue.number:>4}  no longer in the doc, left as is: {issue.title}")
        for title in plan.duplicates:
            print(f"  ! listed twice in the doc, ignored the second: {title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
