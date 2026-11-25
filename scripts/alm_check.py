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
import time

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
    parser.add_argument("--estimate", nargs="?", type=int, const=20, metavar="N",
                        help="sample N defects that have attachments (default 20) and work out what pulling them all "
                             "would cost in files, size and time. Downloads the sample into memory only")
    parser.add_argument("--seed", type=int, help="make --estimate pick the same sample again")
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

    if args.estimate:
        estimate(session, args)

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


def human_bytes(count):
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return f"{count:,.0f} {unit}" if unit == "bytes" else f"{count:,.1f} {unit}"
        count /= 1024


def human_time(seconds):
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    return f"{seconds / 3600:.1f} hours"


def estimate(session, args):
    """Sample some defects that have attachments and say what pulling all of them would cost."""
    total = session.defect_count(alm.HAS_ATTACHMENT)
    print(f"\nsizing a full extract from {total:,} defects that have attachments")
    print(f"   picking {args.estimate} of them at random...")
    started = time.perf_counter()
    ids = session.sample_defect_ids(args.estimate, alm.HAS_ATTACHMENT, seed=args.seed)
    print(f"   sampled {len(ids)} defects in {human_time(time.perf_counter() - started)}: "
          f"{', '.join(str(i) for i in ids[:8])}{'...' if len(ids) > 8 else ''}")
    print("   reading their attachments (into memory, nothing is written to disk)...")
    records = alm.measure_defects(session, ids)
    projection = alm.project_extract(records, total)
    if not projection:
        print("   nothing to measure")
        return

    print(f"\nthe sample:")
    print(f"   files per defect      {projection['files_min']} / {projection['files_median']} / "
          f"{projection['files_max']}   (smallest / middle / largest)")
    print(f"   size per defect       {human_bytes(projection['average_bytes'])} on average")
    print(f"   listing one defect    {projection['seconds_listing'] / total:.2f} seconds")
    print(f"   download speed        {human_bytes(projection['throughput'])}/second")

    print(f"\nso pulling all {total:,} of them would be roughly:")
    print(f"   files                 {projection['files_total']:,}")
    print(f"   size                  {human_bytes(projection['bytes_total'])}")
    print(f"   time                  {human_time(projection['seconds_total'])} in one sequential pass")
    print(f"                         ({human_time(projection['seconds_listing'])} of it just asking ALM what each "
          f"defect has, {human_time(projection['seconds_downloading'])} actually moving bytes)")
    print(f"\n   Rough: it is {projection['sampled']} defects out of {total:,}, and attachment sizes vary a lot. "
          f"Run it again with a different --seed to see how much the answer moves.")
    if projection["seconds_listing"] > projection["seconds_downloading"]:
        print("   Most of the time is per-request overhead rather than data, so running several requests at once "
              "would cut it down a lot more than a faster connection would.")


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
