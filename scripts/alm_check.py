"""Does the ALM REST API work from this machine, and what does it say about our defects?

Read only: it signs in, counts defects, counts the ones with attachments, shows one defect and lists or downloads its
attachments. Nothing here writes to ALM.

    python scripts\\alm_check.py --count-attachments
    python scripts\\alm_check.py --defect 19548
    python scripts\\alm_check.py --defect 19548 --download "ALM Attachments"

Signing in, in order of preference:
  * an API key: set ALM_CLIENT_ID and ALM_API_KEY_SECRET (ALM SaaS prefers this, and may accept nothing else)
  * a user name and password: set ALM_USER and ALM_PASSWORD, or let it ask
  * --cookie / --cookie-file: borrow a signed-in browser session while an API key is being arranged

Credentials are never written to a file in this folder.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from defects import alm      # noqa: E402  (the path above has to be set first)


def ask_for_credentials(user=None):
    if not user:
        print("No ALM_USER / ALM_PASSWORD in the environment.")
        user = input("ALM user name: ").strip()
    return "password", user, getpass.getpass("ALM password: ")


def build_parser():
    parser = argparse.ArgumentParser(description="Check the ALM REST API from this machine (read only)")
    parser.add_argument("--defect", type=int, help="show this defect and list its attachments")
    parser.add_argument("--download", metavar="FOLDER", help="download that defect's attachments into FOLDER")
    parser.add_argument("--count-attachments", action="store_true",
                        help="also count how many defects have attachments (one extra query)")
    parser.add_argument("--fields", action="store_true", help="list the REST field names this project uses")
    parser.add_argument("--user", help="the ALM user name (ours is of the form FirstnameLastname.Surname)")
    parser.add_argument("--cookie", help="run with a signed-in browser session instead: paste that tab's Cookie "
                                         "header. Read only, and it never logs the browser out")
    parser.add_argument("--cookie-file", help="the same, read from a file so the cookies stay out of your history")
    parser.add_argument("--auth", default="basic", choices=list(alm.AUTH_METHODS) + ["all"],
                        help="how to send the password (default: basic). 'all' tries each form in turn, and every "
                             "form costs a failed sign-in attempt, so mind the account lockout")
    parser.add_argument("--debug", action="store_true", help="print every call and its status")
    return parser


def report(session, args):
    """Everything the check prints, once there is a session (signed in, or borrowed from a browser)."""
    print(f"signed in as: {session.is_authenticated() or '(ALM did not say)'}")

    total = session.defect_count()
    print(f"defects in the project: {total:,}")
    if args.count_attachments:
        with_files = session.defect_count(alm.HAS_ATTACHMENT)
        share = f" ({with_files / total:.0%})" if total else ""
        print(f"defects with attachments: {with_files:,}{share}   <- ALM's own flag, not an estimate")

    if args.fields:
        print("\nfields this client knows about:")
        for name in sorted(alm.DEFECT_FIELDS):
            print(f"   {name:22} {alm.DEFECT_FIELDS[name]}")

    if args.defect:
        fields = next(session.defects(query=f"{{id[{args.defect}]}}", limit=1), None)
        if not fields:
            print(f"defect {args.defect} not found")
            return 1
        print(f"\ndefect {args.defect}: {len(fields)} fields")
        for name in sorted(fields):
            value = str(fields[name] or "").replace("\n", " ")
            known = alm.DEFECT_FIELDS.get(name)
            label = f"{name} ({known})" if known else name
            print(f"   {label:46} {value[:60]}{'...' if len(value) > 60 else ''}")
        files = session.attachments(args.defect)
        print(f"\nattachments: {len(files)}")
        for item in files:
            print(f"   {item.get('name')}  ({item.get('file-size')} bytes)")
        if args.download and files:
            for item in files:
                print(f"   saved {session.download_attachment(args.defect, item.get('name'), args.download)}")
    return 0


def explain(error):
    print("\nALM said no:", error)
    text = str(error)
    if "401" in text and "authenticate" in text:
        print("\nALM refused the sign-in. With --auth basic a 401 means the credentials really were rejected; with the "
              "other forms it can also mean ALM did not understand the body.")
        print("  * ALM SaaS may not accept a password for API clients at all. Ask the site administrator for an API "
              "key (client id + secret), then set ALM_CLIENT_ID and ALM_API_KEY_SECRET.")
        print("  * Until then, --cookie lets you borrow a signed-in browser session for a read-only run.")
        print("  * ALM locks an account after a few failed attempts, so stop after two or three tries.")
    elif "401" in text:
        print("\nThe session is not valid for this resource. A browser session needs an application session as well: "
              "open the URL once with ?login-form-required=y, then copy the Cookie header again.")
    else:
        print("\nCheck in this order: base_url (no /qcbin on the end), domain and project spelling, the customer_id if "
              "this is a SaaS server, whether the REST API is enabled for your account, and verify_ssl.")
    return 1


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = alm.load_config()
    except alm.AlmError as e:
        print("Configuration:", e)
        return 1
    print(f"ALM: {config.qcbin}  domain={config.domain}  project={config.project}")

    cookie = args.cookie
    if args.cookie_file:
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookie = fh.read().strip()

    try:
        if cookie:
            return report(alm.AlmSession(config, trace=args.debug).use_cookie_header(cookie), args)
        credentials = alm.credentials_from_environment()
        if credentials is None:
            credentials = ask_for_credentials(args.user)
        methods = alm.AUTH_METHODS if args.auth == "all" else (args.auth,)
        with alm.connect(config, credentials, trace=args.debug, methods=methods) as session:
            return report(session, args)
    except alm.AlmError as e:
        return explain(e)


if __name__ == "__main__":
    sys.exit(main())
