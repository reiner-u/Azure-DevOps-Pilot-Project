"""Talking to ALM (Micro Focus / OpenText ALM 24.1) over its REST API.

Why this exists: the Excel defect export carries text only. Attachments, and anything else the export leaves out, have to
come from ALM itself. ALM 24.1 has a REST API, so none of the old OTA COM business is needed.

Only the standard library is used, so nothing new has to be installed or bundled into the exe.

THE AUTHENTICATION DANCE, from the ALM Project REST API Reference (24.1 Patch 1):
  1. POST /qcbin/authentication-point/alm-authenticate   (user + password)  -> sets LWSSO_COOKIE_KEY
     or POST /qcbin/rest/oauth2/login                    (client id + secret, opens the session by itself)
  2. POST /qcbin/rest/site-session                       -> sets ALM_USER, QCSession, XSRF-TOKEN
  3. every later request sends all of those cookies back, and every non-GET also sends the X-XSRF-TOKEN header,
     or ALM rejects it
  4. GET /qcbin/authentication-point/logout when finished

CONFIRMED against that reference: the four steps above, the cookie and X-XSRF-TOKEN rules, and the /qcbin/v2/rest/...
path shape. NOT in the part of the reference we have: the defect and attachment resources themselves. Those follow the
long-standing ALM REST shape (/qcbin/rest/domains/{domain}/projects/{project}/defects...), which is why alm_check.py
exists: run it once and it says whether this server agrees.

Credentials are never written down here. The reference's own advice is "Do not include credentials as a part of the
script or job", so they come from the environment or are typed when asked for; scripts/alm_config.json (git-ignored)
holds only the server address, domain and project.
"""
import http.cookiejar
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from converter.settings import SCRIPTS_DIR

CONFIG_FILE = os.path.join(SCRIPTS_DIR, "alm_config.json")
PAGE_SIZE = 100                      # ALM pages its results; this is how many entities to ask for at a time


class AlmError(Exception):
    """Anything ALM refused, with the status and whatever it said about why."""


@dataclass
class AlmConfig:
    """Where ALM is. Not secrets: see load_config()."""
    base_url: str = ""               # e.g. https://alm.example.gov.on.ca (no /qcbin)
    domain: str = ""
    project: str = ""
    verify_ssl: bool = True          # only turn this off for a server with a self-signed certificate, knowingly

    @property
    def qcbin(self):
        return self.base_url.rstrip("/") + "/qcbin"


def load_config(path=CONFIG_FILE):
    """Read scripts/alm_config.json. Copy alm_config.example.json to it and fill it in."""
    if not os.path.exists(path):
        raise AlmError(f"no {os.path.basename(path)}: copy scripts/alm_config.example.json to it and fill in the "
                       f"server address, domain and project")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    config = AlmConfig(**{k: v for k, v in data.items() if k in AlmConfig.__dataclass_fields__})
    if not (config.base_url and config.domain and config.project):
        raise AlmError(f"{os.path.basename(path)} needs base_url, domain and project")
    return config


def credentials_from_environment():
    """-> ('password', user, password) or ('apikey', client id, secret) or None. Nothing is ever read from a file."""
    user, password = os.environ.get("ALM_USER"), os.environ.get("ALM_PASSWORD")
    if user and password:
        return "password", user, password
    client, secret = os.environ.get("ALM_CLIENT_ID"), os.environ.get("ALM_API_KEY_SECRET")
    if client and secret:
        return "apikey", client, secret
    return None


def fields_of(entity):
    """One ALM entity's {field name: first value}. ALM returns Fields as a list of {Name, values:[{value}]}."""
    out = {}
    for field in entity.get("Fields", []):
        values = field.get("values") or [{}]
        out[field.get("Name")] = values[0].get("value")
    return out


class AlmSession:
    """One logged-in ALM session. Use it as a context manager so it always logs out again."""

    def __init__(self, config, opener=None):
        self.config = config
        self.jar = http.cookiejar.CookieJar()
        if opener is not None:
            self.opener = opener                      # the tests pass a fake one in here
        else:
            handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
            if not config.verify_ssl:
                handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
            self.opener = urllib.request.build_opener(*handlers)
        self.logged_in = False

    # ----- the plumbing -----
    def _xsrf(self):
        return next((c.value for c in self.jar if c.name == "XSRF-TOKEN"), None)

    def request(self, method, path, body=None, accept="application/json", content_type="application/json"):
        """One call. `path` starts at /qcbin. Returns (status, bytes). Raises AlmError for anything ALM refused."""
        url = self.config.base_url.rstrip("/") + path
        data = body if isinstance(body, bytes) else (json.dumps(body).encode("utf-8") if body is not None else None)
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", accept)
        if data is not None:
            request.add_header("Content-Type", content_type)
        if method != "GET":
            token = self._xsrf()
            if token:                                  # ALM rejects every non-GET without this header
                request.add_header("X-XSRF-TOKEN", token)
        try:
            with self.opener.open(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"")[:400].decode("utf-8", "replace")
            e.close()                                  # an HTTPError holds the response open until it is closed
            raise AlmError(f"{method} {path} -> HTTP {e.code}. {detail}") from None
        except urllib.error.URLError as e:
            raise AlmError(f"{method} {path} -> could not reach ALM: {e.reason}. Check base_url, the network and "
                           f"verify_ssl in alm_config.json") from None

    def json_request(self, method, path, body=None):
        _status, raw = self.request(method, path, body)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            raise AlmError(f"{method} {path} returned something that is not JSON: {raw[:200]!r}") from None

    # ----- signing in and out -----
    def login(self, credentials):
        """`credentials` is what credentials_from_environment() returns."""
        kind, first, second = credentials
        if kind == "apikey":
            self.request("POST", "/qcbin/rest/oauth2/login", {"clientId": first, "secret": second})
        else:
            self._password_login(first, second)
            self.request("POST", "/qcbin/rest/site-session", {})
        self.logged_in = True
        return self

    def _password_login(self, user, password):
        """The reference shows JSON here, but older servers only take the XML form, so fall back to it."""
        body = {"alm-authentication": {"user": user, "password": password}}
        try:
            self.request("POST", "/qcbin/authentication-point/alm-authenticate", body)
        except AlmError:
            xml = (f"<alm-authentication><user>{user}</user>"
                   f"<password>{password}</password></alm-authentication>").encode("utf-8")
            self.request("POST", "/qcbin/authentication-point/alm-authenticate", xml,
                         accept="application/xml", content_type="application/xml")

    def is_authenticated(self):
        """-> the user name ALM thinks we are, or None."""
        try:
            data = self.json_request("GET", "/qcbin/v2/rest/is-authenticated")
        except AlmError:
            return None
        return (data.get("AuthenticationInfo") or {}).get("username")

    def logout(self):
        if self.logged_in:
            try:
                self.request("GET", "/qcbin/authentication-point/logout", accept="application/xml")
            except AlmError:
                pass                                   # logging out is tidiness, never a reason to fail a run
            self.logged_in = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.logout()

    # ----- defects -----
    def _project_path(self, tail):
        return (f"/qcbin/rest/domains/{urllib.parse.quote(self.config.domain)}"
                f"/projects/{urllib.parse.quote(self.config.project)}{tail}")

    def defects(self, query=None, fields=None, page_size=PAGE_SIZE, limit=None):
        """Yield defects as {field name: value}. `query` is ALM's own syntax, e.g. {status['New']}."""
        start, sent = 1, 0
        while True:
            params = {"page-size": page_size, "start-index": start}
            if query:
                params["query"] = query
            if fields:
                params["fields"] = ",".join(fields)
            data = self.json_request("GET", self._project_path("/defects?" + urllib.parse.urlencode(params)))
            entities = data.get("entities", [])
            if not entities:
                return
            for entity in entities:
                yield fields_of(entity)
                sent += 1
                if limit and sent >= limit:
                    return
            start += len(entities)
            if start > int(data.get("TotalResults", 0) or 0):
                return

    def defect_count(self, query=None):
        """How many defects match, without pulling them: ALM reports TotalResults on any page."""
        params = {"page-size": 1, "start-index": 1}
        if query:
            params["query"] = query
        data = self.json_request("GET", self._project_path("/defects?" + urllib.parse.urlencode(params)))
        return int(data.get("TotalResults", 0) or 0)

    # ----- attachments -----
    def attachments(self, defect_id):
        """The attachments of one defect as {field name: value} each (name, file size, description...)."""
        data = self.json_request("GET", self._project_path(f"/defects/{int(defect_id)}/attachments"))
        return [fields_of(entity) for entity in data.get("entities", [])]

    def download_attachment(self, defect_id, name, folder):
        """Save one attachment into `folder`, in a subfolder named after the defect. Returns the path written."""
        path = self._project_path(f"/defects/{int(defect_id)}/attachments/{urllib.parse.quote(name)}")
        _status, raw = self.request("GET", path, accept="application/octet-stream")
        target = os.path.join(folder, str(defect_id))
        os.makedirs(target, exist_ok=True)
        out = os.path.join(target, os.path.basename(name))
        with open(out, "wb") as fh:
            fh.write(raw)
        return out


def connect(config=None, credentials=None):
    """Load the config, take the credentials from the environment, log in. Raises AlmError with advice when it cannot."""
    config = config or load_config()
    credentials = credentials or credentials_from_environment()
    if credentials is None:
        raise AlmError("no credentials: set ALM_USER and ALM_PASSWORD (or ALM_CLIENT_ID and ALM_API_KEY_SECRET) in the "
                       "environment. Never put them in a file in this folder")
    return AlmSession(config).login(credentials)
