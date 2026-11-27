"""Migrate ALM defects into Azure DevOps Bugs, with their attachments.

A DRY RUN UNLESS YOU SAY --create. A dry run reads ALM, maps every field and reports exactly what it would do, without
sending anything to Azure DevOps.

    python scripts\\migrate_defects.py --bug-fields                     what our Bug's fields are really called
    python scripts\\migrate_defects.py --status "Ready For Retest" --limit 10
    python scripts\\migrate_defects.py --status "Ready For Retest" --limit 10 --create      the pilot
    python scripts\\migrate_defects.py --verify                         compare the ledger with what ADO has

ALM: ALM_CLIENT_ID + ALM_API_KEY_SECRET, or ALM_USER + ALM_PASSWORD, or --cookie-file while an API key is arranged.
ADO: ADO_PAT, a personal access token with Work Items (read & write). Neither is ever read from a file in this folder.

Each attachment goes from ALM into memory and straight to Azure DevOps; nothing large is written to disk. Every
migrated defect is written to the ledger as it finishes, so a stopped run resumes where it left off.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from converter import area as area_path                                  # noqa: E402
from defects import ado, alm, mapping, migrate as migration              # noqa: E402
from defects.ledger import Ledger                                        # noqa: E402

LEDGER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports",
                           "migrated_defects.jsonl")


def human_bytes(count):
    for unit in ("bytes", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:,.1f} {unit}"
        count /= 1024


def build_parser():
    parser = argparse.ArgumentParser(description="ALM defects -> Azure DevOps Bugs (a dry run unless --create)")
    parser.add_argument("--create", action="store_true", help="actually create work items. Without this, nothing is "
                                                              "sent to Azure DevOps")
    parser.add_argument("--limit", type=int, default=10, help="how many defects (default 10)")
    parser.add_argument("--status", help="only defects with this ALM status, e.g. \"Ready For Retest\"")
    parser.add_argument("--module", help="only defects in this module (the user-12 field)")
    parser.add_argument("--query", help="a raw ALM query, for anything the two options above do not cover")
    parser.add_argument("--defect", type=int, help="just this one defect, by ALM ID")
    parser.add_argument("--no-attachments", action="store_true", help="fields only, skip the files")
    parser.add_argument("--cookie-file", help="borrow a signed-in ALM browser session (read only)")
    parser.add_argument("--ledger", default=LEDGER_FILE, help=f"where the record of migrated defects lives")
    parser.add_argument("--bug-fields", action="store_true", help="print our Bug's field names and stop")
    parser.add_argument("--verify", action="store_true", help="compare the ledger with what Azure DevOps has")
    parser.add_argument("--show", nargs="?", type=int, const=1, metavar="N",
                        help="print every field of the first N defects exactly as they would be written to the Bug "
                             "(default 1). The way to see what a migrated bug looks like before creating one")
    parser.add_argument("--debug", action="store_true", help="print every call and its status")
    return parser


def alm_session(args, config):
    if args.cookie_file:
        with open(args.cookie_file, encoding="utf-8") as fh:
            return alm.AlmSession(config, trace=args.debug).use_cookie_header(fh.read().strip())
    return alm.connect(config, trace=args.debug)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ado_config = ado.load_config()
    except ado.AdoError as e:
        print("Azure DevOps configuration:", e)
        return 1

    if args.bug_fields:
        session = ado.connect(ado_config, dry_run=False, trace=args.debug)
        names = session.bug_field_names()
        for display in sorted(names):
            print(f"   {display:38} {names[display]}")
        print(f"\n{len(names)} fields. Put the reference name of 'ALM ID' into alm_id_field in ado_config.json.")
        return 0

    ledger = Ledger(args.ledger)
    if args.verify:
        session = ado.connect(ado_config, dry_run=False, trace=args.debug)
        in_ado = session.existing_alm_ids(list(ledger.entries))
        missing_in_ado, missing_in_ledger = ledger.check_against(in_ado)
        print(f"ledger has {len(ledger):,} defects; Azure DevOps has {len(in_ado):,} of them")
        print(f"   in the ledger but not in ADO: {missing_in_ado or 'none'}")
        print(f"   in ADO but not in the ledger: {missing_in_ledger or 'none'}")
        return 1 if missing_in_ado else 0

    if not ado_config.alm_id_field:
        print("warning: alm_id_field is not set in ado_config.json, so bugs will carry no ALM ID and a run cannot be "
              "resumed or verified against Azure DevOps. Run --bug-fields to find it.\n")

    area = area_path.DEFAULT
    query = alm.combine_queries(alm.query_for(status=args.status, user_12=args.module), args.query,
                                f"{{id[{args.defect}]}}" if args.defect else None)
    print(f"ALM query: {query or '(everything)'}   limit {args.limit}")
    print(f"Area Path: {area}")
    print(f"Mode:      {'CREATING work items in Azure DevOps' if args.create else 'dry run, nothing will be sent'}")
    print(f"Ledger:    {args.ledger} ({len(ledger):,} already migrated)\n")

    try:
        with alm_session(args, alm.load_config()) as source:
            target = ado.connect(ado_config, dry_run=not args.create, trace=args.debug)
            defects = list(source.defects(query=query, limit=args.limit))
            already = migration.already_in_ado(target, defects)
            if already is None:
                print("   cannot ask Azure DevOps what it already has (needs alm_id_field and a token), so the "
                      "local ledger decides what to skip\n")
            elif already:
                print(f"   {len(already)} of these are already in Azure DevOps (by ALM ID) and will be skipped\n")
            else:
                print("   Azure DevOps has none of these yet\n")

            def progress(index, _total, result):
                if result.skipped:
                    print(f"   {index:>4}. ALM {result.alm_id:<8} skipped: {result.skipped}")
                elif result.failed:
                    print(f"   {index:>4}. ALM {result.alm_id:<8} FAILED: {result.failed[:120]}")
                else:
                    made = f"-> work item {result.work_item_id}" if result.work_item_id else "(dry run)"
                    print(f"   {index:>4}. ALM {result.alm_id:<8} {result.files} file(s), "
                          f"{human_bytes(result.bytes):>9}  {made}")

            results = migration.migrate(defects, source, target, area, ledger, progress,
                                        with_attachments=not args.no_attachments, already=already)
    except (alm.AlmError, ado.AdoError) as e:
        print("\nStopped:", e)
        return 1

    if not results:
        print("   no defects matched")
        return 0

    for result in results[:args.show or 0]:
        print(f"\n--- ALM {result.alm_id} would be created as ---")
        for name in sorted(result.fields):
            value = str(result.fields[name]).replace("\n", " ")
            print(f"   {name:34} {value[:96]}{'...' if len(value) > 96 else ''}")
        if result.attachment_names:
            print(f"   {'attachments':34} {', '.join(result.attachment_names)}")
        print(f"   {'(state)':34} not set: a work item is always created in its initial state")
    summary = migration.summarise(results)
    print(f"\n{summary['defects']} defect(s): {summary['created']} created, {summary['skipped']} skipped, "
          f"{summary['failed']} failed")
    print(f"   attachments {summary['files']}, {human_bytes(summary['bytes'])}, "
          f"{summary['seconds']:.0f} seconds ({summary['seconds'] / max(1, summary['defects']):.1f} s per defect)")
    if summary["unmapped"]:
        print(f"   values with no ADO equivalent, left blank: {summary['unmapped']} "
              f"(fill the maps in defects/mapping.py)")
    if not args.create:
        print("\n   This was a dry run. Nothing was sent to Azure DevOps. Add --create to do it for real.")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
