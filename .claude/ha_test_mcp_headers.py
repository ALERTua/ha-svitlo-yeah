"""
Print the Authorization header for the MCP server of the test Home Assistant.

Claude Code runs this file as the ``headersHelper`` of the ``ha-test`` server in
``.mcp.json`` and reads a JSON object of headers from stdout. Claude Code removes
variables with TOKEN in the name from the environment of the helper, so the
helper reads ``HA_TEST_TOKEN`` from the ``.env`` file in the project root.
"""

import json
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TOKEN_NAME = "HA_TEST_TOKEN"


def read_token(env_file: Path) -> str | None:
    """Return the value of ``HA_TEST_TOKEN`` from a dotenv file, or None."""
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().removeprefix("export ").strip()
        name, sep, value = line.partition("=")
        if sep and name.strip() == TOKEN_NAME:
            return value.strip().strip("\"'") or None
    return None


def main() -> int:
    """Write the headers JSON to stdout, or an error to stderr."""
    if not ENV_FILE.is_file():
        sys.stderr.write(f"{ENV_FILE} does not exist\n")
        return 1
    token = read_token(ENV_FILE)
    if not token:
        sys.stderr.write(f"{TOKEN_NAME} is not set in {ENV_FILE}\n")
        return 1
    sys.stdout.write(json.dumps({"Authorization": f"Bearer {token}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
