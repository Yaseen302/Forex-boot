"""Manual operator CLI. Credentials are prompted, never accepted in command args."""
import argparse
import getpass
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def main():
    parser = argparse.ArgumentParser(description="ForexLab manual customer/license management")
    parser.add_argument("--url", required=True, help="HTTPS control-plane base URL")
    commands = parser.add_subparsers(dest="command", required=True)
    customer = commands.add_parser("create-customer")
    customer.add_argument("--name", required=True)
    issue = commands.add_parser("issue-license")
    issue.add_argument("--customer-id", required=True)
    issue.add_argument("--days", type=int, default=30, choices=range(1, 3661), metavar="1..3660")
    issue.add_argument("--seats", type=int, default=1, choices=range(1, 51), metavar="1..50")
    revoke = commands.add_parser("revoke-license")
    revoke.add_argument("--license-id", required=True)
    commands.add_parser("list-customers")
    licenses = commands.add_parser("list-licenses")
    licenses.add_argument("--customer-id", required=True)
    release = commands.add_parser("revoke-device")
    release.add_argument("--device-id", required=True)
    options = parser.parse_args()
    parsed = urllib.parse.urlsplit(options.url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        parser.error("Use a base URL without credentials, query, fragment or path")
    if not parsed.hostname or (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"))):
        parser.error("HTTPS is required except on loopback development")
    token = getpass.getpass("Control-plane administrator token (hidden): ")
    if not 32 <= len(token) <= 256 or not token.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in token):
        parser.error("Administrator token must have 32–256 printable ASCII characters without whitespace")
    method = "POST"
    if options.command == "create-customer":
        path, body = "/v1/admin/customers", {"name": options.name}
    elif options.command == "issue-license":
        expiry = datetime.now(timezone.utc) + timedelta(days=options.days)
        path, body = "/v1/admin/licenses", {"customer_id": options.customer_id, "expires_at": expiry.isoformat(), "seat_limit": options.seats}
    elif options.command == "revoke-license":
        if not re.fullmatch(r"lic_[a-f0-9]{32}", options.license_id):
            parser.error("Invalid license identifier")
        path, body = "/v1/admin/licenses/" + options.license_id + "/revoke", {}
    elif options.command == "list-customers":
        path, body, method = "/v1/admin/customers", None, "GET"
    elif options.command == "list-licenses":
        if not re.fullmatch(r"cus_[a-f0-9]{32}", options.customer_id):
            parser.error("Invalid customer identifier")
        path, body, method = "/v1/admin/licenses?customer_id=" + options.customer_id, None, "GET"
    else:
        if not re.fullmatch(r"dev_[a-f0-9]{32}", options.device_id):
            parser.error("Invalid device identifier")
        path, body = "/v1/admin/devices/" + options.device_id + "/revoke", {}
    request = urllib.request.Request(options.url.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method=method)
    # No redirects: do not forward the operator credential to a different host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            result = json.loads(response.read(65536))
    except urllib.error.HTTPError as exc:
        print("Request rejected with HTTP " + str(exc.code) + "; inspect deployment status and supplied metadata.", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Request failed; check address, HTTPS certificate and service availability.", file=sys.stderr)
        return 1
    if "license_key" in result:
        print("Store the following license key securely now. It cannot be retrieved later.", file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
