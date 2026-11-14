"""Read the signed result from the machine sidecar and write the reward.

Runs in `main` after the agent has finished. The agent controlled that container,
so nothing local is trusted: the score counts only if the sidecar's signature over
a fresh nonce verifies with a key the agent never had.
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import urllib.request
from pathlib import Path

REWARD_PATH = Path("/logs/verifier/reward.txt")


def fetch_score() -> float:
    key = os.environ["RESULT_KEY"].encode()
    base = os.environ["MACHINE_CONTROL_URL"]
    nonce = secrets.token_hex(16)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"{base}/result?nonce={nonce}", timeout=10) as response:
        envelope = json.load(response)

    body = envelope["body"].encode()
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, envelope["signature"]):
        raise ValueError("result signature does not verify")

    result = json.loads(body)
    if result["nonce"] != nonce:
        raise ValueError("result nonce does not match")

    score = float(result["score"])
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score out of range: {score}")
    print(f"verified result: {result}")
    return score


def main() -> int:
    try:
        score = fetch_score()
    except Exception as error:  # any failure to obtain a verified score is a zero
        print(f"no verified result: {error!r}", file=sys.stderr)
        score = 0.0
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(f"{score}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
