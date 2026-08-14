#!/usr/bin/env python3
"""Post an AI persona review as a GitHub pull request review.

Reads a JSON file produced by an AI review persona (e.g. "Security
Specialist") and posts it as a pull request review via the GitHub REST
API. If the persona's verdict is REQUEST_CHANGES, the review is posted
with an event of REQUEST_CHANGES and this script exits non-zero so the
calling workflow (and any required status check) fails.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REQUIRED_FIELDS = ("verdict", "summary")
VALID_VERDICTS = ("APPROVE", "REQUEST_CHANGES", "COMMENT")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Repository in owner/name form")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number")
    parser.add_argument("--persona", required=True, help="Name of the reviewing persona")
    parser.add_argument("--input", required=True, help="Path to the review JSON file")
    return parser.parse_args()


def load_review(path):
    """Load and validate the persona's review JSON output."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Review output must be a JSON object")

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ValueError(f"Review output missing required field(s): {', '.join(missing)}")

    verdict = data["verdict"]
    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"Invalid verdict '{verdict}'. Must be one of: {', '.join(VALID_VERDICTS)}"
        )

    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise ValueError("Review output 'summary' must be a non-empty string")

    comments = data.get("comments", [])
    if comments is not None and not isinstance(comments, list):
        raise ValueError("Review output 'comments', if present, must be a list")

    return data


def build_review_body(persona, review):
    body_lines = [f"### {persona} Review", "", review["summary"]]

    comments = review.get("comments") or []
    if comments:
        body_lines.append("")
        body_lines.append("**Findings:**")
        for comment in comments:
            body_lines.append(f"- {comment}")

    return "\n".join(body_lines)


def post_review(repo, pr_number, persona, review):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is required")

    payload = {
        "body": build_review_body(persona, review),
        "event": review["verdict"],
    }

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")

    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to post review ({e.code}): {details}") from e


def main():
    args = parse_args()

    try:
        review = load_review(args.input)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        print(f"Invalid review output: {e}", file=sys.stderr)
        sys.exit(1)

    post_review(args.repo, args.pr, args.persona, review)

    verdict = review["verdict"]
    if verdict == "REQUEST_CHANGES":
        print(f"{args.persona} requested changes.")
        sys.exit(1)

    print(f"{args.persona} verdict: {verdict}")


if __name__ == "__main__":
    main()
