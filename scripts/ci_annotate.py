"""Turn pytest failures (JUnit XML) into GitHub Actions error annotations.

Annotations are visible on the run page and through the checks API, which
makes failures readable without downloading the full job log.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def esc(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(path: str) -> int:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::error title=pytest::could not read {path}: {exc}")
        return 0
    shown = 0
    for case in root.iter("testcase"):
        for tag in ("failure", "error"):
            node = case.find(tag)
            if node is None:
                continue
            name = f"{case.get('classname', '')}.{case.get('name', '')}"
            detail = (node.get("message") or "") + "\n" + (node.text or "")
            lines = detail.strip().splitlines()
            if len(lines) > 30:
                lines = lines[:4] + ["..."] + lines[-26:]
            body = "\n".join(lines)
            print(f"::error title={esc(name)}::{esc(body[:3500])}")
            shown += 1
    if not shown:
        print("::error title=pytest::tests failed but no failing test case was recorded (crash or collection error?)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "pytest.xml"))
