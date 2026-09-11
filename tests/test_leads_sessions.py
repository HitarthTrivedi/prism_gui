"""The Leads sessions store (addons.leads.sessions).

Every Leads & Outreach run is saved as a session, so it survives a restart and
the next run can skip the people an earlier one already pulled. What that rests
on, pinned against temp folders only:

  · a run reopens as the same OBJECT GRAPH — dossier.lead is an element of
    all_leads, draft.dossier an element of dossiers — because the cockpit keys
    drafts by id(dossier), and equal copies would detach every draft;
  · nothing but whitelisted run parameters reaches disk (cfg carries API keys);
  · the list is newest first, and a re-save keeps when the run began;
  · "pulled" is everyone for a search, only the qualified for a sheet;
  · a damaged or missing index is rebuilt from the session files; a damaged
    session fails alone, and loudly, and never empties the list;
  · one value UTF-8 cannot write (half an emoji) never costs a whole run;
  · writes are atomic: no temp file is ever left, and a failed replace keeps
    the previous file byte for byte.

No network. Qt is imported by one test only, to read a reopened draft through
the cockpit's own status_of.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.leads import sessions as S                          # noqa: E402
from prospector.identity import SeenIndex, keys_of              # noqa: E402
from prospector.models import Dimension, Dossier, Lead          # noqa: E402
from prospector.models import Signal as LeadSignal              # noqa: E402
from prospector.reach import Draft                              # noqa: E402

_APP = None     # the QApplication the cockpit test creates, kept alive


def _graph():
    """A realistic run: three sourced people, two qualified, one mailed."""
    kunyi = Lead(name="Kunyi Mehta", title="Head of Automation",
                 company="Acme Pvt. Ltd.", email="kunyi@acme.in",
                 phone="+91 98765 43210", industry="Pharma", fit_score=96.5,
                 fit_reason="runs automation at a pharma plant")
    kunyi.extra = {"email_check": "valid", "other_emails": ["k.mehta@acme.in"],
                   "linkedin": "https://www.linkedin.com/in/Kunyi-Mehta/",
                   "location": "Vadodara"}
    vaibhav = Lead(name="Vaibhav Rao", title="Plant Head", company="Borosil",
                   email="vaibhav@borosil.com", fit_score=81.0,
                   drops=["email_unsendable"])
    nomail = Lead(name="Nomail Shah", title="COO", company="Chem Co",
                  fit_score=40.0)
    hot = Dossier(
        lead=kunyi, verdict="hot", score=88,
        dimensions=[Dimension("Fit", "pass", "runs three plants", "acme.in/about"),
                    Dimension("Timing", "unknown")],
        opener="Saw Acme is opening the Dahej line.",
        signals=[LeadSignal(title="Acme opens Dahej line",
                            snippet="A new sterile-fill line…",
                            url="https://news.example/acme-dahej",
                            published="2026-08-30", source="news.example")],
        summary="Strong fit with a dated trigger.",
        generated_at="2026-09-10T08:15:00+00:00", status="ok",
        confidence=0.75, signal_status="found")
    warm = Dossier(lead=vaibhav, verdict="warm", score=61,
                   generated_at="2026-09-10T08:16:30+00:00",
                   note="no why-now signal", confidence=0.2,
                   signal_status="none")
    sent = Draft(dossier=hot, subject="The Dahej line",
                 body="Hi Kunyi,\n\nSaw the Dahej line…", status="sent")
    draft = Draft(dossier=warm, subject="Borosil — a quick idea",
                  body="Hi Vaibhav,", status="draft",
                  note="⚠ unverified figure(s): 15%")
    return [kunyi, vaibhav, nomail], [hot, warm], [sent, draft]


ICP = {"mode": "icp", "industries": ["Pharma", "Chemicals", "Glass"],
       "roles": ["Head of Automation"], "location": "India", "target": 300,
       "offer": "Line automation retrofits", "limit": 25, "verify_limit": 25,
       "claims_path": "", "include_earlier": False}


def _save(folder, session_id, mode="icp", params=None, graph=None, **kw):
    leads, dossiers, drafts = graph or _graph()
    return S.save(folder, session_id, mode=mode,
                  params=ICP if params is None else params,
                  all_leads=leads, dossiers=dossiers, drafts=drafts, **kw)


class _Folder(unittest.TestCase):
    """A temp parent, and a sessions folder inside it that does not exist yet
    — save() must create it, and nothing else may."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self._tmp.name, "Leads sessions")

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, name):
        return os.path.join(self.folder, name)

    def _read(self, name):
        with open(self._path(name), encoding="utf-8") as f:
            return json.load(f)

    def _bytes(self, name):
        with open(self._path(name), "rb") as f:
            return f.read()

    def _write(self, name, text):
        with open(self._path(name), "w", encoding="utf-8") as f:
            f.write(text)

    def _temps(self):
        return [n for n in os.listdir(self.folder) if n.endswith(".tmp")]

    def _ids(self):
        return [h["id"] for h in S.list_sessions(self.folder)]


# ── the graph ─────────────────────────────────────────────────────────────────

class TheGraphComesBack(_Folder):

    def setUp(self):
        super().setUp()
        self.leads, self.dossiers, self.drafts = _graph()
        _save(self.folder, "s1", graph=(self.leads, self.dossiers, self.drafts),
              total_in_sheet=412, signal_source="exa", skipped_seen=7)
        self.out = S.load(self.folder, "s1")

    def test_the_links_are_identities_not_copies(self):
        leads, dossiers, drafts = (self.out["all_leads"], self.out["dossiers"],
                                   self.out["drafts"])
        self.assertEqual((len(leads), len(dossiers), len(drafts)), (3, 2, 2))
        self.assertIs(dossiers[0].lead, leads[0])
        self.assertIs(dossiers[1].lead, leads[1])
        self.assertIs(drafts[0].dossier, dossiers[0])
        self.assertIs(drafts[1].dossier, dossiers[1])

    def test_every_field_survives(self):
        for before, after in zip(self.leads, self.out["all_leads"]):
            self.assertEqual(dataclasses.asdict(after), dataclasses.asdict(before))
        # asdict recurses, so this covers the lead, dimensions, signals,
        # generated_at, confidence, signal_status, note and status at once.
        for before, after in zip(self.dossiers, self.out["dossiers"]):
            self.assertEqual(dataclasses.asdict(after), dataclasses.asdict(before))
        for before, after in zip(self.drafts, self.out["drafts"]):
            for name in ("subject", "body", "status", "error", "note"):
                self.assertEqual(getattr(after, name), getattr(before, name), name)
        hot = self.out["dossiers"][0]
        self.assertEqual(hot.generated_at, "2026-09-10T08:15:00+00:00")
        self.assertIsInstance(hot.dimensions[0], Dimension)
        self.assertIsInstance(hot.signals[0], LeadSignal)
        self.assertEqual(hot.lead.extra["other_emails"], ["k.mehta@acme.in"])
        self.assertEqual((self.out["total_in_sheet"], self.out["signal_source"],
                          self.out["skipped_seen"]), (412, "exa", 7))

    def test_a_sent_draft_still_reads_mailed_in_the_cockpit(self):
        global _APP
        from PySide6.QtWidgets import QApplication
        _APP = QApplication.instance() or QApplication(sys.argv)
        from addons.leads import cockpit

        dossiers, drafts = self.out["dossiers"], self.out["drafts"]
        draft_by = {id(d.dossier): d for d in drafts}     # how the cockpit keys them
        self.assertEqual(
            cockpit.status_of(dossiers[0], draft_by.get(id(dossiers[0]))), "Mailed")
        self.assertEqual(
            cockpit.status_of(dossiers[1], draft_by.get(id(dossiers[1]))), "Guessed")


class WhatGoesIntoTheFile(_Folder):

    def test_a_dossier_brings_its_lead_when_all_leads_lacks_it(self):
        leads, dossiers, drafts = _graph()
        header = _save(self.folder, "s1", graph=([leads[0]], dossiers, drafts))
        out = S.load(self.folder, "s1")
        self.assertEqual([lead.name for lead in out["all_leads"]],
                         ["Kunyi Mehta", "Vaibhav Rao"])
        self.assertIs(out["dossiers"][1].lead, out["all_leads"][1])
        self.assertEqual(header["counts"]["leads"], 2)

    def test_a_draft_whose_dossier_is_not_saved_is_left_out(self):
        leads, dossiers, drafts = _graph()
        stray = Draft(dossier=Dossier(lead=leads[2]), subject="nobody's")
        header = _save(self.folder, "s1", graph=(leads, dossiers, drafts + [stray]))
        self.assertEqual(header["counts"]["drafted"], 2)
        self.assertEqual([d.subject for d in S.load(self.folder, "s1")["drafts"]],
                         ["The Dahej line", "Borosil — a quick idea"])

    def test_extra_values_json_cannot_hold_are_kept_as_text(self):
        leads, dossiers, drafts = _graph()
        when = datetime(2026, 9, 1, 10, 30)
        leads[2].extra = {"imported_at": when, "tags": ("a",), "row": 12}
        _save(self.folder, "s1", graph=(leads, dossiers, drafts))
        self.assertEqual(S.load(self.folder, "s1")["all_leads"][2].extra,
                         {"imported_at": str(when), "tags": ["a"], "row": 12})

    def test_half_an_emoji_does_not_cost_the_run(self):
        """Web text can arrive holding one half of a surrogate pair (a source
        cut it mid-emoji). UTF-8 cannot write that half, and losing a whole
        run — and who it pulled — over one snippet is the worse outcome."""
        leads, dossiers, drafts = _graph()
        leads[2].name = "Nomail \ud83d Shah"
        dossiers[0].signals[0].snippet = "A new sterile-fill line \ud83d"
        # Both halves present, just as two code points: that is still one emoji.
        dossiers[1].summary = "Warm \ud83d\udfe1 and a whole one \U0001F525"
        header = _save(self.folder, "s1", graph=(leads, dossiers, drafts),
                       signal_source="exa \udc80")
        self.assertEqual(self._temps(), [])
        out = S.load(self.folder, "s1")
        self.assertEqual(out["all_leads"][2].name, "Nomail \ufffd Shah")
        self.assertEqual(out["dossiers"][0].signals[0].snippet,
                         "A new sterile-fill line \ufffd")
        self.assertEqual(out["dossiers"][1].summary,
                         "Warm \U0001F7E1 and a whole one \U0001F525")
        self.assertEqual(out["signal_source"], "exa \ufffd")
        self.assertEqual(S.list_sessions(self.folder), [header])
        self.assertIn(leads[2], SeenIndex(S.seen_keys(self.folder)))

    def test_only_whitelisted_params_reach_disk(self):
        params = dict(ICP, mode="sheet", exa_api_key="exa-SECRET-123",
                      cfg={"api_key": "gsk_SECRET_456"})
        _save(self.folder, "s1", params=params)
        for name in ("s1.json", S.INDEX):
            self.assertNotIn(b"SECRET", self._bytes(name), name)
        out = S.load(self.folder, "s1")["params"]
        self.assertEqual(set(out), set(ICP))
        self.assertLessEqual(set(out), set(S.PARAM_KEYS))
        self.assertEqual(out["mode"], "icp")             # the mode argument wins
        self.assertEqual(out["industries"], ICP["industries"])


class AHandEditedSessionStillOpens(_Folder):

    def test_unknown_keys_missing_fields_and_malformed_rows(self):
        os.makedirs(self.folder)
        self._write("s1.json", json.dumps({
            "schema": 1, "id": "s1", "written_by": "a later build",
            "header": {"created_at": "2026-09-01T10:00:00+05:30",
                       "updated_at": "2026-09-01T10:05:00+05:30", "mode": "icp"},
            "params": {"mode": "icp", "industries": ["Pharma"],
                       "location": "India", "groq_api_key": "gsk_nope"},
            "leads": [
                "not a lead",
                {"name": "Asha Patel", "company": "Zeta", "email": "asha@zeta.in",
                 "fit_score": "72", "extra": "not a dict", "future_field": 1},
                {"name": "Ravi Iyer"},
            ],
            "dossiers": [
                {"lead": 0, "verdict": "hot"},        # its lead row was malformed
                {"lead": 1, "verdict": "warm", "score": 55.0,
                 "dimensions": ["junk", {"name": "Fit", "verdict": "pass", "weight": 3}],
                 "signals": [{"title": "Zeta expands", "url": "https://z.example",
                              "mystery": 1}]},
                {"lead": True, "verdict": "cold"},    # True == 1, but is no index
                {"lead": 9},
                "junk",
            ],
            "drafts": [
                {"dossier": 0, "subject": "orphan"},
                {"dossier": 1, "subject": "Hello Asha", "status": "sent", "opened": True},
                {"dossier": "1", "subject": "a string is no index"},
            ],
        }))
        out = S.load(self.folder, "s1")
        leads, dossiers, drafts = out["all_leads"], out["dossiers"], out["drafts"]
        self.assertEqual([lead.name for lead in leads], ["Asha Patel", "Ravi Iyer"])
        self.assertEqual((leads[0].fit_score, leads[0].extra, leads[1].email),
                         (72.0, {}, ""))
        self.assertEqual(len(dossiers), 1)
        d = dossiers[0]
        self.assertIs(d.lead, leads[0])
        self.assertEqual((d.verdict, d.score), ("warm", 55))
        self.assertEqual(d.generated_at, "")              # never re-stamped with today
        self.assertEqual([(x.name, x.verdict) for x in d.dimensions], [("Fit", "pass")])
        self.assertEqual([s.title for s in d.signals], ["Zeta expands"])
        self.assertEqual(len(drafts), 1)
        self.assertIs(drafts[0].dossier, d)
        self.assertEqual((drafts[0].subject, drafts[0].status), ("Hello Asha", "sent"))
        self.assertEqual(out["params"],
                         {"mode": "icp", "industries": ["Pharma"], "location": "India"})
        self.assertEqual(out["header"]["created_at"], "2026-09-01T10:00:00+05:30")
        self.assertEqual(out["header"]["label"], "1 industry · India")
        self.assertEqual(out["header"]["counts"],
                         {"leads": 2, "qualified": 1, "hot": 0, "warm": 1,
                          "drafted": 1, "sent": 1})
        self.assertEqual((out["total_in_sheet"], out["signal_source"],
                          out["skipped_seen"]), (0, "", 0))


# ── the list ──────────────────────────────────────────────────────────────────

class TheList(_Folder):

    def test_the_header_is_small_and_counted_off_the_run(self):
        header = _save(self.folder, "s1")
        self.assertEqual(set(header), {"id", "created_at", "updated_at", "mode",
                                       "label", "skipped_seen", "counts"})
        self.assertEqual(header["counts"], {"leads": 3, "qualified": 2, "hot": 1,
                                            "warm": 1, "drafted": 2, "sent": 1})
        self.assertEqual((header["id"], header["mode"], header["label"]),
                         ("s1", "icp", "3 industries · India"))
        self.assertEqual(S.list_sessions(self.folder), [header])
        self.assertEqual(S.load(self.folder, "s1")["header"], header)

        index = self._read(S.INDEX)
        self.assertEqual(index["schema"], S.SCHEMA)
        entry = index["sessions"][0]
        leads, dossiers, _ = _graph()
        self.assertEqual(entry["pulled"], sorted(S.pulled_keys("icp", leads, dossiers)))
        self.assertEqual({k: v for k, v in entry.items() if k != "pulled"}, header)

    def test_labels(self):
        cases = [
            ("sheet", {"sheet_path": "C:\\Users\\owner\\Leads\\client export.xlsx"},
             "client export.xlsx"),
            ("sheet", {"sheet_path": "/home/owner/leads.csv"}, "leads.csv"),
            ("sheet", {}, "Sheet"),
            ("icp", {"industries": ["Pharma", " ", "Glass"], "location": "Gujarat"},
             "2 industries · Gujarat"),
            ("icp_leads_only", {"industries": "Pharma\n\nChemicals\nGlass\n",
                                "location": "India"}, "3 industries · India"),
            ("icp", {"industries": ["Pharma"], "location": "India"}, "1 industry · India"),
            ("icp", {"industries": ["Pharma", "Glass"]}, "2 industries"),
        ]
        for i, (mode, params, label) in enumerate(cases):
            with self.subTest(label=label):
                header = _save(self.folder, f"s{i}", mode=mode, params=params)
                self.assertEqual(header["label"], label)

    def test_a_filtered_search_is_labelled_from_its_filters(self):
        # The legacy "location" line says "Anywhere except India" too, but the
        # label must come from the facets: the old text box read "Global except
        # india" as a place to search IN.
        filters = {"industries": {"include": [f"Industry {i}" for i in range(10)]},
                   "locations": {"exclude": ["India"]}}
        cases = [
            ("icp", dict(ICP, filters=filters, location="Global except india"),
             "10 industries · Anywhere except India"),
            ("icp_leads_only", {"filters": {"industries": {"include": ["Pharma"]},
                                            "locations": {"include": ["UAE", "Qatar"]}}},
             "1 industry · UAE, Qatar"),
            ("icp", {"filters": {"locations": {"exclude": ["India"]}},
                     "industries": ["Pharma", "Glass"]},
             "Anywhere except India"),
        ]
        for i, (mode, params, label) in enumerate(cases):
            with self.subTest(label=label):
                self.assertEqual(_save(self.folder, f"f{i}", mode=mode,
                                       params=params)["label"], label)

    def test_filters_survive_save_and_load(self):
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({
            "job_titles": {"include": ["Plant Head", "Head of Manufacturing"],
                           "exclude": ["Intern"]},
            "seniority": {"include": ["head", "director"]},
            "locations": {"exclude": ["India"]},
            "headcount": ["51-200", "201-500"], "similar_titles": False})
        raw = dict(spec.to_dict(), exa_api_key="exa-SECRET-1")
        _save(self.folder, "s1", params=dict(ICP, filters=raw))
        self.assertNotIn(b"SECRET", self._bytes("s1.json"))
        out = S.load(self.folder, "s1")["params"]
        self.assertEqual(out["filters"], spec.to_dict())
        self.assertEqual(SearchSpec.from_params(out), spec)

    def test_newest_first_and_latest(self):
        self.assertIsNone(S.latest(self.folder))
        _save(self.folder, "early", created_at="2026-09-01T10:00:00+05:30")
        _save(self.folder, "late", created_at="2026-09-03T10:00:00+05:30")
        _save(self.folder, "middle", created_at="2026-09-02T10:00:00+05:30")
        self.assertEqual(self._ids(), ["late", "middle", "early"])
        self.assertEqual(S.latest(self.folder)["id"], "late")
        self.assertEqual([e["id"] for e in self._read(S.INDEX)["sessions"]],
                         ["late", "middle", "early"])

    def test_a_folder_that_does_not_exist_lists_nothing_and_is_not_created(self):
        self.assertEqual(S.list_sessions(self.folder), [])
        self.assertIsNone(S.latest(self.folder))
        self.assertEqual(S.seen_keys(self.folder), frozenset())
        self.assertFalse(os.path.exists(self.folder))

    def test_a_resave_keeps_when_the_run_began(self):
        leads, dossiers, drafts = _graph()
        with mock.patch.object(S, "_now", return_value="2026-09-11T09:00:00+05:30"):
            first = _save(self.folder, "s1", graph=(leads, dossiers, drafts))
        drafts[1].status = "sent"
        with mock.patch.object(S, "_now", return_value="2026-09-11T11:30:00+05:30"):
            second = _save(self.folder, "s1", graph=(leads, dossiers, drafts))
        self.assertEqual(second["created_at"], "2026-09-11T09:00:00+05:30")
        self.assertEqual(second["updated_at"], "2026-09-11T11:30:00+05:30")
        self.assertEqual((first["counts"]["sent"], second["counts"]["sent"]), (1, 2))
        self.assertEqual(S.list_sessions(self.folder), [second])
        self.assertEqual(S.load(self.folder, "s1")["header"], second)

    def test_a_resave_keeps_when_the_run_began_even_if_the_index_was_lost(self):
        with mock.patch.object(S, "_now", return_value="2026-09-11T09:00:00+05:30"):
            _save(self.folder, "s1")
        os.remove(self._path(S.INDEX))
        with mock.patch.object(S, "_now", return_value="2026-09-12T09:00:00+05:30"):
            again = _save(self.folder, "s1")
        self.assertEqual(again["created_at"], "2026-09-11T09:00:00+05:30")

    def test_new_ids_read_as_time_and_do_not_collide(self):
        ids = {S.new_id() for _ in range(20)}
        self.assertEqual(len(ids), 20)
        for session_id in ids:
            self.assertRegex(session_id, r"^\d{8}-\d{6}-[0-9a-f]{6}$")
        header = _save(self.folder, next(iter(ids)))
        self.assertIn(header["id"], ids)


# ── who was pulled ────────────────────────────────────────────────────────────

class WhoWasPulled(_Folder):

    def test_a_search_marks_everyone_it_sourced(self):
        _save(self.folder, "s1", mode="icp")
        seen = SeenIndex(S.seen_keys(self.folder))
        self.assertIn(Lead(email="KUNYI@acme.in"), seen)                  # address
        self.assertIn(Lead(extra={"linkedin": "linkedin.com/in/kunyi-mehta"}), seen)
        self.assertIn(Lead(name="nomail shah", company="Chem Co Ltd"), seen)
        self.assertNotIn(Lead(name="Someone Else", company="Acme",
                              email="else@acme.in"), seen)

    def test_leads_only_marks_everyone_with_no_dossiers(self):
        leads, _, _ = _graph()
        _save(self.folder, "s1", mode="icp_leads_only", graph=(leads, [], []))
        seen = SeenIndex(S.seen_keys(self.folder))
        for lead in leads:
            self.assertIn(lead, seen)

    def test_a_sheet_marks_only_the_people_it_qualified(self):
        leads, dossiers, drafts = _graph()
        _save(self.folder, "s1", mode="sheet", params={"sheet_path": "client.xlsx"},
              graph=(leads, dossiers, drafts))
        seen = SeenIndex(S.seen_keys(self.folder))
        self.assertIn(leads[0], seen)
        self.assertIn(leads[1], seen)
        self.assertNotIn(leads[2], seen)   # on the sheet, never qualified: next run's
        self.assertEqual(S.pulled_keys("sheet", leads, dossiers),
                         keys_of(leads[0]) | keys_of(leads[1]))

    def test_exclude_id_leaves_one_session_out(self):
        leads, dossiers, drafts = _graph()
        _save(self.folder, "search", mode="icp", graph=([leads[2]], [], []))
        _save(self.folder, "sheet", mode="sheet", params={},
              graph=(leads[:2], dossiers[:1], drafts[:1]))
        both = SeenIndex(S.seen_keys(self.folder))
        self.assertIn(leads[2], both)
        self.assertIn(leads[0], both)
        without = SeenIndex(S.seen_keys(self.folder, exclude_id="search"))
        self.assertNotIn(leads[2], without)
        self.assertIn(leads[0], without)
        self.assertNotIn(leads[1], without)


# ── a damaged store ───────────────────────────────────────────────────────────

class ADamagedStore(_Folder):

    def setUp(self):
        super().setUp()
        _save(self.folder, "older", created_at="2026-09-01T10:00:00+05:30")
        self.other = Lead(name="Ravi Iyer", company="Omega Glass",
                          email="ravi@omega.in")
        _save(self.folder, "newer", mode="icp_leads_only",
              graph=([self.other], [], []), created_at="2026-09-02T10:00:00+05:30")

    def test_a_missing_index_is_rebuilt_from_the_session_files(self):
        before = self._read(S.INDEX)
        os.remove(self._path(S.INDEX))
        self.assertEqual(self._ids(), ["newer", "older"])
        self.assertEqual(self._read(S.INDEX), before)
        self.assertIn(self.other, SeenIndex(S.seen_keys(self.folder)))

    def test_a_corrupt_index_is_rebuilt(self):
        for garbage in ("{ not json", "[]", '{"schema": 1, "sessions": "x"}',
                        '{"sessions": []}'):
            with self.subTest(index=garbage):
                self._write(S.INDEX, garbage)
                self.assertEqual(self._ids(), ["newer", "older"])
                self.assertEqual([e["id"] for e in self._read(S.INDEX)["sessions"]],
                                 ["newer", "older"])
        self._write(S.INDEX, "{ not json")
        self.assertIn(self.other, SeenIndex(S.seen_keys(self.folder)))

    def test_an_index_from_a_newer_prism_is_read_around_not_rewritten(self):
        newer = json.dumps({"schema": S.SCHEMA + 1, "sessions": [], "future": True})
        self._write(S.INDEX, newer)
        self.assertEqual(self._ids(), ["newer", "older"])
        with open(self._path(S.INDEX), encoding="utf-8") as f:
            self.assertEqual(f.read(), newer)

    def test_a_corrupt_session_fails_alone(self):
        self._write("older.json", '{"schema": 1, "leads": [')
        with self.assertRaises(S.SessionStoreError) as caught:
            S.load(self.folder, "older")
        self.assertTrue(str(caught.exception).startswith("Couldn't open this session:"))
        self.assertEqual(self._ids(), ["newer", "older"])     # the index still lists it
        self.assertEqual(len(S.load(self.folder, "newer")["all_leads"]), 1)
        os.remove(self._path(S.INDEX))
        self.assertEqual(self._ids(), ["newer"])              # a rebuild skips it

    def test_what_is_not_a_session_is_refused(self):
        cases = {"missing": None, "alist": "[1, 2]", "noleads": '{"schema": 1}',
                 "badschema": '{"schema": "1", "leads": []}',
                 "future": json.dumps({"schema": S.SCHEMA + 1, "leads": []}),
                 # a later schema may well have reshaped the run itself
                 "reshaped": json.dumps({"schema": S.SCHEMA + 1, "people": {}})}
        for session_id, text in cases.items():
            with self.subTest(session=session_id):
                if text is not None:
                    self._write(session_id + ".json", text)
                with self.assertRaises(S.SessionStoreError):
                    S.load(self.folder, session_id)
        for session_id in ("future", "reshaped"):
            with self.subTest(newer=session_id):
                with self.assertRaisesRegex(S.SessionStoreError, "newer version"):
                    S.load(self.folder, session_id)
        self.assertEqual(self._ids(), ["newer", "older"])

    def test_a_session_the_index_missed_is_adopted(self):
        real_replace = os.replace

        def index_fails(src, dst):
            if os.path.basename(dst) == S.INDEX:
                raise PermissionError(13, "Access is denied", dst)
            return real_replace(src, dst)

        with mock.patch.object(S.os, "replace", side_effect=index_fails):
            with self.assertRaises(S.SessionStoreError):
                _save(self.folder, "newest", created_at="2026-09-03T10:00:00+05:30")
        self.assertEqual(self._temps(), [])
        self.assertEqual(self._ids(), ["newest", "newer", "older"])
        self.assertEqual([e["id"] for e in self._read(S.INDEX)["sessions"]],
                         ["newest", "newer", "older"])

    def test_a_session_whose_file_is_gone_is_forgotten(self):
        os.remove(self._path("newer.json"))
        self.assertEqual(self._ids(), ["older"])
        self.assertNotIn(self.other, SeenIndex(S.seen_keys(self.folder)))

    def test_one_unreadable_session_never_empties_the_list(self):
        # A hand-edited number no float can hold is one wrong cell, read as its
        # default like any other — not an OverflowError out of load().
        self._write("huge.json", '{"schema": 1, "leads": [{"name": "Huge", '
                                 '"fit_score": 1' + "0" * 400 + "}]}")
        self.assertEqual(S.load(self.folder, "huge")["all_leads"][0].fit_score, 0.0)
        # And a failure nobody foresaw costs only its own file. The rebuild runs
        # inside list_sessions/seen_keys, whose never-raise would otherwise
        # hand back nothing at all — an empty list, and nobody skipped.
        self._write("odd.json", '{"schema": 1, "leads": []}')
        real_load = S.load

        def odd_fails(folder, session_id):
            if session_id == "odd":
                raise RuntimeError("nobody saw this coming")
            return real_load(folder, session_id)

        os.remove(self._path(S.INDEX))
        with mock.patch.object(S, "load", side_effect=odd_fails):
            self.assertEqual(sorted(self._ids()), ["huge", "newer", "older"])
            self.assertIn(self.other, SeenIndex(S.seen_keys(self.folder)))


# ── refused before anything is written ────────────────────────────────────────

class RefusedBeforeTouchingDisk(_Folder):

    def test_an_id_that_is_not_a_plain_name_is_refused(self):
        for bad in ("../escape", "..\\escape", "index", "INDEX", "", "a.b",
                    None, "x" * 101):
            with self.subTest(session_id=bad):
                with self.assertRaises(S.SessionStoreError):
                    _save(self.folder, bad)
                with self.assertRaises(S.SessionStoreError):
                    S.load(self.folder, bad)
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(S.SessionStoreError):
            _save(self.folder, "s1", mode="linkedin")
        self.assertFalse(os.path.exists(self.folder))


# ── atomic writes ─────────────────────────────────────────────────────────────

class WritesAreAtomic(_Folder):

    def test_no_temp_file_is_left_behind(self):
        for i in range(3):
            _save(self.folder, "s1")
            _save(self.folder, f"s{i + 2}", mode="sheet", params={})
        S.list_sessions(self.folder)
        self.assertEqual(self._temps(), [])
        self.assertEqual(sorted(os.listdir(self.folder)),
                         ["index.json", "s1.json", "s2.json", "s3.json", "s4.json"])

    def test_a_failed_replace_keeps_the_previous_file(self):
        leads, dossiers, drafts = _graph()
        _save(self.folder, "s1", graph=(leads, dossiers, drafts))
        session_before, index_before = self._bytes("s1.json"), self._bytes(S.INDEX)
        drafts[1].status = "sent"
        leads.append(Lead(name="Late Addition", company="Zeta"))
        with mock.patch.object(S.os, "replace",
                               side_effect=PermissionError(13, "Access is denied")):
            with self.assertRaises(S.SessionStoreError) as caught:
                _save(self.folder, "s1", graph=(leads, dossiers, drafts))
        message = str(caught.exception)
        self.assertTrue(message.startswith("Couldn't save this session:"), message)
        self.assertIn("Access is denied", message)
        self.assertEqual(self._temps(), [])
        self.assertEqual(self._bytes("s1.json"), session_before)
        self.assertEqual(self._bytes(S.INDEX), index_before)
        self.assertEqual(S.load(self.folder, "s1")["header"]["counts"]["sent"], 1)

    def test_a_folder_that_cannot_be_created_is_reported(self):
        with open(self.folder, "w", encoding="utf-8") as f:
            f.write("a file where the folder should be")
        with self.assertRaises(S.SessionStoreError):
            _save(self.folder, "s1")
        self.assertEqual(S.list_sessions(self.folder), [])
        self.assertEqual(S.seen_keys(self.folder), frozenset())


if __name__ == "__main__":
    unittest.main()
