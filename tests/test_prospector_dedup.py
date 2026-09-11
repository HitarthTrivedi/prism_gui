"""Never pull the same person twice — the pipeline half.

Leads & Outreach skips anyone an earlier session already pulled. What is
pinned here is the part below the UI:

  · identity — the keys a person is known by, and that a sheet lead (e-mail,
    name, company) and a searched lead (profile, name, company) are one person;
  · source — a skipped person costs no company slot; a failed Exa call is
    counted and is never read as "no more people"; top-up rounds only ever ask
    a NEW question, stay inside their budget, and stop at target or when a
    round finds nobody;
  · engine — filter_new, and run_leads spending `limit` on new people only;
  · reach — one address twice in a batch is mailed once.

No network (Exa and SMTP are stubbed), no Qt, no real home: the suppression
file is a temp path and every Exa call goes to a recorder.
"""
from __future__ import annotations

import itertools
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import engine, identity, reach, source, triage  # noqa: E402
from prospector.identity import SeenIndex                       # noqa: E402
from prospector.models import HOT, NO_MODEL, Dossier, Lead       # noqa: E402

OFFER = "Automation and IIoT retrofits for automobile plants"


def _person(name: str, company: str, title: str = "Plant Head",
            slug: str = "") -> dict:
    """One Exa people-search result, shaped like the live API's: the profile
    link on the row, the person as an entity, and a work history whose live
    role is not the first one listed (source._current_job must pick it)."""
    slug = slug or name.lower().replace(" ", "-")
    return {"url": f"https://in.linkedin.com/in/{slug}",
            "entities": [{"type": "person", "properties": {
                "name": name, "location": "Pune, Maharashtra, India",
                "workHistory": [
                    {"title": "Engineer", "company": {"name": "Old Works"},
                     "dates": {"from": "2014-06-01", "to": "2020-12-31"}},
                    {"title": title, "company": {"name": company},
                     "dates": {"from": "2021-04-01", "to": None}},
                ]}}]}


class _Exa:
    """Stands in for source._exa_people: records every query string and
    answers with reply(query, call_number). source() calls it from a thread
    pool, so both happen under one lock and the call numbers stay honest."""

    def __init__(self, reply):
        self._reply, self._lock, self.queries = reply, threading.Lock(), []

    def __call__(self, query, api_key, n=50, timeout=60):
        with self._lock:
            self.queries.append(query)
            return self._reply(query, len(self.queries) - 1)


_FRESH = object()


# ── identity ─────────────────────────────────────────────────────────────────

class WhoALeadIs(unittest.TestCase):

    def test_an_email_is_trimmed_and_lower_cased_and_junk_is_nothing(self):
        self.assertEqual(identity.norm_email("  Jane.Doe@Acme.COM "), "jane.doe@acme.com")
        self.assertEqual(identity.norm_email("mailto:jane@acme.com"), "jane@acme.com")
        for junk in ("", "jane", "@acme.com", "jane@", "jane doe@acme.com", None):
            self.assertEqual(identity.norm_email(junk), "", junk)

    def test_one_profile_however_the_link_is_written(self):
        forms = ("https://in.linkedin.com/in/Jane-Doe/?trk=x",
                 "www.linkedin.com/in/jane-doe/",
                 "linkedin.com/in/jane-doe")
        self.assertEqual({identity.norm_profile(f) for f in forms},
                         {"linkedin.com/in/jane-doe"})

    def test_a_bare_host_identifies_nobody(self):
        for bare in ("https://www.linkedin.com/", "linkedin.com", "acme.com/"):
            self.assertEqual(identity.norm_profile(bare), "", bare)

    def test_legal_forms_fold_away_but_real_words_stay(self):
        self.assertEqual(identity.norm_company("Acme Pvt. Ltd."), "acme")
        self.assertEqual(identity.norm_company("ACME Limited"), "acme")
        self.assertEqual(identity.norm_company("Acme Industries"), "acme industries")

    def test_a_sheet_lead_and_a_searched_lead_are_one_person(self):
        """The sheet knows her by e-mail, the search by profile; the name and
        company are the only key both carry — and that is enough."""
        sheet_lead = Lead(name="Jane Doe", company="Acme Pvt. Ltd.",
                          email="jane@acme.com")
        icp_lead = Lead(name="JANE DOE", company="ACME Limited",
                        extra={"linkedin": "https://in.linkedin.com/in/jane-doe"})
        self.assertEqual(identity.keys_of(sheet_lead) & identity.keys_of(icp_lead),
                         {"n:jane doe|acme"})
        index = SeenIndex(identity.keys_of(sheet_lead))
        self.assertIn(icp_lead, index)
        self.assertNotIn(Lead(name="Jane Doe", company="Beta Motors"), index)

    def test_an_index_rebuilt_from_stored_keys_still_matches(self):
        index = SeenIndex()
        index.update(["e:jane@acme.com", "", None])
        self.assertEqual(len(index), 1)
        self.assertIn(Lead(email="JANE@acme.com"), index)
        self.assertEqual(index.keys(), {"e:jane@acme.com"})

    def test_dedupe_keeps_the_first_row(self):
        first = Lead(name="Jane Doe", company="Acme", email="jane@acme.com")
        other = Lead(name="Ravi Kumar", company="Beta Motors")
        again = Lead(name="Jane D.", company="Acme Ltd", email="Jane@Acme.com")
        kept, dropped = identity.dedupe([first, other, again])
        self.assertEqual(len(kept), 2)
        self.assertIs(kept[0], first)
        self.assertIs(kept[1], other)
        self.assertEqual(len(dropped), 1)
        self.assertIs(dropped[0], again)


# ── source: the Exa call itself ──────────────────────────────────────────────

class AFailedSearchIsNotAnEmptyOne(unittest.TestCase):
    """_exa_people must tell "Exa answered: nobody" from "the call failed"."""

    def _call(self, **post):
        with mock.patch("requests.post", **post):
            return source._exa_people("Plant Head at automobile firms", "exa-test-key")

    def test_a_raised_call_is_a_failure(self):
        self.assertIsNone(self._call(side_effect=OSError("connection reset")))

    def test_a_non_200_is_a_failure(self):
        reply = mock.Mock(status_code=402, json=lambda: {"error": "no credits"})
        self.assertIsNone(self._call(return_value=reply))

    def test_a_body_with_no_results_list_is_a_failure(self):
        reply = mock.Mock(status_code=200, json=lambda: {"error": "bad request"})
        self.assertIsNone(self._call(return_value=reply))

    def test_a_genuine_empty_answer_is_an_empty_list(self):
        reply = mock.Mock(status_code=200, json=lambda: {"results": []})
        self.assertEqual(self._call(return_value=reply), [])

    def test_rows_come_back_as_rows(self):
        row = _person("Ann Lee", "Beta Motors")
        reply = mock.Mock(status_code=200, json=lambda: {"results": [row]})
        self.assertEqual(self._call(return_value=reply), [row])


# ── source: skipping, counting and topping up ────────────────────────────────

class SourcingSkipsKnownPeople(unittest.TestCase):

    def _source(self, reply, *, industries=("automobile",), roles=("Plant Head",),
                stats=_FRESH, **kw):
        exa = _Exa(reply)
        stats = {} if stats is _FRESH else stats
        with mock.patch.object(source, "_exa_people", exa):
            leads = source.source(list(industries), list(roles), "exa-test-key",
                                  stats=stats, **kw)
        return leads, stats, exa

    def test_a_seen_person_is_skipped_and_takes_no_company_slot(self):
        rows = [_person("Jane Doe", "Acme Pvt Ltd"), _person("John Roe", "Acme Pvt Ltd"),
                _person("Ann Lee", "Beta Motors")]
        # Pulled from a sheet last time: an e-mail and a slightly different
        # spelling of the company — no profile link at all.
        earlier = Lead(name="Jane Doe", company="ACME Limited", email="jane@acme.com")
        skip = SeenIndex(identity.keys_of(earlier))

        leads, stats, _ = self._source(lambda q, i: rows, per_company=1, target=5,
                                       skip=skip, max_extra_queries=0)
        self.assertEqual([l.name for l in leads], ["John Roe", "Ann Lee"])
        self.assertEqual(stats["skipped_seen"], 1)
        self.assertEqual(stats["short_by"], 3)

        # The control: without the skip, Jane takes Acme's only slot and John
        # is lost to the company cap — which is why the skip must come first.
        leads, _, _ = self._source(lambda q, i: rows, per_company=1, target=5)
        self.assertEqual([l.name for l in leads], ["Jane Doe", "Ann Lee"])

    def test_a_seen_person_found_by_two_searches_is_one_skip(self):
        """skipped_seen counts people, not rows — it is shown to the user as a
        number of people, and Exa hands one person to several searches."""
        jane = _person("Jane Doe", "Acme Pvt Ltd")
        skip = SeenIndex(identity.keys_of(Lead(name="Jane Doe", company="Acme")))
        leads, stats, exa = self._source(lambda q, i: [jane],
                                         roles=("Plant Head", "Plant Director"),
                                         target=5, skip=skip, max_extra_queries=0)
        self.assertEqual(leads, [])
        self.assertEqual(len(exa.queries), 2)
        self.assertEqual((stats["skipped_seen"], stats["duplicates"]), (1, 0))

    def test_stats_carries_every_key_even_with_nothing_to_report(self):
        _, stats, _ = self._source(lambda q, i: [_person("Ann Lee", "Beta Motors")],
                                   target=1)
        self.assertEqual(stats, {"skipped_seen": 0, "duplicates": 0, "queries_used": 1,
                                 "query_errors": 0, "extra_queries": 0, "short_by": 0})

    def test_two_people_sharing_a_name_are_two_people(self):
        """The in-run dedupe used to be name.lower(); identity keeps two Rahul
        Shahs at two companies, and still merges one person found twice."""
        rows = [_person("Rahul Shah", "Acme Pvt Ltd", slug="rahul-shah-1"),
                _person("Rahul Shah", "Beta Motors", slug="rahul-shah-2")]
        leads, stats, _ = self._source(lambda q, i: rows,
                                       roles=("Plant Head", "Plant Director"), target=10)
        self.assertEqual([l.company for l in leads], ["Acme Pvt Ltd", "Beta Motors"])
        self.assertEqual(stats["duplicates"], 2)        # both again from the second search

    def test_without_skip_there_is_no_top_up(self):
        leads, stats, exa = self._source(
            lambda q, i: [], industries=("automobile", "pharma"),
            roles=("Plant Head", "VP Operations"), max_queries=2, target=50, stats=None)
        self.assertEqual(leads, [])
        self.assertIsNone(stats)
        self.assertEqual(len(exa.queries), 2)

    def test_a_failed_call_is_counted_and_does_not_end_the_top_up(self):
        answers = {0: None,                                     # first pass: Exa down
                   1: None,                                     # top-up round 1: still down
                   2: [_person("Ann Lee", "Beta Motors")],
                   3: [_person("Raj Iyer", "Gamma Auto"),
                       _person("Meera Rao", "Delta Castings")]}
        leads, stats, exa = self._source(lambda q, i: answers.get(i, []), target=3,
                                         skip=SeenIndex())
        self.assertEqual(len(leads), 3)
        self.assertEqual(len(exa.queries), 4)       # round 1 found nobody, but it FAILED
        self.assertEqual(stats["query_errors"], 2)
        self.assertEqual(stats["queries_used"], 4)
        self.assertEqual(stats["extra_queries"], 3)
        self.assertEqual(stats["short_by"], 0)

    def test_top_up_asks_only_new_questions_and_stops_at_its_budget(self):
        fresh = itertools.count()

        def reply(q, i):
            n = next(fresh)
            return [_person(f"Person {n}", f"Company {n}", slug=f"person-{n}")]

        inds, roles = ("automobile", "pharma"), ("Plant Head", "VP Operations")
        grid = [q for _, q in source.queries(list(inds), list(roles))]
        leads, stats, exa = self._source(reply, industries=inds, roles=roles,
                                         max_queries=2, max_extra_queries=5,
                                         target=500, skip=SeenIndex())
        self.assertEqual(len(exa.queries), 7)                 # 2 first-pass + 5 extra
        asked = {" ".join(q.casefold().split()) for q in exa.queries}
        self.assertEqual(len(asked), 7, "an Exa query was sent twice")
        self.assertEqual(set(exa.queries[:2]), set(grid[:2]))
        self.assertEqual(set(exa.queries[2:4]), set(grid[2:]))  # the cut pairings go first
        self.assertEqual(stats["extra_queries"], 5)
        self.assertEqual(stats["queries_used"], 7)
        self.assertEqual(stats["short_by"], 500 - len(leads))

    def test_progress_keeps_counting_through_the_top_up(self):
        """on_progress is the worker's "(qi/n searches)" line. The top-up calls
        it too, with the same four arguments; the count runs on from the first
        pass, and the total grows by the top-up it will actually spend, so the
        line never runs backwards or past its total."""
        fresh = itertools.count()

        def reply(q, i):
            n = next(fresh)
            return [_person(f"Person {n}", f"Company {n}", slug=f"person-{n}")]

        calls = []
        leads, _, exa = self._source(reply, industries=("automobile", "pharma"),
                                     max_queries=2, max_extra_queries=3, target=500,
                                     skip=SeenIndex(),
                                     on_progress=lambda *a: calls.append(a))
        self.assertEqual(len(exa.queries), 5)
        self.assertEqual([c[0] for c in calls], [1, 2, 3, 4, 5])
        # 2 first-pass searches, then 2 + min(budget 3, 8 planned top-up).
        self.assertEqual([c[1] for c in calls], [2, 2, 5, 5, 5])
        self.assertEqual(calls[-1][3], len(leads))

    def test_top_up_never_resends_a_question_the_first_pass_asked(self):
        """The same industry typed twice ("automobile", "Automobile") makes
        pairings that differ only in case. Exa would answer both with the same
        page, so the top-up must not pay for it again."""
        fresh = itertools.count()

        def reply(q, i):
            n = next(fresh)
            return [_person(f"Person {n}", f"Company {n}", slug=f"person-{n}")]

        _, stats, exa = self._source(reply, industries=("automobile", "Automobile"),
                                     max_queries=1, target=500, skip=SeenIndex())
        asked = [" ".join(q.casefold().split()) for q in exa.queries]
        self.assertEqual(len(asked), len(set(asked)), "an Exa query was sent twice")
        self.assertEqual(len(asked), 1 + len(source._VARIANTS))   # the pass, one per phrasing
        self.assertEqual(stats["extra_queries"], len(source._VARIANTS))

    def test_top_up_stops_the_moment_target_is_reached(self):
        def reply(q, i):
            if i == 0:
                return [_person("Ann Lee", "Beta Motors")]
            return [_person(f"Extra {i} {k}", f"Firm {i} {k}", slug=f"extra-{i}-{k}")
                    for k in range(3)]

        leads, stats, exa = self._source(reply, target=2, skip=SeenIndex())
        self.assertEqual(len(leads), 2)
        self.assertEqual(len(exa.queries), 2)
        self.assertEqual(stats["extra_queries"], 1)
        self.assertEqual(stats["short_by"], 0)

    def test_a_round_that_finds_nobody_new_ends_the_top_up(self):
        ann = _person("Ann Lee", "Beta Motors")
        leads, stats, exa = self._source(lambda q, i: [ann], target=10, skip=SeenIndex())
        self.assertEqual(len(leads), 1)
        self.assertEqual(len(exa.queries), 2)       # the first pass, one fruitless round
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["short_by"], 9)

    def test_top_up_lets_a_productive_industry_fill_past_its_share(self):
        fresh = itertools.count()

        def reply(q, i):
            if "pharma" in q:
                return []
            return [_person(f"Auto {n}", f"Auto Co {n}", slug=f"auto-{n}")
                    for n in [next(fresh) for _ in range(5)]]

        kw = dict(industries=("automobile", "pharma"), target=6, per_company=1)
        # First pass alone: automobile's share is ceil(6 / 2) = 3.
        leads, _, _ = self._source(reply, **kw)
        self.assertEqual(len(leads), 3)
        leads, _, _ = self._source(reply, skip=SeenIndex(), **kw)
        self.assertEqual(len(leads), 6)
        self.assertTrue(all(l.industry == "automobile" for l in leads))


# ── engine ───────────────────────────────────────────────────────────────────

class FilterNew(unittest.TestCase):

    def setUp(self):
        self.jane = Lead(name="Jane Doe", company="Acme Pvt Ltd", email="jane@acme.com")
        self.ravi = Lead(name="Ravi Kumar", company="Beta Motors",
                         extra={"linkedin": "linkedin.com/in/ravi-kumar"})
        self.jane_again = Lead(name="J. Doe", company="Acme", email=" JANE@acme.com ")
        self.meera = Lead(name="Meera Rao", company="Delta Castings Limited")
        earlier = Lead(name="meera rao", company="Delta Castings",
                       extra={"linkedin": "https://www.linkedin.com/in/meera-rao/"})
        self.skip = SeenIndex(identity.keys_of(earlier))

    def test_repeats_and_already_pulled_people_are_removed_and_counted(self):
        stats = {}
        kept = engine.filter_new([self.jane, self.ravi, self.jane_again, self.meera],
                                 self.skip, stats)
        self.assertEqual(len(kept), 2)
        self.assertIs(kept[0], self.jane)
        self.assertIs(kept[1], self.ravi)
        self.assertEqual(stats, {"duplicates": 1, "skipped_seen": 1})

    def test_without_skip_only_the_repeats_go(self):
        kept = engine.filter_new([self.jane, self.jane_again, self.meera])
        self.assertEqual([l.name for l in kept], ["Jane Doe", "Meera Rao"])

    def test_old_keyword_constructors_still_build_a_run_result(self):
        res = engine.RunResult(dossiers=[], total_in_sheet=0, signal_source="",
                               all_leads=[])
        self.assertEqual((res.skipped_seen, res.duplicates), (0, 0))


class RunLeadsSpendsTheLimitOnNewPeople(unittest.TestCase):
    """run_leads with nothing to call out to: no Groq key (the qualifier returns
    a no_model dossier without importing the engine), no Exa key (enrich and
    signals stay home), and time.sleep stubbed."""

    def setUp(self):
        def lead(name, title, company, email):
            return Lead(name=name, title=title, company=company, email=email,
                        industry="automobile")
        self.ceo = lead("Asha Mehta", "CEO", "Acme Pvt Ltd", "asha@acme.com")
        self.director = lead("Ravi Kumar", "Director Operations", "Beta Motors",
                             "ravi@beta.com")
        self.manager = lead("Meera Rao", "Manager", "Delta Castings", "meera@delta.com")
        self.repeat = lead("Ravi Kumar", "Director Operations", "Beta Motors Ltd",
                           "RAVI@beta.com")
        self.skip = SeenIndex(identity.keys_of(Lead(email="asha@acme.com")))
        self.sheet = [self.ceo, self.director, self.manager, self.repeat]
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("EXA_API_KEY", None)
        nap = mock.patch.object(engine.time, "sleep")
        nap.start()
        self.addCleanup(nap.stop)

    def test_limit_picks_the_best_new_person_not_the_best_person(self):
        ranked_inputs = []
        real_rank = triage.rank

        def spy(leads, offer, roles=None):
            ranked_inputs.append(list(leads))
            return real_rank(leads, offer, roles)

        stats = {"queries_used": 7, "skipped_seen": 2}
        with mock.patch.object(triage, "rank", spy):
            res = engine.run_leads(self.sheet, OFFER, {}, limit=1,
                                   skip=self.skip, stats=stats)

        self.assertEqual(len(res.dossiers), 1)
        self.assertIs(res.dossiers[0].lead, self.director)
        self.assertEqual(res.dossiers[0].status, NO_MODEL)
        # The filter ran BEFORE ranking: the seen CEO and the repeat never
        # reached triage, so they could not take the one slot.
        self.assertEqual({id(l) for l in ranked_inputs[0]},
                         {id(self.director), id(self.manager)})
        self.assertEqual([l.name for l in res.all_leads], ["Ravi Kumar", "Meera Rao"])
        self.assertEqual(res.total_in_sheet, 4)
        self.assertEqual((res.skipped_seen, res.duplicates), (1, 1))
        self.assertEqual(stats, {"queries_used": 7, "skipped_seen": 3, "duplicates": 1})

    def test_the_control_without_skip_the_ceo_wins_the_slot(self):
        res = engine.run_leads(self.sheet, OFFER, {}, limit=1)
        self.assertIs(res.dossiers[0].lead, self.ceo)
        self.assertEqual((res.skipped_seen, res.duplicates), (0, 1))

    def test_a_list_of_only_known_people_comes_back_empty_and_says_so(self):
        res = engine.run_leads([self.ceo], OFFER, {}, limit=3, skip=self.skip)
        self.assertEqual(res.dossiers, [])
        self.assertEqual(res.all_leads, [])
        self.assertEqual(res.total_in_sheet, 1)
        self.assertEqual(res.skipped_seen, 1)

    def test_the_sheet_path_hands_skip_and_stats_through(self):
        stats = {}
        with mock.patch.object(engine.sheet, "load", return_value=self.sheet) as load, \
                mock.patch.object(engine, "run_leads", return_value="result") as run_leads:
            out = engine.run("leads.xlsx", OFFER, {}, sheet_name="Sheet1", limit=2,
                             skip=self.skip, stats=stats)
        self.assertEqual(out, "result")
        load.assert_called_once_with("leads.xlsx", "Sheet1")
        self.assertIs(run_leads.call_args.kwargs["skip"], self.skip)
        self.assertIs(run_leads.call_args.kwargs["stats"], stats)
        self.assertEqual(run_leads.call_args.kwargs["limit"], 2)


# ── reach ────────────────────────────────────────────────────────────────────

class ReachMailsEachAddressOncePerBatch(unittest.TestCase):
    """send() with the SMTP sender stubbed and the suppression file in a temp
    folder — never ~/.prism/outreach_suppressed.txt."""

    def setUp(self):
        import core_bridge as CB        # the same module object send() imports
        self.CB = CB
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.suppression = os.path.join(tmp.name, "outreach_suppressed.txt")

    @staticmethod
    def _draft(email: str) -> reach.Draft:
        lead = Lead(name="Jane Doe", company="Acme", email=email)
        return reach.Draft(dossier=Dossier(lead=lead, verdict=HOT),
                           subject="A quick idea", body="Hi Jane")

    def _send(self, drafts, answer):
        with mock.patch.object(reach, "_suppression_path", return_value=self.suppression), \
                mock.patch.object(self.CB.mailer, "is_configured", return_value=True), \
                mock.patch.object(self.CB.mailer, "send_bulk", side_effect=answer) as bulk:
            sent, failed = reach.send(drafts, {"email": {}})
        return sent, failed, bulk

    def test_the_same_address_twice_is_mailed_once(self):
        first, second = self._draft("jane@acme.com"), self._draft(" Jane@Acme.com ")
        sent, failed, bulk = self._send(
            [first, second], lambda cfg, rcpts, subject, body, files=(): (rcpts, []))
        self.assertEqual(bulk.call_count, 1)
        self.assertEqual((first.status, second.status), ("sent", "skipped"))
        self.assertIn("suppression list", second.note)
        self.assertEqual((sent, failed), (["jane@acme.com"], []))
        with open(self.suppression, encoding="utf-8") as f:
            self.assertEqual(f.read().split(), ["jane@acme.com"])

    def test_a_hard_bounce_is_not_retried_later_in_the_batch(self):
        first, second = self._draft("gone@acme.com"), self._draft("gone@acme.com")
        _, failed, bulk = self._send(
            [first, second],
            lambda cfg, rcpts, subject, body, files=():
                ([], [(rcpts[0]["email"], "550 5.1.1 user unknown")]))
        self.assertEqual(bulk.call_count, 1)
        self.assertEqual((first.status, second.status), ("failed", "skipped"))
        self.assertEqual(len(failed), 1)

    def test_a_soft_failure_is_still_tried_again(self):
        """Only a send or a hard bounce suppresses — a busy server says nothing
        about the address, so its repeat still gets its chance."""
        first, second = self._draft("busy@acme.com"), self._draft("busy@acme.com")
        _, _, bulk = self._send(
            [first, second],
            lambda cfg, rcpts, subject, body, files=():
                ([], [(rcpts[0]["email"], "421 try again later")]))
        self.assertEqual(bulk.call_count, 2)


if __name__ == "__main__":
    unittest.main()
