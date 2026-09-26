"""
spacemail_check.py — Spacemail fleet connectivity audit.
========================================================

Logs into every mailbox in the fleet and reports which credentials actually
work, using the same code paths the sender uses:

    SMTP   mail.spacemail.com : 465   (SSL/TLS)
    IMAP   mail.spacemail.com : 993   (SSL/TLS)

No email is ever sent.

    python spacemail_check.py                 # whole fleet
    python spacemail_check.py zoya@flinzamedia.com   # one mailbox
"""

import argparse
import concurrent.futures
import sys

import spacemail_accounts as sa
import email_sender


def check_one(acc: dict) -> dict:
    email = acc["email"]
    password = acc["password"]

    smtp = email_sender.test_account_connection(
        email, password, smtp_host=sa.SMTP_HOST, smtp_port=sa.SMTP_PORT
    )
    imap = email_sender.test_imap_connection(
        email, password, imap_host=sa.IMAP_HOST, imap_port=sa.IMAP_PORT
    )

    return {
        "email": email,
        "smtp_ok": bool(smtp.get("success")),
        "smtp_err": smtp.get("error") or "",
        "imap_ok": bool(imap.get("success")),
        "imap_err": imap.get("error") or "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Spacemail mailbox connectivity.")
    parser.add_argument("email", nargs="?", help="audit a single mailbox instead of the fleet")
    parser.add_argument("--workers", type=int, default=4, help="parallel logins (default 4)")
    args = parser.parse_args()

    fleet = sa.load_accounts()
    if args.email:
        wanted = args.email.strip().lower()
        fleet = [a for a in fleet if a["email"].lower() == wanted]
        if not fleet:
            print(f"{args.email} is not in the fleet (.env has no matching SPACEMAIL_<n>_EMAIL).")
            return 1

    if not fleet:
        print("No Spacemail mailboxes configured. Add SPACEMAIL_<n>_EMAIL / _PASS to .env.")
        return 1

    print(f"Auditing {len(fleet)} mailbox(es) on {sa.SMTP_HOST}:{sa.SMTP_PORT} (SMTP) "
          f"and {sa.IMAP_HOST}:{sa.IMAP_PORT} (IMAP)\n")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for res in pool.map(check_one, fleet):
            results.append(res)

    width = max(len(r["email"]) for r in results)
    ok = 0
    for r in results:
        smtp_mark = "SMTP ok  " if r["smtp_ok"] else "SMTP FAIL"
        imap_mark = "IMAP ok  " if r["imap_ok"] else "IMAP FAIL"
        print(f"  {r['email']:<{width}}  {smtp_mark}  {imap_mark}")
        if r["smtp_ok"] and r["imap_ok"]:
            ok += 1
        else:
            if not r["smtp_ok"]:
                print(f"      smtp: {r['smtp_err']}")
            if not r["imap_ok"]:
                print(f"      imap: {r['imap_err']}")

    print(f"\n{ok}/{len(results)} mailboxes authenticated on both SMTP and IMAP.")
    return 0 if ok == len(results) else 2


if __name__ == "__main__":
    sys.exit(main())
