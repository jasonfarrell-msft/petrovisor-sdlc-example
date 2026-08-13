#!/usr/bin/env python3
"""
Posts a single automated persona's review verdict as a real GitHub PR review
(APPROVE or REQUEST_CHANGES), with inline comments for each finding.

Reads a JSON file produced by a Copilot CLI persona review step with this shape:
{
  "verdict": "APPROVE" | "REQUEST_CHANGES",
  "summary": "...",
  "findings": [
    {"file": "path", "line": 0, "severity": "blocking|warning|info", "comment": "..."}
  ]
}

Falls back to a REQUEST_CHANGES review with an explanatory comment if the input
file is missing or malformed, so a broken/timed-out AI step never silently
counts as an approval.
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def gh_api(method, url, token, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code}: {e.read().decode('utf-8')}", file=sys.stderr)
        raise


def load_review(path, persona):
    if not os.path.exists(path):
        return {
            "verdict": "REQUEST_CHANGES",
            "summary": (
                f"The automated {persona} review step did not produce an output file "
                f"({path} missing). Treating this as a failed review; changes requested "
                f"pending a successful automated review run."
            ),
            "findings": [],
        }
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if data.get("verdict") not in ("APPROVE", "REQUEST_CHANGES"):
            raise ValueError("missing/invalid verdict")
        return data
    except Exception as e:
        return {
            "verdict": "REQUEST_CHANGES",
            "summary": (
                f"The automated {persona} review output could not be parsed ({e}). "
                f"Treating this as a failed review; changes requested pending a "
                f"successful automated review run."
            ),
            "findings": [],
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--persona", required=True)
    ap.add_argument("--input", required=True)
    args = ap.parse_args()

    token = os.environ["GITHUB_TOKEN"]
    review = load_review(args.input, args.persona)

    verdict = review["verdict"]
    event = "APPROVE" if verdict == "APPROVE" else "REQUEST_CHANGES"

    findings = review.get("findings", []) or []
    body_lines = [
        f"### 🤖 Automated review — {args.persona}",
        "",
        review.get("summary", "").strip() or "_No summary provided._",
    ]
    if findings:
        body_lines.append("")
        body_lines.append("**Findings:**")
        for f in findings:
            sev = f.get("severity", "info").upper()
            file_ref = f.get("file", "")
            line_ref = f.get("line", "")
            loc = f" (`{file_ref}`{f':{line_ref}' if line_ref else ''})" if file_ref else ""
            body_lines.append(f"- **[{sev}]**{loc}: {f.get('comment', '')}")

    body = "\n".join(body_lines)

    base_url = f"https://api.github.com/repos/{args.repo}/pulls/{args.pr}"

    # Fetch the diff to know which files/lines are eligible for inline comments.
    diff_files = {}
    try:
        files_resp = gh_api("GET", f"{base_url}/files?per_page=100", token)
        for fobj in files_resp:
            diff_files[fobj["filename"]] = fobj
    except Exception as e:
        print(f"Warning: could not fetch PR files for inline comments: {e}", file=sys.stderr)

    comments = []
    for f in findings:
        file_ref = f.get("file")
        line_ref = f.get("line")
        if file_ref and line_ref and file_ref in diff_files:
            comments.append({
                "path": file_ref,
                "line": int(line_ref),
                "side": "RIGHT",
                "body": f"**[{f.get('severity','info').upper()}] {args.persona}:** {f.get('comment','')}",
            })

    payload = {
        "body": body,
        "event": event,
    }
    if comments:
        payload["comments"] = comments

    try:
        gh_api("POST", f"{base_url}/reviews", token, payload)
    except urllib.error.HTTPError:
        # Inline comments can fail if a line isn't part of the diff hunk; retry without them.
        print("Retrying review submission without inline comments...", file=sys.stderr)
        gh_api("POST", f"{base_url}/reviews", token, {"body": body, "event": event})

    print(f"Posted {event} review for persona '{args.persona}' on PR #{args.pr}.")

    # Fail the workflow job itself on REQUEST_CHANGES so this becomes a required,
    # non-bypassable status check in branch protection (a posted review alone is
    # not sufficient to block a merge).
    if verdict == "REQUEST_CHANGES":
        print(f"{args.persona} requested changes; failing this check.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
