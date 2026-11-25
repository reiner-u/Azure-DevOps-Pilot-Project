"""Tests for the ALM REST client, against a fake server.

Nothing here touches a real ALM: a fake opener records the requests and hands back canned answers, so the things worth
checking -- the order of the sign-in calls, the X-XSRF-TOKEN rule, paging, and where downloads land -- are tested
without a server, a VPN or a password.
"""
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
        self.assertEqual(opener.paths(), ["POST /qcbin/authentication-point/alm-authenticate",
                                          "POST /qcbin/rest/site-session"])
        self.assertIn(b"someone", opener.calls[0]["body"])

    def test_an_api_key_login_opens_the_session_by_itself(self):
        session, opener = session_with()
        session.login(("apikey", "apikey-123", "shh"))
        self.assertEqual(opener.paths(), ["POST /qcbin/rest/oauth2/login"])

    def test_a_server_that_refuses_json_gets_the_xml_form(self):
        session, opener = session_with(errors={("POST", "/qcbin/authentication-point/alm-authenticate"): 400})
        with self.assertRaises(alm.AlmError):
            session.login(("password", "someone", "secret"))      # both forms refused
        self.assertEqual(opener.paths().count("POST /qcbin/authentication-point/alm-authenticate"), 2)
        self.assertIn(b"<alm-authentication>", opener.calls[1]["body"])

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


class Problems(unittest.TestCase):
    def test_an_http_error_says_what_and_why(self):
        session, _ = session_with(errors={"/qcbin/rest/domains/D/projects/P/defects": 403})
        with self.assertRaises(alm.AlmError) as caught:
            session.defect_count()
        self.assertIn("403", str(caught.exception))
        self.assertIn("ALM says no", str(caught.exception))

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
