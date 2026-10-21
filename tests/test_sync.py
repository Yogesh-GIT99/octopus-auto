import unittest

from octopus.sync import (BACKLOG, BLOCKED, DONE, IN_PROGRESS, TODO, Issue, normalize,
                          parse_status_doc, plan_source)

DOC = """# demo

> intro text with a **bold** word that is not an item

## ✅ Done
- **Bootstrap state backend** — S3 + lock table
- ~~**Retire the old server**~~ — already gone

## 🔄 Ongoing
- **Migrate service A** — working on it
  - **nested detail** — must not become an item
- **Wire DNS writer role** — blocked on access from the network team
- **Write the runbook** — Next: draft the rollback section

## 📌 Notes
- **Not an item** — notes are ignored

## 📋 Upcoming
### Backlog
- **Spot capacity for dev**
"""


class ParseTest(unittest.TestCase):
    def test_sections_and_statuses(self):
        got = {i.title: i.target_status for i in parse_status_doc(DOC)}
        self.assertEqual(got, {
            "Bootstrap state backend": DONE,
            "Retire the old server": DONE,
            "Migrate service A": IN_PROGRESS,
            "Wire DNS writer role": BLOCKED,
            "Write the runbook": TODO,
            "Spot capacity for dev": BACKLOG,
        })

    def test_normalize_ignores_tags_case_and_punctuation(self):
        self.assertEqual(normalize("[Platform] Migrate  service-A!"), normalize("migrate service a"))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.items = parse_status_doc(DOC)

    def kinds(self, plan):
        return sorted((a.kind, a.number, a.to) for a in plan.actions)

    def test_empty_board_creates_everything(self):
        plan = plan_source(self.items, [], prefix="[Demo] ")
        self.assertEqual(len(plan.actions), 6)
        self.assertTrue(all(a.kind == "create" and a.title.startswith("[Demo] ") for a in plan.actions))

    def test_in_sync_board_is_a_no_op(self):
        issues = [Issue(n, "[Demo] " + i.title, i.target_status != DONE, i.target_status)
                  for n, i in enumerate(self.items, 1)]
        plan = plan_source(self.items, issues)
        self.assertEqual(plan.actions, [])
        self.assertEqual(plan.vanished, [])

    def test_moves_closes_reopens_and_reports_vanished(self):
        issues = [
            Issue(1, "[Demo] Bootstrap state backend", True, IN_PROGRESS),  # finished -> Done + close
            Issue(2, "[Demo] Spot capacity for dev", False, DONE),           # back in backlog -> reopen
            Issue(3, "[Demo] Something we dropped", True, TODO),             # gone from doc
            Issue(4, "[Demo] Migrate service A", True, None),                # not on the board yet
        ]
        plan = plan_source(self.items, issues)
        self.assertIn(("status", 1, DONE), self.kinds(plan))
        self.assertIn(("close", 1, None), self.kinds(plan))
        self.assertIn(("status", 2, BACKLOG), self.kinds(plan))
        self.assertIn(("reopen", 2, None), self.kinds(plan))
        self.assertIn(("add", 4, None), self.kinds(plan))
        self.assertIn(("status", 4, IN_PROGRESS), self.kinds(plan))
        self.assertEqual([i.number for i in plan.vanished], [3])
        self.assertNotIn(3, [a.number for a in plan.actions])  # never touched

    def test_duplicate_items_are_reported_once(self):
        doc = "## Ongoing\n- **Same thing** — a\n- **same thing!** — b\n"
        plan = plan_source(parse_status_doc(doc), [])
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.duplicates, ["same thing!"])


if __name__ == "__main__":
    unittest.main()
