"""
Standalone DHPO SOAP connection test.

Usage (from backend directory):
    .venv/bin/python scripts/test_dhpo_soap.py \
        --login YOUR_ECLAIMLINK_USERNAME \
        --pwd   YOUR_ECLAIMLINK_PASSWORD \
        --from  2025-01-01 \
        --to    2025-01-31

What it tests:
  1. WSDL reachable (https://dhpo.eclaimlink.ae/ValidateTransactions.asmx?wsdl)
  2. SearchTransactions — ClaimSubmission (sent, direction=1)
  3. SearchTransactions — RemittanceAdvice (received, direction=2)
  4. DownloadTransactionFile — first file from each result (if any)
  5. Prints return codes, file counts, and any error messages

No data is written to the database — purely read/test.
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# Allow running from the backend root
sys.path.insert(0, str(Path(__file__).parent.parent))

DHPO_LIVE_WSDL    = "https://dhpo.eclaimlink.ae/ValidateTransactions.asmx?wsdl"
DHPO_ARCHIVE_WSDL = "https://dhpo.eclaimlink.ae/ClaimsAndAuthorizationsArchive.asmx?wsdl"

TX_CLAIM_SUBMISSION  = 2
TX_REMITTANCE_ADVICE = 8
DHPO_OK_CODES = {0, 1, 2, 3}


def parse_args():
    p = argparse.ArgumentParser(description="Test DHPO SOAP connection")
    p.add_argument("--login",    required=True,  help="eClaimLink username")
    p.add_argument("--pwd",      required=True,  help="eClaimLink password")
    p.add_argument("--license",  default=None,   help="Caller license / provider ID (optional)")
    p.add_argument("--from",     dest="date_from", default="2025-01-01",
                   help="Date from YYYY-MM-DD (default: 2025-01-01)")
    p.add_argument("--to",       dest="date_to",   default=date.today().isoformat(),
                   help="Date to YYYY-MM-DD (default: today)")
    p.add_argument("--archive",  action="store_true",
                   help="Use Archive endpoint instead of Live")
    p.add_argument("--download", action="store_true",
                   help="Download first file from each result set")
    return p.parse_args()


def make_client(wsdl_url: str):
    try:
        from zeep import Client
        from zeep.transports import Transport
        import requests
    except ImportError:
        print("ERROR: zeep not installed. Run:  .venv/bin/pip install zeep==4.2.1")
        sys.exit(1)

    print(f"  Connecting to WSDL: {wsdl_url}")
    session = requests.Session()
    transport = Transport(session=session, timeout=60, operation_timeout=60)
    try:
        client = Client(wsdl_url, transport=transport)
        print("  WSDL loaded OK")
        return client
    except Exception as exc:
        print(f"  ERROR loading WSDL: {exc}")
        sys.exit(1)


def test_get_new(client, login, pwd):
    print("\n[1] GetNewTransactions ...")
    try:
        result = client.service.GetNewTransactions(login=login, pwd=pwd)
        code    = (result.getNewTransactionsResult
                   if hasattr(result, "getNewTransactionsResult")
                   else getattr(result, "GetNewTransactionsResult",
                        getattr(result, "returnCode", -99)))
        xml_str = getattr(result, "xmlTransactions",
                   getattr(result, "XmlTransactions", "")) or ""
        err     = getattr(result, "errorMessage",
                   getattr(result, "ErrorMessage", "")) or ""
        print(f"  Return code : {code}")
        print(f"  Error msg   : {err or '(none)'}")
        if xml_str:
            from lxml import etree
            root  = etree.fromstring(xml_str.encode())
            files = root.findall("File")
            print(f"  Files found : {len(files)}")
            for f in files[:5]:
                print(f"    FileID={f.get('FileID')} Name={f.get('FileName')} "
                      f"Downloaded={f.get('IsDownloaded')}")
        else:
            print("  No XML returned (no new transactions or login failed)")
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")


def test_search(client, login, pwd, direction, tx_id, label,
                date_from, date_to, caller_license, do_download, tx_status=1):
    print(f"\n[SearchTransactions] {label}  direction={direction}  tx_id={tx_id}")
    from_str = date_from.strftime("%d/%m/%Y 00:00:00")
    to_str   = date_to.strftime("%d/%m/%Y 23:59:59")
    print(f"  Date range  : {from_str}  →  {to_str}")

    try:
        result = client.service.SearchTransactions(
            login=login,
            pwd=pwd,
            direction=direction,
            callerLicense=caller_license,
            ePartner=None,
            transactionID=tx_id,
            TransactionStatus=tx_status,
            transactionFileName=None,
            transactionFromDate=from_str,
            transactionToDate=to_str,
            minRecordCount=-1,
            maxRecordCount=-1,
        )
        code    = (result.searchTransactionsResult
                   if hasattr(result, "searchTransactionsResult")
                   else getattr(result, "SearchTransactionsResult", -99))
        xml_str = getattr(result, "foundTransactions",
                   getattr(result, "FoundTransactions", "")) or ""
        err     = getattr(result, "errorMessage",
                   getattr(result, "ErrorMessage", "")) or ""
        print(f"  Return code : {code}  ({'OK' if code in DHPO_OK_CODES else 'ERROR'})")
        print(f"  Error msg   : {err or '(none)'}")

        files = []
        if xml_str:
            from lxml import etree
            root  = etree.fromstring(xml_str.encode())
            files = root.findall("File")
        print(f"  Files found : {len(files)}")
        for f in files[:5]:
            print(f"    FileID={f.get('FileID')}  Name={f.get('FileName')}  "
                  f"Records={f.get('RecordCount')}  Date={f.get('TransactionDate')}")
        if len(files) > 5:
            print(f"    ... and {len(files)-5} more")

        if do_download and files:
            fid   = files[0].get("FileID")
            fname = files[0].get("FileName", f"file_{fid}.xml")
            print(f"\n  [Download] FileID={fid} ...")
            try:
                dl = client.service.DownloadTransactionFile(
                    login=login, pwd=pwd, fileId=fid
                )
                dl_code = (dl.downloadTransactionFileResult
                           if hasattr(dl, "downloadTransactionFileResult")
                           else getattr(dl, "DownloadTransactionFileResult", 0))
                dl_err  = getattr(dl, "errorMessage",
                           getattr(dl, "ErrorMessage", "")) or ""
                raw     = getattr(dl, "file",
                           getattr(dl, "File",
                            getattr(dl, "fileContent",
                             getattr(dl, "FileContent", None))))
                print(f"    Return code : {dl_code}")
                print(f"    Error msg   : {dl_err or '(none)'}")
                if raw:
                    raw_bytes = bytes(raw)
                    print(f"    Bytes received: {len(raw_bytes)}")
                    # Detect ZIP
                    if raw_bytes[:4] == b"PK\x03\x04":
                        print(f"    Content type: ZIP archive")
                    else:
                        preview = raw_bytes[:200].decode("utf-8", errors="replace")
                        print(f"    Content preview: {preview!r}")
                else:
                    print("    No file bytes returned")
            except Exception as exc:
                print(f"    EXCEPTION during download: {exc}")

    except Exception as exc:
        print(f"  EXCEPTION: {exc}")


def main():
    args = parse_args()
    date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    date_to   = datetime.strptime(args.date_to,   "%Y-%m-%d").date()
    wsdl      = DHPO_ARCHIVE_WSDL if args.archive else DHPO_LIVE_WSDL

    print("=" * 60)
    print("DHPO SOAP Connection Test")
    print("=" * 60)
    print(f"  Login    : {args.login}")
    print(f"  License  : {args.license or '(not set)'}")
    print(f"  Endpoint : {'ARCHIVE' if args.archive else 'LIVE'}")
    print(f"  Date     : {date_from}  →  {date_to}")

    client = make_client(wsdl)

    test_get_new(client, args.login, args.pwd)

    test_search(client, args.login, args.pwd,
                direction=1, tx_id=TX_CLAIM_SUBMISSION,
                label="ClaimSubmission NEW (status=1)",
                date_from=date_from, date_to=date_to,
                caller_license=args.license,
                do_download=args.download)

    test_search(client, args.login, args.pwd,
                direction=1, tx_id=TX_CLAIM_SUBMISSION,
                label="ClaimSubmission DOWNLOADED (status=2)",
                date_from=date_from, date_to=date_to,
                caller_license=args.license,
                do_download=args.download,
                tx_status=2)

    test_search(client, args.login, args.pwd,
                direction=2, tx_id=TX_REMITTANCE_ADVICE,
                label="RemittanceAdvice (received)",
                date_from=date_from, date_to=date_to,
                caller_license=args.license,
                do_download=args.download)

    print("\n" + "=" * 60)
    print("Test complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
