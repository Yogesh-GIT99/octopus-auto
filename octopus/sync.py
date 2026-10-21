"""Reconcile a GitHub Projects v2 board with status docs kept in project repos.

Each tracked source has a markdown status doc with three sections:
    ## ✅ Done      -> Status "Done" (issue closed)
    ## 🔄 Ongoing   -> "In Progress", or "Blocked" / "Todo" depending on wording
    ## 📋 Upcoming  -> "Backlog"
and one bullet per work item:  - **Item title** — optional description

The board is derived from those docs. Syncs are idempotent: an unchanged doc
produces no writes, and a run interrupted halfway can simply be re-run.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DONE, IN_PROGRESS, TODO, BLOCKED, BACKLOG = "Done", "In Progress", "Todo", "Blocked", "Backlog"

# ---------------------------------------------------------------- parsing

SECTION_KEYWORDS = [  # checked in order; first match wins
    ("done", re.compile(r"\bdone\b", re.I)),
    ("ongoing", re.compile(r"\b(ongoing|in progress)\b", re.I)),
    ("upcoming", re.compile(r"\b(upcoming|backlog|next up|planned)\b", re.I)),
]
HEADING = re.compile(r"^(#{2,3})\s+(.*)$")
ITEM = re.compile(r"^[-*]\s+(~~)?\*\*(.+?)\*\*(?:~~)?\s*(?:[—–:-]+\s*(.*))?$")
BLOCKED_CUES = re.compile(r"\b(blocked (on|by)|waiting (for|on)|stuck on)\b", re.I)
TODO_CUES = re.compile(r"^(next:|need to\b|todo\b)", re.I)


@dataclass
class Item:
    title: str
    description: str
    section: str  # done | ongoing | upcoming

    @property
    def target_status(self) -> str:
        if self.section == "done":
            return DONE
        if self.section == "upcoming":
            return BACKLOG
        if BLOCKED_CUES.search(self.description):
            return BLOCKED
        if TODO_CUES.search(self.description.strip()):
            return TODO
        return IN_PROGRESS


def parse_status_doc(text: str) -> list[Item]:
    """Return the top-level bold bullets under the Done / Ongoing / Upcoming headings."""
    items: list[Item] = []
    section = None
    for line in text.splitlines():
        h = HEADING.match(line)
        if h:
            level, heading = len(h.group(1)), h.group(2)
            found = next((name for name, rx in SECTION_KEYWORDS if rx.search(heading)), None)
            if found:
                section = found
            elif level == 2:  # an unrelated top-level section (e.g. "## Notes") ends tracking
                section = None
            continue
        if section is None or line[:1] in (" ", "\t"):  # nested bullets are detail, not items
            continue
        m = ITEM.match(line.rstrip())
        if m:
            struck, title, desc = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
            # a struck-through item ("~~**x**~~ — already gone") is finished wherever it sits
            items.append(Item(title, desc, "done" if struck else section))
    return items


def normalize(title: str) -> str:
    """Matching key: drop leading [tags], case, punctuation and extra spaces."""
    title = re.sub(r"^(\s*\[[^\]]*\]\s*)+", "", title)
    return " ".join(re.sub(r"[^0-9a-z]+", " ", title.lower()).split())


# ---------------------------------------------------------------- planning

@dataclass
class Issue:
    number: int
    title: str
    open: bool
    status: str | None  # current board Status, None if the issue is not on the board


@dataclass
class Action:
    kind: str  # create | add | status | close | reopen
    title: str
    number: int | None = None
    to: str | None = None
    frm: str | None = None
    body: str = ""

    def __str__(self) -> str:
        ref = f"#{self.number}" if self.number else "new"
        if self.kind == "status":
            return f"  ~ {ref:>5}  {self.frm or '(none)'} -> {self.to}   {self.title}"
        mark = {"create": "+", "add": "+", "close": "x", "reopen": "o"}[self.kind]
        extra = f" [{self.to}]" if self.kind == "create" else ""
        return f"  {mark} {ref:>5}  {self.kind}{extra}   {self.title}"


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    vanished: list[Issue] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


def plan_source(items: list[Item], issues: list[Issue], prefix: str = "") -> Plan:
    """Pure function: what has to change so the board matches the doc."""
    plan = Plan()
    by_key = {normalize(i.title): i for i in issues}
    seen: set[str] = set()
    for item in items:
        key = normalize(item.title)
        if key in seen:
            plan.duplicates.append(item.title)
            continue
        seen.add(key)
        target = item.target_status
        issue = by_key.get(key)
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
    # items that left the doc are reported, never deleted or moved
    plan.vanished = [i for i in issues if normalize(i.title) not in seen]
    return plan


# ---------------------------------------------------------------- GitHub I/O

def gh(*args: str, payload: dict | None = None):
    proc = subprocess.run(["gh", "api", *args] + (["--input", "-"] if payload is not None else []),
                          input=json.dumps(payload) if payload is not None else None,
                          capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"gh api {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def graphql(query: str, **variables):
    res = gh("graphql", payload={"query": query, "variables": variables})
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    return res["data"]


class Board:
    """A Projects v2 board; field and option IDs are resolved by name at runtime."""

    def __init__(self, owner: str, number: int, fields: dict[str, str]):
        q = """query($login:String!,$n:Int!){ %s(login:$login){ projectV2(number:$n){ id
                 fields(first:50){ nodes{ ... on ProjectV2SingleSelectField{ id name options{ id name } } } } } } }"""
        project = None
        for kind in ("user", "organization"):
            try:
                project = graphql(q % kind, login=owner, n=number)[kind]["projectV2"]
                break
            except (RuntimeError, TypeError):
                continue
        if not project:
            raise SystemExit(f"Project {owner}#{number} not found")
        self.id = project["id"]
        by_name = {f["name"]: f for f in project["fields"]["nodes"] if f}
        self.fields = {}
        for key, name in fields.items():
            if name not in by_name:
                raise SystemExit(f"Board has no single-select field named {name!r}")
            f = by_name[name]
            self.fields[key] = (f["id"], {o["name"]: o["id"] for o in f["options"]})
        self.items = self._load_items()

    def _load_items(self) -> dict[tuple[str, int], tuple[str, str | None]]:
        """(repo, issue number) -> (project item id, current Status)."""
        status_field = self.fields["status"][0]
        q = """query($id:ID!,$after:String){ node(id:$id){ ... on ProjectV2{ items(first:100, after:$after){
                 pageInfo{ hasNextPage endCursor }
                 nodes{ id content{ ... on Issue{ number repository{ nameWithOwner } } }
                        fieldValues(first:20){ nodes{ ... on ProjectV2ItemFieldSingleSelectValue{
                            name field{ ... on ProjectV2SingleSelectField{ id } } } } } } } } } }"""
        out, after = {}, None
        while True:  # paginate: the default page silently truncates large boards
            page = graphql(q, id=self.id, after=after)["node"]["items"]
            for node in page["nodes"]:
                c = node.get("content") or {}
                if "number" not in c:
                    continue
                status = next((v["name"] for v in node["fieldValues"]["nodes"]
                               if v and v.get("field", {}).get("id") == status_field), None)
                out[(c["repository"]["nameWithOwner"], c["number"])] = (node["id"], status)
            if not page["pageInfo"]["hasNextPage"]:
                return out
            after = page["pageInfo"]["endCursor"]

    def add(self, content_id: str) -> str:
        try:
            return graphql("""mutation($p:ID!,$c:ID!){ addProjectV2ItemById(input:{projectId:$p, contentId:$c}){ item{ id } } }""",
                           p=self.id, c=content_id)["addProjectV2ItemById"]["item"]["id"]
        except RuntimeError as e:
            # a board auto-add workflow can add a new issue between our create and add
            if "already exists" not in str(e):
                raise
        items = graphql("""query($c:ID!){ node(id:$c){ ... on Issue{ projectItems(first:50){ nodes{ id project{ id } } } } } }""",
                        c=content_id)["node"]["projectItems"]["nodes"]
        return next(i["id"] for i in items if i["project"]["id"] == self.id)

    def set(self, item_id: str, key: str, option: str) -> None:
        field_id, options = self.fields[key]
        if option not in options:
            raise SystemExit(f"Field {key!r} has no option {option!r} (has: {', '.join(options)})")
        graphql("""mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue(
                     input:{projectId:$p, itemId:$i, fieldId:$f, value:{singleSelectOptionId:$o}}){ clientMutationId } }""",
                p=self.id, i=item_id, f=field_id, o=options[option])


def epic_issues(repo: str, epic: int, board: Board) -> list[Issue]:
    issues, page = [], 1
    while True:
        batch = gh(f"repos/{repo}/issues/{epic}/sub_issues?per_page=100&page={page}")
        for i in batch:
            _, status = board.items.get((repo, i["number"]), (None, None))
            issues.append(Issue(i["number"], i["title"], i["state"] == "open", status))
        if len(batch) < 100:
            return issues
        page += 1


def apply(plan: Plan, repo: str, epic: int, board: Board, source: dict, defaults: dict) -> None:
    for a in plan.actions:
        if a.kind == "create":
            issue = gh(f"repos/{repo}/issues", "-X", "POST",
                       payload={"title": a.title, "body": a.body + f"\n\n_Synced from `{source['status_doc']}`._"})
            a.number = issue["number"]
            gh(f"repos/{repo}/issues/{epic}/sub_issues", "-X", "POST", payload={"sub_issue_id": issue["id"]})
            item = board.add(issue["node_id"])
            board.set(item, "status", a.to)
            board.set(item, "context", source["context"])
            board.set(item, "priority", source.get("priority", defaults["priority"]))
            board.set(item, "effort", source.get("effort", defaults["effort"]))
            if a.to == DONE:
                gh(f"repos/{repo}/issues/{a.number}", "-X", "PATCH", payload={"state": "closed", "state_reason": "completed"})
        elif a.kind == "add":
            node = gh(f"repos/{repo}/issues/{a.number}")["node_id"]
            item = board.add(node)
            board.items[(repo, a.number)] = (item, None)
            board.set(item, "context", source["context"])
            board.set(item, "priority", source.get("priority", defaults["priority"]))
            board.set(item, "effort", source.get("effort", defaults["effort"]))
        elif a.kind == "status":
            board.set(board.items[(repo, a.number)][0], "status", a.to)
        elif a.kind in ("close", "reopen"):
            # PATCH to a state is idempotent, so a board workflow that already
            # auto-closed the issue on "Done" doesn't make this fail
            state = {"close": {"state": "closed", "state_reason": "completed"}, "reopen": {"state": "open"}}[a.kind]
            gh(f"repos/{repo}/issues/{a.number}", "-X", "PATCH", payload=state)
        print(a)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--config", default="sources.json")
    ap.add_argument("-s", "--source", action="append", help="only sync this source (repeatable)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args(argv)

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text())
    b = cfg["board"]
    board = Board(b["owner"], b["project_number"], b["fields"])
    defaults = cfg.get("defaults", {"priority": "Med", "effort": "M"})

    for src in cfg["sources"]:
        if args.source and src["name"] not in args.source:
            continue
        if not src.get("active", True):
            print(f"== {src['name']}: paused, skipped")
            continue
        doc = (cfg_path.parent / src["status_doc"]).expanduser()
        plan = plan_source(parse_status_doc(doc.read_text()),
                           epic_issues(b["issues_repo"], src["epic_issue"], board),
                           src.get("title_prefix", ""))
        print(f"== {src['name']} (epic #{src['epic_issue']}): "
              f"{len(plan.actions) or 'no'} change{'s' if len(plan.actions) != 1 else ''}"
              + (" (dry run)" if args.dry_run and plan.actions else ""))
        if args.dry_run:
            for a in plan.actions:
                print(a)
        else:
            apply(plan, b["issues_repo"], src["epic_issue"], board, src, defaults)
        for i in plan.vanished:
            print(f"  ? #{i.number:>4}  no longer in the doc, left as is: {i.title}")
        for t in plan.duplicates:
            print(f"  ! duplicate item in doc, ignored: {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
