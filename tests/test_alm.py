"""Tests for the ALM REST client, against a fake server.

Nothing here touches a real ALM: a fake opener records the requests and hands back canned answers, so the things worth
checking -- the order of the sign-in calls, the X-XSRF-TOKEN rule, paging, and where downloads land -- are tested
without a server, a VPN or a password.
"""
import base64
import http.cookiejar
import io
import json
import os
import tempfile
import unittest
import urllib.error

import _paths  # noqa: F401
from defects import alm


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class FakeOpener:
    """Records every request and answers from `answers`, keyed by the path (or a (method, path) pair)."""

    def __init__(self, answers=None, errors=None):
        self.answers, self.errors, self.calls = answers or {}, errors or {}, []

    def open(self, request):
        path = request.full_url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path.split("?")[0]
        self.calls.append({"method": request.get_method(), "path": path, "url": request.full_url,
                           "headers": dict(request.header_items()), "body": request.data})
        key = (request.get_method(), path)
        if key in self.errors or path in self.errors:
            code = self.errors.get(key, self.errors.get(path))
            raise urllib.error.HTTPError(request.full_url, code, "no", {}, io.BytesIO(b"ALM says no"))
        answer = self.answers.get(key, self.answers.get(path, {}))
        if isinstance(answer, bytes):
            return FakeResponse(answer)
        return FakeResponse(json.dumps(answer).encode("utf-8"))

    def paths(self):
        return [f"{c['method']} {c['path']}" for c in self.calls]


def entity(**fields):
    return {"Fields": [{"Name": name, "values": [{"value": value}]} for name, value in fields.items()]}


CONFIG = alm.AlmConfig(base_url="https://alm.example", domain="D", project="P")


def session_with(answers=None, errors=None):
    opener = FakeOpener(answers, errors)
    session = alm.AlmSession(CONFIG, opener=opener)
    return session, opener


class SigningIn(unittest.TestCase):
    def test_a_password_login_authenticates_then_opens_a_session(self):
        session, opener = session_with()
        session.login(("password", "someone", "secret"))
        self.assertEqual(opener.paths(), ["GET /qcbin/authentication-point/authenticate",
                                          "POST /qcbin/rest/site-session"])

    def test_the_default_form_is_http_basic(self):
        session, opener = session_with()
        session.login(("password", "someone", "secret"))
        header = opener.calls[0]["headers"].get("Authorization")
        self.assertEqual(header, "Basic " + base64.b64encode(b"someone:secret").decode())

    def test_an_api_key_login_opens_the_session_by_itself(self):
        session, opener = session_with()
        session.login(("apikey", "apikey-123", "shh"))
        self.assertEqual(opener.paths(), ["POST /qcbin/rest/oauth2/login"])

    def test_the_other_forms_are_tried_in_turn_when_asked(self):
        """--auth all walks the list; each shape costs a failed attempt, which is why it is not the default."""
        session, opener = session_with(errors={"/qcbin/authentication-point/authenticate": 401,
                                               "/qcbin/authentication-point/alm-authenticate": 401})
        with self.assertRaises(alm.AlmError):
            session.login(("password", "someone", "secret"), methods=alm.AUTH_METHODS)
        self.assertEqual(opener.paths(), ["GET /qcbin/authentication-point/authenticate",
                                          "POST /qcbin/authentication-point/alm-authenticate",
                                          "POST /qcbin/authentication-point/alm-authenticate",
                                          "POST /qcbin/authentication-point/alm-authenticate"])
        self.assertIn(b'"alm-authentication"', opener.calls[1]["body"])     # the reference's example shape
        self.assertIn(b'"alm-authenticate"', opener.calls[2]["body"])       # its schema shape, which differs
        self.assertIn(b"<alm-authentication>", opener.calls[3]["body"])     # the older XML form

    def test_the_first_form_that_works_stops_the_search(self):
        session, opener = session_with(errors={"/qcbin/authentication-point/authenticate": 401})
        session.login(("password", "someone", "secret"), methods=alm.AUTH_METHODS)
        self.assertEqual(opener.paths()[:2], ["GET /qcbin/authentication-point/authenticate",
                                              "POST /qcbin/authentication-point/alm-authenticate"])
        self.assertNotIn("POST /qcbin/rest/oauth2/login", opener.paths())

    def test_logging_out_is_not_allowed_to_fail_a_run(self):
        session, opener = session_with(errors={"/qcbin/authentication-point/logout": 500})
        session.login(("apikey", "a", "b"))
        session.logout()                                          # must not raise
        self.assertFalse(session.logged_in)

    def test_the_context_manager_logs_out(self):
        session, opener = session_with()
        with session.login(("apikey", "a", "b")):
            pass
        self.assertIn("GET /qcbin/authentication-point/logout", opener.paths())

    def test_who_am_i(self):
        session, opener = session_with({"/qcbin/v2/rest/is-authenticated": {"AuthenticationInfo": {"username": "me"}}})
        self.assertEqual(session.is_authenticated(), "me")

    def test_who_am_i_when_not_signed_in(self):
        session, _ = session_with(errors={"/qcbin/v2/rest/is-authenticated": 401})
        self.assertIsNone(session.is_authenticated())


class ABorrowedBrowserSession(unittest.TestCase):
    """--cookie runs read-only against a session that belongs to the person's browser."""

    def test_the_cookies_are_sent_and_no_sign_in_happens(self):
        session, opener = session_with({"/qcbin/v2/rest/is-authenticated": {"AuthenticationInfo": {"username": "me"}}})
        session.use_cookie_header("LWSSO_COOKIE_KEY=abc; QCSession=def; XSRF-TOKEN=ghi")
        self.assertEqual(session.is_authenticated(), "me")
        self.assertEqual(opener.paths(), ["GET /qcbin/v2/rest/is-authenticated"])      # no sign-in calls
        self.assertEqual(sorted(c.name for c in session.jar), ["LWSSO_COOKIE_KEY", "QCSession", "XSRF-TOKEN"])

    def test_logging_out_would_end_the_browser_session_so_it_does_not_happen(self):
        session, opener = session_with()
        with session.use_cookie_header("QCSession=def"):
            pass
        self.assertNotIn("GET /qcbin/authentication-point/logout", opener.paths())

    def test_rubbish_in_the_header_is_skipped(self):
        session, _ = session_with()
        session.use_cookie_header("  ; QCSession=def ;novalue; =noname")
        self.assertEqual([c.name for c in session.jar], ["QCSession"])


class TheXsrfRule(unittest.TestCase):
    """ALM rejects every non-GET that does not carry the X-XSRF-TOKEN header."""

    def setUp(self):
        self.session, self.opener = session_with()
        cookie = http.cookiejar.Cookie(0, "XSRF-TOKEN", "token-123", None, False, "alm.example", True, False,
                                       "/", True, False, None, False, None, None, {})
        self.session.jar.set_cookie(cookie)

    def test_a_post_carries_the_token(self):
        self.session.request("POST", "/qcbin/rest/site-session", {})
        self.assertEqual(self.opener.calls[0]["headers"].get("X-xsrf-token"), "token-123")

    def test_a_get_does_not_need_it(self):
        self.session.request("GET", "/qcbin/rest/domains/D/projects/P/defects")
        self.assertNotIn("X-xsrf-token", self.opener.calls[0]["headers"])


class SaaS(unittest.TestCase):
    """ALM SaaS wants a customer-id header; an on-premises server neither needs nor gets one."""

    def test_the_customer_id_is_sent_when_configured(self):
        config = alm.AlmConfig(base_url="https://almcsc.saas.microfocus.com", domain="D", project="P",
                               customer_id="12345")
        opener = FakeOpener()
        alm.AlmSession(config, opener=opener).request("GET", "/qcbin/v2/rest/is-authenticated")
        self.assertEqual(opener.calls[0]["headers"].get("Customer-id"), "12345")

    def test_no_header_without_it(self):
        session, opener = session_with()
        session.request("GET", "/qcbin/v2/rest/is-authenticated")
        self.assertNotIn("Customer-id", opener.calls[0]["headers"])


class ReadingDefects(unittest.TestCase):
    def test_fields_are_flattened(self):
        self.assertEqual(alm.fields_of(entity(id="19548", status="Closed")), {"id": "19548", "status": "Closed"})

    def test_a_field_with_no_value(self):
        self.assertEqual(alm.fields_of({"Fields": [{"Name": "x"}]}), {"x": None})

    def test_defects_are_paged_through(self):
        page_one = {"entities": [entity(id=str(n)) for n in range(1, 4)], "TotalResults": 5}
        session, opener = session_with({"/qcbin/rest/domains/D/projects/P/defects": page_one})
        got = list(session.defects(page_size=3, limit=3))
        self.assertEqual([d["id"] for d in got], ["1", "2", "3"])
        self.assertIn("start-index=1", opener.calls[0]["url"])
        self.assertIn("page-size=3", opener.calls[0]["url"])

    def test_a_query_and_a_field_list_reach_the_url(self):
        session, opener = session_with({"/qcbin/rest/domains/D/projects/P/defects": {"entities": [], "TotalResults": 0}})
        list(session.defects(query="{status['New']}", fields=["id", "name"]))
        url = opener.calls[0]["url"]
        self.assertIn("query=", url)
        self.assertIn("fields=id%2Cname", url)

    def test_the_count_comes_from_total_results(self):
        session, opener = session_with({"/qcbin/rest/domains/D/projects/P/defects": {"entities": [], "TotalResults": 27643}})
        self.assertEqual(session.defect_count(), 27643)
        self.assertIn("page-size=1", opener.calls[0]["url"])

    def test_the_project_path_is_escaped(self):
        config = alm.AlmConfig(base_url="https://alm.example", domain="My Domain", project="My Project")
        session = alm.AlmSession(config, opener=FakeOpener())
        self.assertIn("/domains/My%20Domain/projects/My%20Project/defects", session._project_path("/defects"))


class Attachments(unittest.TestCase):
    def test_the_list_is_flattened(self):
        answer = {"entities": [entity(name="shot.png", **{"file-size": "1024"})]}
        session, _ = session_with({"/qcbin/rest/domains/D/projects/P/defects/19548/attachments": answer})
        files = session.attachments(19548)
        self.assertEqual(files[0]["name"], "shot.png")
        self.assertEqual(files[0]["file-size"], "1024")

    def test_a_download_lands_in_a_folder_named_after_the_defect(self):
        path = "/qcbin/rest/domains/D/projects/P/defects/19548/attachments/shot.png"
        session, opener = session_with({path: b"\x89PNG fake"})
        with tempfile.TemporaryDirectory() as folder:
            written = session.download_attachment(19548, "shot.png", folder)
            self.assertEqual(written, os.path.join(folder, "19548", "shot.png"))
            with open(written, "rb") as fh:
                self.assertEqual(fh.read(), b"\x89PNG fake")
        self.assertEqual(opener.calls[0]["headers"].get("Accept"), "application/octet-stream")


class Filtering(unittest.TestCase):
    """ALM filters server-side, which is how a run is kept to one module instead of all 27,000 defects."""

    def test_a_query_from_fields(self):
        self.assertEqual(alm.query_for(status="Closed"), "{status['Closed']}")
        self.assertEqual(alm.query_for(status="Closed", user_12="Personal Info"),
                         "{status['Closed']; user-12['Personal Info']}")

    def test_blank_values_are_left_out(self):
        self.assertIsNone(alm.query_for(status=None, user_12=""))
        self.assertEqual(alm.query_for(status="New", user_12=None), "{status['New']}")

    def test_queries_combine_inside_one_pair_of_braces(self):
        self.assertEqual(alm.combine_queries(alm.HAS_ATTACHMENT, "{status['New']}"),
                         "{attachment['Y']; status['New']}")
        self.assertEqual(alm.combine_queries(alm.HAS_ATTACHMENT, None), "{attachment['Y']}")
        self.assertIsNone(alm.combine_queries(None, None))

    def test_the_username_is_read_from_an_xml_answer_too(self):
        xml = b"<?xml version='1.0'?><AuthenticationInfo><Username>ReinerEthan.Umila</Username></AuthenticationInfo>"
        session, _ = session_with({"/qcbin/v2/rest/is-authenticated": xml})
        self.assertEqual(session.is_authenticated(), "ReinerEthan.Umila")


class SizingAnExtract(unittest.TestCase):
    """--estimate samples a few defects and multiplies up. The arithmetic is tested here; the sampling is one call."""

    def records(self):
        return [{"id": "1", "files": 2, "bytes": 2_000_000, "fetched": 2, "list_seconds": 0.4, "download_seconds": 1.0},
                {"id": "2", "files": 1, "bytes": 1_000_000, "fetched": 1, "list_seconds": 0.4, "download_seconds": 0.5},
                {"id": "3", "files": 5, "bytes": 9_000_000, "fetched": 5, "list_seconds": 0.4, "download_seconds": 4.5}]

    def test_the_projection(self):
        p = alm.project_extract(self.records(), 1000)
        self.assertEqual(p["sampled"], 3)
        self.assertEqual((p["files_min"], p["files_median"], p["files_max"]), (1, 2, 5))
        self.assertEqual(p["files_total"], 2667)                      # 8 files over 3 defects, times 1000
        self.assertEqual(p["bytes_total"], 4_000_000_000)             # 4 MB each on average
        self.assertAlmostEqual(p["throughput"], 2_000_000)            # 12 MB in 6 seconds
        self.assertAlmostEqual(p["seconds_listing"], 400)             # 0.4 s each
        self.assertAlmostEqual(p["seconds_downloading"], 2000)
        self.assertAlmostEqual(p["seconds_total"], 2400)

    def test_an_empty_sample_says_nothing_rather_than_dividing_by_zero(self):
        self.assertEqual(alm.project_extract([], 1000), {})

    def test_a_sample_with_no_downloads_does_not_divide_by_zero(self):
        records = [{"id": "1", "files": 1, "bytes": 900, "fetched": 0, "list_seconds": 0.2, "download_seconds": 0.0}]
        p = alm.project_extract(records, 10)
        self.assertEqual(p["throughput"], 0)
        self.assertEqual(p["seconds_downloading"], 0)

    def test_a_huge_attachment_is_counted_but_not_fetched(self):
        answer = {"entities": [entity(name="big.zip", **{"file-size": str(200 * 1024 * 1024)}),
                               entity(name="small.png", **{"file-size": "100"})]}
        session, opener = session_with({"/qcbin/rest/domains/D/projects/P/defects/7/attachments": answer,
                                        "/qcbin/rest/domains/D/projects/P/defects/7/attachments/small.png": b"x" * 100})
        record = alm.measure_defects(session, ["7"])[0]
        self.assertEqual(record["files"], 2)
        self.assertEqual(record["fetched"], 1)                        # the 200 MB one was not pulled
        self.assertEqual(record["bytes"], 200 * 1024 * 1024 + 100)    # but its size still counts
        self.assertNotIn("GET /qcbin/rest/domains/D/projects/P/defects/7/attachments/big.zip", opener.paths())

    def test_the_sample_is_repeatable_with_a_seed(self):
        page = {"entities": [entity(id="42")], "TotalResults": 500}
        session, _ = session_with({"/qcbin/rest/domains/D/projects/P/defects": page})
        first = session.sample_defect_ids(5, alm.HAS_ATTACHMENT, seed=7)
        second = session.sample_defect_ids(5, alm.HAS_ATTACHMENT, seed=7)
        self.assertEqual(len(first), 5)
        self.assertEqual(first, second)


class Problems(unittest.TestCase):
    def test_an_http_error_says_what_and_why(self):
        session, _ = session_with(errors={"/qcbin/rest/domains/D/projects/P/defects": 403})
        with self.assertRaises(alm.AlmError) as caught:
            session.defect_count()
        self.assertIn("403", str(caught.exception))
        self.assertIn("ALM says no", str(caught.exception))

    def test_an_expired_session_says_so_instead_of_complaining_about_json(self):
        """ALM answers an expired session with its HTML login page, which is not an obvious thing to read."""
        session, _ = session_with({"/qcbin/rest/domains/D/projects/P/defects": b"\n\n<!-- login page -->\n<html>"})
        with self.assertRaises(alm.AlmError) as caught:
            session.defect_count()
        self.assertIn("session has expired", str(caught.exception))

    def test_a_missing_config_file_says_what_to_do(self):
        with self.assertRaises(alm.AlmError) as caught:
            alm.load_config(os.path.join(tempfile.gettempdir(), "no_such_alm_config.json"))
        self.assertIn("alm_config.example.json", str(caught.exception))

    def test_an_incomplete_config_file_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "alm_config.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"base_url": "https://alm.example"}, fh)
            with self.assertRaises(alm.AlmError):
                alm.load_config(path)

    def test_credentials_come_from_the_environment_only(self):
        keys = ("ALM_USER", "ALM_PASSWORD", "ALM_CLIENT_ID", "ALM_API_KEY_SECRET")
        saved = {k: os.environ.pop(k, None) for k in keys}
        self.addCleanup(lambda: os.environ.update({k: v for k, v in saved.items() if v is not None}))
        self.assertIsNone(alm.credentials_from_environment())
        os.environ["ALM_USER"], os.environ["ALM_PASSWORD"] = "someone", "secret"
        self.assertEqual(alm.credentials_from_environment(), ("password", "someone", "secret"))
        del os.environ["ALM_USER"], os.environ["ALM_PASSWORD"]
        os.environ["ALM_CLIENT_ID"], os.environ["ALM_API_KEY_SECRET"] = "apikey-1", "shh"
        self.assertEqual(alm.credentials_from_environment(), ("apikey", "apikey-1", "shh"))

    def test_connect_without_credentials_says_so(self):
        with self.assertRaises(alm.AlmError) as caught:
            alm.connect(CONFIG, credentials=None)
        self.assertIn("ALM_USER", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
