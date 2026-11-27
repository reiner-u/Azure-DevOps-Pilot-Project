"""Creating Azure DevOps Bug work items over the REST API, with their attachments.

Why this exists at all: the CSV import cannot carry attachments and cannot set a state (proved by test on 2026-11-25,
see the briefing). The REST API can do both, and has no 1,000-row limit.

Two calls per attachment and one per bug:
    POST {project}/_apis/wit/attachments?fileName=x.png   the bytes        -> {id, url}
    POST {project}/_apis/wit/workitems/$Bug               a JSON Patch document, with the attachment urls as
                                                          "AttachedFile" relations
Adding the relations in the create call is not documented, so create_bug() falls back to creating the work item and
then patching the relations on, which costs one extra call per bug.

Standard library only, same as alm.py. Authentication is a personal access token sent as HTTP Basic with an empty user
name, which is how Azure DevOps expects it. The token is read from the environment, never from a file in this folder.
"""
import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from converter.settings import SCRIPTS_DIR

CONFIG_FILE = os.path.join(SCRIPTS_DIR, "ado_config.json")
WORK_ITEM_TYPE = "Bug"


class AdoError(Exception):
    """Anything Azure DevOps refused, with the status and whatever it said about why."""


@dataclass
class AdoConfig:
    """Where Azure DevOps is and what this project's fields are called. Not secrets: the token comes
    from the environment."""
    base_url: str = ""               # https://dev.azure.com/{org}, or https://{server}/{collection} on-premises
    project: str = ""
    api_version: str = "7.1"
    verify_ssl: bool = True
    # The reference name of the custom "ALM ID" field on our Bug. The display name works in a CSV import, but WIQL and
    # the REST API want the reference name, and it is not guessable: read it from
    #     {base_url}/{project}/_apis/wit/workitemtypes/Bug/fields
    alm_id_field: str = ""


def load_config(path=CONFIG_FILE):
    if not os.path.exists(path):
        raise AdoError(f"no {os.path.basename(path)}: copy scripts/ado_config.example.json to it and fill it in")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    config = AdoConfig(**{k: v for k, v in data.items() if k in AdoConfig.__dataclass_fields__})
    if not (config.base_url and config.project):
        raise AdoError(f"{os.path.basename(path)} needs base_url and project")
    return config


def token_from_environment():
    """The personal access token, from ADO_PAT. Never read from a file in this folder."""
    return os.environ.get("ADO_PAT") or None


def add(path, value):
    """One JSON Patch operation, which is how Azure DevOps takes work item fields."""
    return {"op": "add", "path": path, "value": value}


def attachment_relation(url, comment=""):
    return add("/relations/-", {"rel": "AttachedFile", "url": url, "attributes": {"comment": comment}})


class AdoSession:
    """Calls against one Azure DevOps project. Create it with a token, or with dry_run=True to write nothing."""

    def __init__(self, config, token=None, opener=None, dry_run=True, trace=False):
        self.config, self.token, self.dry_run, self.trace = config, token, dry_run, trace
        self.created, self.uploaded_bytes = 0, 0        # what a run has done, for the summary at the end
        if opener is not None:
            self.opener = opener
        elif not config.verify_ssl:
            self.opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        else:
            self.opener = urllib.request.build_opener()
        if not dry_run and not token:
            raise AdoError("no token: set ADO_PAT in the environment, or run with dry_run=True")

    # ----- plumbing -----
    def _url(self, path, **params):
        params.setdefault("api-version", self.config.api_version)
        return (self.config.base_url.rstrip("/") + path + "?" + urllib.parse.urlencode(params))

    def request(self, method, url, body=None, content_type="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body).encode("utf-8") if body is not None else None)
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", content_type)
        if self.token:                      # a PAT goes in as Basic auth with an empty user name
            request.add_header("Authorization", "Basic " + base64.b64encode(f":{self.token}".encode()).decode())
        try:
            with self.opener.open(request) as response:
                raw = response.read()
                if self.trace:
                    print(f"   {method} {url.split('?')[0]} -> {response.status}")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"")[:400].decode("utf-8", "replace")
            e.close()
            raise AdoError(f"{method} {url.split('?')[0]} -> HTTP {e.code}. {detail}") from None
        except urllib.error.URLError as e:
            raise AdoError(f"{method} {url.split('?')[0]} -> could not reach Azure DevOps: {e.reason}") from None

    def _project_url(self, tail, **params):
        return self._url(f"/{urllib.parse.quote(self.config.project)}{tail}", **params)

    # ----- attachments -----
    def upload_attachment(self, file_name, data):
        """Upload bytes and return the attachment URL to link to a work item. Returns None on a dry run."""
        self.uploaded_bytes += len(data)
        if self.dry_run:
            return None
        answer = self.request("POST", self._project_url("/_apis/wit/attachments", fileName=file_name), data,
                              content_type="application/octet-stream")
        return answer.get("url")

    # ----- work items -----
    def create_bug(self, fields, attachment_urls=(), comment="Migrated from ALM"):
        """Create one Bug. `fields` is {reference name: value}. Returns the new work item's id, or None on a dry run.

        State is deliberately not settable here: a work item is always created in its type's initial state. Whatever
        the ALM status was belongs in a tag and in the post-migration bulk edit, not in this call."""
        document = [add(f"/fields/{name}", value) for name, value in fields.items() if value not in (None, "")]
        document += [attachment_relation(url, comment) for url in attachment_urls if url]
        if self.dry_run:
            self.created += 1
            return None
        url = self._project_url(f"/_apis/wit/workitems/${WORK_ITEM_TYPE}")
        try:
            answer = self.request("POST", url, document, content_type="application/json-patch+json")
        except AdoError:
            # relations on create are not documented: fall back to creating it bare, then patching them on
            bare = [op for op in document if op["path"] != "/relations/-"]
            answer = self.request("POST", url, bare, content_type="application/json-patch+json")
            relations = [op for op in document if op["path"] == "/relations/-"]
            if relations:
                self.request("PATCH", self._url(f"/_apis/wit/workitems/{answer['id']}"), relations,
                             content_type="application/json-patch+json")
        self.created += 1
        return answer.get("id")

    def existing_alm_ids(self, alm_ids, chunk=200):
        """Which of these ALM IDs are already in Azure DevOps -> {alm id: work item id}.

        Azure DevOps is the authority on what has been migrated, not the local ledger: a ledger can be deleted, or
        live on another machine, or be missing the last line because the run died after the work item was created.
        A WIQL IN clause cannot be unbounded, so this asks in chunks."""
        if not self.config.alm_id_field or not alm_ids:
            return {}
        alm_ids = [str(i) for i in alm_ids]
        if len(alm_ids) > chunk:
            found = {}
            for start in range(0, len(alm_ids), chunk):
                found.update(self.existing_alm_ids(alm_ids[start:start + chunk], chunk))
            return found
        wanted = ", ".join(f"'{str(i)}'" for i in alm_ids)
        query = (f"SELECT [System.Id], [{self.config.alm_id_field}] FROM workitems "
                 f"WHERE [System.WorkItemType] = '{WORK_ITEM_TYPE}' AND [{self.config.alm_id_field}] IN ({wanted})")
        answer = self.request("POST", self._project_url("/_apis/wit/wiql"), {"query": query})
        ids = [str(item["id"]) for item in answer.get("workItems", [])]
        return self._alm_ids_of(ids)

    def _alm_ids_of(self, work_item_ids):
        """{alm id: work item id} for work items we already know the ids of."""
        if not work_item_ids:
            return {}
        answer = self.request("GET", self._url("/_apis/wit/workitems", ids=",".join(work_item_ids),
                                               fields=f"System.Id,{self.config.alm_id_field}"))
        found = {}
        for item in answer.get("value", []):
            alm_id = item.get("fields", {}).get(self.config.alm_id_field)
            if alm_id is not None:
                found[str(alm_id)] = item["id"]
        return found

    def bug_field_names(self):
        """Every field on a Bug in this project: {display name: reference name}. Use it to fill in alm_id_field."""
        answer = self.request("GET", self._project_url(f"/_apis/wit/workitemtypes/{WORK_ITEM_TYPE}/fields"))
        return {f.get("name"): f.get("referenceName") for f in answer.get("value", [])}


def connect(config=None, token=None, dry_run=True, trace=False):
    config = config or load_config()
    token = token or token_from_environment()
    if not dry_run and not token:
        raise AdoError("no token: set ADO_PAT in the environment (a personal access token with Work Items: read & write)")
    return AdoSession(config, token=token, dry_run=dry_run, trace=trace)
