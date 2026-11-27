"""Tests for the Azure DevOps client, the ledger and the ALM-to-ADO migration, all against fakes.

Nothing here touches a real server, and nothing creates a work item. The point is that the parts that would be
expensive to get wrong in production -- the dry run writing nothing, the resume skipping what is done, one bad defect
not stopping a run -- are proved here instead of discovered at 3am during a migration.
"""
import io
import json
import os
import tempfile
import unittest
import urllib.error

import _paths  # noqa: F401
from defects import ado, mapping, migrate as migration
from defects.ledger import Ledger
from test_alm import FakeOpener, FakeResponse, entity, session_with      # the ALM fakes, reused

CONFIG = ado.AdoConfig(base_url="https://dev.azure.com/demo", project="Demo", alm_id_field="Custom.ALMID")

DEFECT = {"id": "19548", "name": "Sign-in page shows the wrong message", "description": "<html>steps</html>",
          "status": "Ready For Retest", "severity": "2-High", "priority": "1-Must Have", "attachment": "Y",
          "user-03": "Fixed", "user-04": "Data issue", "detected-by": "someone", "creation-time": "2015-04-23"}


class AdoFakeOpener(FakeOpener):
    """The ALM fake, matching on the end of the path: an Azure DevOps base_url carries the organisation in the path
    (https://dev.azure.com/demo), so the keys in a test read as "/_apis/..." rather than "/demo/Demo/_apis/...".""" 

    def _match(self, table, method, path):
        for key in table:
            wanted = key if isinstance(key, str) else key[1]
            if (isinstance(key, str) or key[0] == method) and path.endswith(wanted):
                return table[key]
        return None

    def open(self, request):
        path = "/" + request.full_url.split("://", 1)[-1].split("/", 1)[-1].split("?")[0]
        method = request.get_method()
        self.calls.append({"method": method, "path": path, "url": request.full_url,
                           "headers": dict(request.header_items()), "body": request.data})
        code = self._match(self.errors, method, path)
        if code:
            raise urllib.error.HTTPError(request.full_url, code, "no", {}, io.BytesIO(b"ADO says no"))
        answer = self._match(self.answers, method, path)
        if isinstance(answer, bytes):
            return FakeResponse(answer)
        return FakeResponse(json.dumps(answer if answer is not None else {}).encode("utf-8"))


def ado_session(answers=None, errors=None, dry_run=False, token="pat"):
    opener = AdoFakeOpener(answers, errors)
    return ado.AdoSession(CONFIG, token=token, opener=opener, dry_run=dry_run), opener


class CreatingABug(unittest.TestCase):
    def test_the_fields_become_a_json_patch(self):
        session, opener = ado_session({"/Demo/_apis/wit/workitems/$Bug": {"id": 190313}})
        new_id = session.create_bug({"System.Title": "A bug", "Microsoft.VSTS.Common.Priority": "1"})
        self.assertEqual(new_id, 190313)
        body = json.loads(opener.calls[0]["body"])
        self.assertEqual(body, [{"op": "add", "path": "/fields/System.Title", "value": "A bug"},
                                {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": "1"}])
        self.assertEqual(opener.calls[0]["headers"].get("Content-type"), "application/json-patch+json")

    def test_blank_fields_are_left_out_rather_than_sent_empty(self):
        session, opener = ado_session({"/Demo/_apis/wit/workitems/$Bug": {"id": 1}})
        session.create_bug({"System.Title": "A bug", "Microsoft.VSTS.Common.Severity": ""})
        self.assertEqual(len(json.loads(opener.calls[0]["body"])), 1)

    def test_attachments_are_linked_in_the_create_call(self):
        session, opener = ado_session({"/Demo/_apis/wit/workitems/$Bug": {"id": 7}})
        session.create_bug({"System.Title": "A bug"}, ["https://dev.azure.com/demo/_apis/wit/attachments/abc"])
        relation = json.loads(opener.calls[0]["body"])[-1]
        self.assertEqual(relation["path"], "/relations/-")
        self.assertEqual(relation["value"]["rel"], "AttachedFile")

    def test_a_server_that_refuses_relations_on_create_gets_them_patched_on_after(self):
        """Relations on create are not documented, so the client has to cope with a server that rejects them."""
        attempts = {"n": 0}
        original = AdoFakeOpener.open

        def sometimes_refuse(self, request):
            if request.get_method() == "POST" and "workitems/$Bug" in request.full_url:
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise urllib.error.HTTPError(request.full_url, 400, "no", {}, io.BytesIO(b"bad relation"))
            return original(self, request)

        AdoFakeOpener.open = sometimes_refuse
        self.addCleanup(setattr, AdoFakeOpener, "open", original)
        session, opener = ado_session({"/Demo/_apis/wit/workitems/$Bug": {"id": 7},
                                       "/_apis/wit/workitems/7": {"id": 7}})
        self.assertEqual(session.create_bug({"System.Title": "A bug"}, ["https://x/attachments/abc"]), 7)
        self.assertTrue(opener.paths()[-1].endswith("/_apis/wit/workitems/7"))

    def test_the_token_goes_in_as_basic_auth_with_no_user_name(self):
        session, opener = ado_session({"/Demo/_apis/wit/workitems/$Bug": {"id": 1}})
        session.create_bug({"System.Title": "A bug"})
        import base64
        self.assertEqual(opener.calls[0]["headers"].get("Authorization"),
                         "Basic " + base64.b64encode(b":pat").decode())

    def test_an_error_says_what_and_why(self):
        session, _ = ado_session(errors={"/Demo/_apis/wit/workitems/$Bug": 403})
        with self.assertRaises(ado.AdoError) as caught:
            session.create_bug({"System.Title": "A bug"})
        self.assertIn("403", str(caught.exception))


class ADryRun(unittest.TestCase):
    """The whole point of the default mode: it must not send anything."""

    def test_nothing_is_sent_and_no_token_is_needed(self):
        opener = AdoFakeOpener()
        session = ado.AdoSession(CONFIG, token=None, opener=opener, dry_run=True)
        self.assertIsNone(session.upload_attachment("x.png", b"12345"))
        self.assertIsNone(session.create_bug({"System.Title": "A bug"}))
        self.assertEqual(opener.calls, [])
        self.assertEqual(session.created, 1)
        self.assertEqual(session.uploaded_bytes, 5)

    def test_a_real_run_without_a_token_is_refused_before_anything_happens(self):
        with self.assertRaises(ado.AdoError):
            ado.AdoSession(CONFIG, token=None, opener=AdoFakeOpener(), dry_run=False)


class TheLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "sub", "ledger.jsonl")

    def test_what_is_written_is_still_there_after_reopening(self):
        ledger = Ledger(self.path)
        ledger.record(5, 190313, files=2, byte_count=1000)
        again = Ledger(self.path)
        self.assertIn("5", again)
        self.assertEqual(again.entries["5"]["work_item_id"], 190313)
        self.assertEqual(again.totals(), {"defects": 1, "files": 2, "bytes": 1000})

    def test_todo_leaves_out_what_is_done(self):
        ledger = Ledger(self.path)
        ledger.record(5, 1)
        ledger.record(19548, 2)
        self.assertEqual(ledger.todo(["5", "19548", "44133"]), ["44133"])

    def test_a_half_written_last_line_does_not_break_it(self):
        """A crash mid-write leaves a broken line; the ledger has to survive its own worst day."""
        ledger = Ledger(self.path)
        ledger.record(5, 1)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"alm_id": "999", "work_ite')
        self.assertEqual(len(Ledger(self.path)), 1)

    def test_it_can_be_checked_against_what_ado_really_has(self):
        ledger = Ledger(self.path)
        ledger.record(5, 1)
        ledger.record(19548, 2)
        missing_in_ado, missing_in_ledger = ledger.check_against({"5": 1, "44133": 3})
        self.assertEqual(missing_in_ado, ["19548"])
        self.assertEqual(missing_in_ledger, ["44133"])


class MigratingOneDefect(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ledger = Ledger(os.path.join(self.dir.name, "ledger.jsonl"))
        attachments = {"entities": [entity(name="shot.png", **{"file-size": "9"})]}
        self.source, self.source_opener = session_with({
            "/qcbin/rest/domains/D/projects/P/defects/19548/attachments": attachments,
            "/qcbin/rest/domains/D/projects/P/defects/19548/attachments/shot.png": b"123456789"})
        self.target, self.target_opener = ado_session({
            "/Demo/_apis/wit/attachments": {"id": "abc", "url": "https://dev.azure.com/demo/_apis/wit/attachments/abc"},
            "/Demo/_apis/wit/workitems/$Bug": {"id": 190313}})

    def test_the_attachment_goes_from_alm_straight_into_ado(self):
        result = migration.migrate_defect(DEFECT, self.source, self.target, "Area\\Path", self.ledger)
        self.assertEqual(result.work_item_id, 190313)
        self.assertEqual((result.files, result.bytes), (1, 9))
        self.assertTrue(any(p.endswith("/_apis/wit/attachments") for p in self.target_opener.paths()))
        self.assertIn("19548", self.ledger)

    def test_nothing_is_written_to_disk(self):
        migration.migrate_defect(DEFECT, self.source, self.target, "Area\\Path", self.ledger)
        self.assertEqual(sorted(os.listdir(self.dir.name)), ["ledger.jsonl"])

    def test_a_defect_already_in_the_ledger_is_skipped_without_any_calls(self):
        self.ledger.record("19548", 111)
        before = len(self.target_opener.calls)
        result = migration.migrate_defect(DEFECT, self.source, self.target, "Area\\Path", self.ledger)
        self.assertIn("already migrated", result.skipped)
        self.assertEqual(len(self.target_opener.calls), before)

    def test_a_defect_with_no_attachment_flag_is_not_asked_for_files(self):
        quiet = dict(DEFECT, attachment="N")
        migration.migrate_defect(quiet, self.source, self.target, "Area\\Path", self.ledger)
        self.assertNotIn("GET /qcbin/rest/domains/D/projects/P/defects/19548/attachments",
                         self.source_opener.paths())

    def test_one_bad_defect_does_not_stop_the_run(self):
        target, _ = ado_session(errors={"/Demo/_apis/wit/workitems/$Bug": 500})
        results = migration.migrate([DEFECT, dict(DEFECT, id="19549")], self.source, target, "A", self.ledger)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.failed for r in results))
        self.assertEqual(migration.summarise(results)["failed"], 2)

    def test_unmapped_values_are_reported_rather_than_guessed(self):
        odd = dict(DEFECT, severity="9-Unheard Of")
        result = migration.migrate_defect(odd, self.source, self.target, "Area\\Path", self.ledger)
        self.assertIn("severity='9-Unheard Of'", result.unmapped)

    def test_a_dry_run_creates_nothing_and_writes_no_ledger_line(self):
        target = ado.AdoSession(CONFIG, token=None, opener=AdoFakeOpener(), dry_run=True)
        result = migration.migrate_defect(DEFECT, self.source, target, "Area\\Path", self.ledger)
        self.assertIsNone(result.work_item_id)
        self.assertNotIn("19548", self.ledger)


class TheFieldMapping(unittest.TestCase):
    def test_an_alm_defect_becomes_bug_fields(self):
        fields = mapping.bug_fields_from_alm(DEFECT, "Area\\Path", alm_id_field="Custom.ALMID")
        self.assertEqual(fields["System.Title"], "Sign-in page shows the wrong message")
        self.assertEqual(fields["System.AreaPath"], "Area\\Path")
        self.assertEqual(fields["Microsoft.VSTS.Common.Severity"], "2 - High")
        self.assertEqual(fields["Microsoft.VSTS.Common.Priority"], "1")
        self.assertEqual(fields["Custom.ALMID"], "19548")
        self.assertIn("ALM defect ID: 19548", fields["Microsoft.VSTS.TCM.SystemInfo"])
        self.assertIn("ALM-status-Ready For Retest", fields["System.Tags"])

    def test_state_is_never_set_because_a_new_work_item_cannot_have_one(self):
        fields = mapping.bug_fields_from_alm(DEFECT, "Area\\Path")
        self.assertNotIn("System.State", fields)
        self.assertNotIn("System.Reason", fields)

    def test_a_long_summary_is_shortened_and_kept_in_system_info(self):
        long_one = dict(DEFECT, name="Sign-in " + "very " * 80 + "long")
        fields = mapping.bug_fields_from_alm(long_one, "A")
        self.assertLessEqual(len(fields["System.Title"]), 255)
        self.assertTrue(fields["System.Title"].endswith("..."))
        self.assertIn("Full ALM summary:", fields["Microsoft.VSTS.TCM.SystemInfo"])

    def test_a_defect_with_no_summary_still_gets_a_title(self):
        fields = mapping.bug_fields_from_alm(dict(DEFECT, name=None), "A")
        self.assertIn("no summary in ALM", fields["System.Title"])

    def test_a_field_nobody_has_identified_yet_is_still_carried(self):
        """ALM's custom fields are numbered user-01..user-25 and several hold real data (Screen, Tested on Browser,
        Tested in Build). We do not know which is which yet, so they are carried under their own name rather than
        dropped: losing nothing is the point of a migration."""
        defect = dict(DEFECT, **{"user-07": "CPT_Support Doc", "user-09": "IE 8"})
        info = mapping.bug_fields_from_alm(defect, "A")["Microsoft.VSTS.TCM.SystemInfo"]
        self.assertIn("ALM user-07: CPT_Support Doc", info)
        self.assertIn("ALM user-09: IE 8", info)

    def test_alm_plumbing_is_not_carried(self):
        defect = dict(DEFECT, **{"ver-stamp": "45", "has-linkage": "N", "cycle-id": "7", "to-mail": "someone"})
        info = mapping.bug_fields_from_alm(defect, "A")["Microsoft.VSTS.TCM.SystemInfo"]
        for noise in ("ver-stamp", "has-linkage", "cycle-id", "to-mail"):
            self.assertNotIn(noise, info)

    def test_the_comment_thread_and_the_alm_assignee_are_carried(self):
        defect = dict(DEFECT, owner="zhangman", **{"dev-comments": "<html>Mandy Zhang: root cause</html>"})
        info = mapping.bug_fields_from_alm(defect, "A")["Microsoft.VSTS.TCM.SystemInfo"]
        self.assertIn("Assigned to in ALM: zhangman", info)
        self.assertIn("Comments: <html>Mandy Zhang: root cause</html>", info)

    def test_a_field_with_its_own_ado_home_is_not_repeated_in_system_info(self):
        info = mapping.bug_fields_from_alm(DEFECT, "A")["Microsoft.VSTS.TCM.SystemInfo"]
        self.assertNotIn("Sign-in page shows the wrong message", info)      # the summary is the Title
        self.assertNotIn("<html>steps</html>", info)                        # the description is Repro Steps

    def test_an_unmapped_severity_is_left_out_rather_than_invented(self):
        fields = mapping.bug_fields_from_alm(dict(DEFECT, severity="9-Unheard Of"), "A")
        self.assertNotIn("Microsoft.VSTS.Common.Severity", fields)


if __name__ == "__main__":
    unittest.main()
