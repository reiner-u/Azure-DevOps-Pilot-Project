"""Does the ALM REST API work from this machine, and what does it say about our defects?

Run this before anything else is built on top of ALM. It only reads: it logs in, counts defects, counts the ones with
attachments, shows one defect's fields, and optionally downloads that defect's attachments to a folder.

    set ALM_USER=yourname
    set ALM_PASSWORD=...
    python scripts\\alm_check.py                     check the connection and the counts
    python scripts\\alm_check.py --defect 19548      show one defect and list its attachments
    python scripts\\alm_check.py --defect 19548 --download "ALM Attachments"

Credentials come from the environment or are typed when asked for; they are never written to a file.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from defects import alm      # noqa: E402  (the path above has to be set first)

# ALM's own query syntax. BG_ATTACHMENT is the flag the defects grid shows as the "Attachment" column.
HAS_ATTACHMENT = "{BG_ATTACHMENT['Y']}"


def ask_for_credentials():
    print("No ALM_USER / ALM_PASSWORD in the environment.")
    user = input("ALM user name: ").strip()
    return "password", user, getpass.getpass("ALM password: ")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the ALM REST API from this machine (read only)")
    parser.add_argument("--defect", type=int, help="show this defect and list its attachments")
    parser.add_argument("--download", metavar="FOLDER", help="download that defect's attachments into FOLDER")
    parser.add_argument("--count-attachments", action="store_true",
                        help="also count how many defects have attachments (one extra query)")
    args = parser.parse_args(argv)

    try:
        config = alm.load_config()
    except alm.AlmError as e:
        print("Configuration:", e)
        return 1
    print(f"ALM: {config.qcbin}  domain={config.domain}  project={config.project}")

    credentials = alm.credentials_from_environment() or ask_for_credentials()
    try:
        with alm.connect(config, credentials) as session:
            who = session.is_authenticated()
            print(f"signed in as: {who or '(ALM did not say)'}")

            total = session.defect_count()
            print(f"defects in the project: {total:,}")
            if args.count_attachments:
                with_files = session.defect_count(HAS_ATTACHMENT)
                share = f" ({with_files / total:.0%})" if total else ""
                print(f"defects with attachments: {with_files:,}{share}   <- the real number, not an estimate")

            if args.defect:
                fields = next(session.defects(query=f"{{id[{args.defect}]}}", limit=1), None)
                if not fields:
                    print(f"defect {args.defect} not found")
                    return 1
                print(f"\ndefect {args.defect}: {len(fields)} fields")
                for name in sorted(fields):
                    value = str(fields[name] or "")
                    print(f"   {name:28} {value[:70]}{'...' if len(value) > 70 else ''}")
                files = session.attachments(args.defect)
                print(f"\nattachments: {len(files)}")
                for item in files:
                    print(f"   {item.get('name')}  ({item.get('file-size')} bytes)")
                if args.download and files:
                    for item in files:
                        written = session.download_attachment(args.defect, item.get("name"), args.download)
                        print(f"   saved {written}")
    except alm.AlmError as e:
        print("\nALM said no:", e)
        print("\nIf this is the first try, check in this order: base_url (no /qcbin on the end), domain and project "
              "spelling, whether the REST API is enabled for your account, and whether the server uses a certificate "
              "this machine does not trust (verify_ssl).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
