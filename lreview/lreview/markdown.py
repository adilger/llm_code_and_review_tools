"""Render collected review JSONs as human-readable Markdown reports.

Every completed review gets a report at
<results-dir>/markdown/<change>_<subject>_ps<N>.md so the results can
be read comfortably without posting them to Gerrit. A clean review
(spec=None) writes a report saying so — it replaces the previous
run's findings report, keeping the directory in sync with the latest
review of that change+patchset.
"""

import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Optional

from .gerrit import ResolvedChange, change_ref
from .github import ResolvedGitHubPullRequest
from .ui import elapsed, format_tokens

MARKDOWN_SUBDIR = "markdown"

_REVIEW_JSON_RE = re.compile(
    r"gerrit-review-(\d+)_ps(\d+)(-[a-z]+)?\.json$")
_GITHUB_JSON_RE = re.compile(r"review-result-github_.+\.json$")


def _sanitize(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len].rstrip("_")


def markdown_filename(change, tag: str = "") -> str:
    """Report filename; `tag` is the review-mode suffix ("" for full,
    "-light" for light) so modes keep separate reports."""
    # local reviews and GitHub PRs have no patchset: their slug carries
    # the ref or PR plus the sha
    if change.number is None or getattr(change, "provider", None) == "github":
        return f"{change.slug}_{_sanitize(change.subject)}{tag}.md"
    return (f"{change.number}_{_sanitize(change.subject)}"
            f"_ps{change.patchset}{tag}.md")


# Review messages are written for Gerrit, which shows them as plain
# text: identifiers like ll_io_zero_page()/ll_io_read_page() would
# turn into italics in Markdown, and <name> into a vanished HTML tag.
_CODE_SPAN_RE = re.compile(r"`[^`\n]+`")
_CODE_LIKE_RE = re.compile(r"[_*\\`]|\w->|<\w|\w>|\w\(\)")
_LEAD_PUNCT = "\"'([{"
_TRAIL_PUNCT = "\"'.,;:!?)]}"
_PAIRS = {")": "(", "]": "[", "}": "{"}
# quote and list markers mean the same in Gerrit and Markdown
_BLOCK_MARKER_RE = re.compile(r"\s*(?:>\s*)*(?:[-*+]\s+|\d+[.)]\s+)?")


def _code_core(token: str) -> tuple[str, str, str]:
    """Split a whitespace-delimited token into (lead, core, trail):
    the surrounding prose punctuation and what is left. A closing
    bracket stays when the core opens it, as in foo()."""
    start, end = 0, len(token)
    while start < end and token[start] in _LEAD_PUNCT:
        start += 1
    while end > start and token[end - 1] in _TRAIL_PUNCT:
        ch = token[end - 1]
        core = token[start:end]
        if ch in _PAIRS and core.count(_PAIRS[ch]) >= core.count(ch):
            break
        end -= 1
    return token[:start], token[start:end], token[end:]


def _code_token(token: str) -> str:
    lead, core, trail = _code_core(token)
    if (not core or not _CODE_LIKE_RE.search(core)
            or core.startswith(("http://", "https://"))):
        return token
    fence = "``" if "`" in core else "`"
    pad = " " if core.startswith("`") or core.endswith("`") else ""
    return f"{lead}{fence}{pad}{core}{pad}{fence}{trail}"


def inline_markdown(text: str) -> str:
    """One line of plain prose as Markdown: code-like tokens (anything
    with _ * \\ ` -> <tag> or a call's ()) go into code spans, so their
    characters show as written. Existing `code spans` are kept."""
    out = []
    pos = 0
    for span in _CODE_SPAN_RE.finditer(text):
        out.append(_inline_prose(text[pos:span.start()]))
        out.append(span.group())
        pos = span.end()
    out.append(_inline_prose(text[pos:]))
    return "".join(out)


def _inline_prose(text: str) -> str:
    return "".join(_code_token(part) if part and not part.isspace()
                   else part for part in re.split(r"(\s+)", text))


# whole lines meant for a commit message: trailers and subject lines
_COMMIT_LINE_RE = re.compile(
    r"\s*(?:Fixes:\s+[0-9a-f]{7,40}\b"
    r"|(?:Change-Id|Signed-off-by|Reviewed-by|Reviewed-on|Tested-by"
    r"|Acked-by|Reported-by|Suggested-by|Co-developed-by"
    r"|Co-[Aa]uthored-[Bb]y|Test-Parameters|Lustre-change"
    r"|Lustre-commit|Link|Closes|Cc):\s+\S"
    r"|[A-Z][A-Z0-9]*-\d+ [\w./-]+: \S)")
# a source or shell line written without indentation
_CODE_LINE_RE = re.compile(
    r".*[;{}]\s*$"
    r"|\s*#\s*(?:include|define|undef|if|ifdef|ifndef|elif|else|endif)\b"
    r"|\s*(?:if|while|for|switch)\s*\(.*\)\s*$"
    r"|\s*(?:else|do)\s*$"
    r"|\s*(?:/\*|\*/|//)"
    r"|\s+\*(?:\s|/|$)"
    r"|\$ \S"
    r"|@@ ")


def _line_kind(line: str) -> str:
    if not line.strip():
        return "blank"
    if line.lstrip().startswith("```"):
        return "fence"
    if line.startswith(("    ", "\t")) or _CODE_LINE_RE.match(line):
        return "code"
    if _COMMIT_LINE_RE.match(line):
        return "commit"
    return "prose"


def _fenced(block: list[str]) -> list[str]:
    body = textwrap.dedent("\n".join(block)).split("\n")
    runs = re.findall(r"`+", "\n".join(body))
    fence = "`" * max(3, max(map(len, runs), default=0) + 1)
    return [fence, *body, fence]


def message_markdown(text: str) -> str:
    """A Gerrit plain-text review message as Markdown. Code - indented,
    or source and shell lines that are not - and lines meant for a
    commit message (Fixes: and other trailers, a subject line) become
    fenced blocks, to be read and copied as written; fenced blocks
    already there are kept. Every other line goes through
    inline_markdown()."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        kind = _line_kind(lines[i])
        if kind == "fence":
            end = i + 1
            while end < len(lines) and _line_kind(lines[end]) != "fence":
                end += 1
            block = lines[i:end + 1]
        elif kind in ("code", "commit"):
            # blank lines stay inside a block that goes on after them
            end = nxt = i + 1
            while nxt < len(lines):
                if _line_kind(lines[nxt]) == kind:
                    end = nxt + 1
                elif _line_kind(lines[nxt]) != "blank":
                    break
                nxt += 1
            block = _fenced(lines[i:end])
            end -= 1
        else:
            marker = _BLOCK_MARKER_RE.match(lines[i]).group()
            out.append(marker + inline_markdown(lines[i][len(marker):]))
            i += 1
            continue
        if out and out[-1].strip():
            out.append("")
        out += block
        i = end + 1
        if i < len(lines) and lines[i].strip():
            out.append("")
    return "\n".join(out)


def iter_findings(spec: dict):
    """Yield (path, comment) for every JSON shape: the Gerrit comments
    map or flat list, and review-result.json's findings list, whose
    general and commit-message findings have a None path."""
    findings = spec.get("findings")
    if isinstance(findings, list):
        for entry in findings:
            yield entry.get("path"), entry
        return
    comments = spec.get("comments") or {}
    if isinstance(comments, dict):
        for path, entries in comments.items():
            for entry in entries:
                yield path, entry
    else:
        for entry in comments:
            yield entry.get("path", "?"), entry


def pathless_anchor(entry: dict) -> str:
    """Where a review-result.json finding without a file belongs."""
    if entry.get("location_kind") == "commit_message":
        return "commit message"
    return "general"


def _anchor(path: Optional[str], entry: dict) -> str:
    if path is None:
        return pathless_anchor(entry)
    rng = entry.get("range")
    if rng:
        loc = f"lines {rng.get('start_line')}–{rng.get('end_line')}"
    elif entry.get("line") is not None:
        loc = f"line {entry['line']}"
    else:
        loc = "file-level"
    if entry.get("side") == "PARENT":
        loc += ", old side"
    return f"`{path}` ({loc})"


def review_markdown(
    change: ResolvedChange,
    spec: Optional[dict],
    severity: Optional[str] = None,
    model: Optional[str] = None,
    tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
    duration: Optional[float] = None,
    memory: Optional[Any] = None,
) -> str:
    findings = list(iter_findings(spec)) if spec is not None else []

    if spec is None:
        review_bits = ["clean — no findings"]
        if severity and severity != "none":
            review_bits.append(f"severity **{severity}**")
    else:
        review_bits = [f"{len(findings)} finding(s)"]
        if severity:
            review_bits.append(f"severity **{severity}**")
    run_bits = []
    if model:
        run_bits.append(model)
    if tokens is not None:
        run_bits.append(f"{format_tokens(tokens)} tokens")
    if cost_usd is not None:
        run_bits.append(f"${cost_usd:.2f}")
    if duration is not None:
        run_bits.append(elapsed(duration))

    if change.number is None:  # local review
        ref_name = getattr(change, "ref_name", "local")
        lines = [
            f"# {inline_markdown(ref_name)} — "
            f"{inline_markdown(change.subject)}",
            "",
            f"- **Commit:** `{change.sha[:12]}` "
            f"({inline_markdown(ref_name)}, local review — not tied to "
            "a Gerrit change)",
            f"- **Review:** {', '.join(review_bits)}",
        ]
    elif getattr(change, "provider", None) == "github":
        lines = [
            f"# {change.project}#{change.number} — "
            f"{inline_markdown(change.subject)}",
            "",
            f"- **Pull request:** {change.url} (head `{change.sha[:12]}`, "
            f"base `{change.base_sha[:12]}`)",
            f"- **Review:** {', '.join(review_bits)}",
        ]
    else:
        url = (f"{change.base_url.rstrip('/')}/c/{change.project}"
               f"/+/{change.number}")
        lines = [
            f"# {change.number} ps{change.patchset} — "
            f"{inline_markdown(change.subject)}",
            "",
            f"- **Change:** {url} (patchset {change.patchset}, "
            f"`{change.sha[:12]}`)",
            f"- **Review:** {', '.join(review_bits)}",
        ]
    focus = getattr(change, "since", None)
    if focus is not None:
        from .since import focus_label
        lines.append(f"- **Focus:** {focus_label(focus)}")
    if run_bits:
        lines.append(f"- **Run:** {', '.join(run_bits)}")
    if memory:
        lines.append(f"- **Review memory:** `{memory}`")
    lines.append("")

    message = (spec or {}).get("message")
    if message:
        lines += ["## Overall assessment", "", message_markdown(message),
                  ""]

    lines += ["## Findings", ""]
    if spec is None:
        note = "None — the review completed without findings."
        if memory:
            note += (" Prior findings, if any, were re-checked against "
                     "this patchset; see the review memory document for "
                     "what was verified and withdrawn.")
        lines += [note, ""]
    for i, (path, entry) in enumerate(findings, 1):
        note = ("" if entry.get("unresolved", True)
                else " *(informational)*")
        lines.append(f"### {i}. {_anchor(path, entry)}{note}")
        lines.append("")
        lines.append(message_markdown(entry.get("message", "").strip()))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_review_markdown(
    results_dir: Path,
    change: ResolvedChange,
    spec: Optional[dict],
    tag: str = "",
    **stats: Any,
) -> Path:
    md_dir = results_dir / MARKDOWN_SUBDIR
    md_dir.mkdir(parents=True, exist_ok=True)
    path = md_dir / markdown_filename(change, tag)
    path.write_text(review_markdown(change, spec, **stats))
    return path


def _reconstruct(json_path: Path, number: int, patchset: int,
                 tag: str = ""):
    """Best-effort (change, stats) for an existing review JSON, from
    summary.json when its entry matches this patchset, else from the
    review-metadata sidecar, else minimal."""
    results_dir = json_path.parent
    entry: dict = {}
    summary_path = results_dir / "summary.json"
    if summary_path.is_file():
        try:
            candidate = json.loads(summary_path.read_text()).get(
                f"{number}{tag}") or {}
            if candidate.get("patchset") == patchset:
                entry = candidate
        except json.JSONDecodeError:
            pass

    subject = entry.get("subject")
    sha = entry.get("sha")
    if not subject or not sha:
        metadata_path = (results_dir /
                         f"review-metadata-{number}_ps{patchset}{tag}.json")
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text())
                subject = subject or metadata.get("subject")
                sha = sha or metadata.get("sha")
            except json.JSONDecodeError:
                pass

    base_url = (entry.get("base_url")
                or os.environ.get("GERRIT_URL")
                or "https://review.whamcloud.com")
    change = ResolvedChange(
        number=number, project="fs/lustre-release",
        subject=subject or f"change {number}",
        sha=sha or "0" * 40, patchset=patchset,
        ref=change_ref(number, patchset), base_url=base_url)
    return change, _entry_stats(entry)


def _entry_stats(entry: dict) -> dict:
    return {
        "severity": entry.get("severity"),
        "model": entry.get("model"),
        "tokens": entry.get("tokens"),
        "cost_usd": entry.get("cost_usd"),
        "duration": entry.get("duration_s"),
    }


def _reconstruct_github(json_path: Path):
    """(change, stats) for a GitHub review JSON from the summary.json
    entry that names it, or None. The PR's identity is recorded only
    there: owner and repo names may contain the underscores that join
    them in the file's slug."""
    try:
        summary = json.loads((json_path.parent / "summary.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    for entry in summary.values():
        if (entry.get("provider") != "github"
                or entry.get("json") != json_path.name):
            continue
        owner, _, repo_name = (entry.get("repository") or "").partition("/")
        change = ResolvedGitHubPullRequest(
            owner, repo_name, entry["number"], entry.get("subject") or "",
            entry["sha"], entry.get("base_sha") or "", "",
            entry["repository"], entry.get("web_url") or "")
        return change, _entry_stats(entry)
    return None


def render_existing(
    files: Optional[list[Path]] = None,
    results_dir: Optional[Path] = None,
):
    """Render existing gerrit-review-*.json and GitHub
    review-result-*.json files to Markdown.

    Returns (written_paths, skipped) where skipped is a list of
    (path, reason) for files that could not be rendered.
    """
    if files:
        targets = [Path(f) for f in files]
    else:
        base = results_dir or Path(".")
        targets = (sorted(base.glob("gerrit-review-*.json"))
                   + sorted(base.glob("review-result-*.json")))

    written: list[Path] = []
    skipped: list[tuple] = []
    for json_path in targets:
        match = _REVIEW_JSON_RE.search(json_path.name)
        github = _GITHUB_JSON_RE.search(json_path.name)
        if not match and not github:
            skipped.append((json_path,
                            "name is not gerrit-review-<N>_ps<M>.json "
                            "or review-result-github_<slug>.json"))
            continue
        try:
            spec = json.loads(json_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append((json_path, str(exc)))
            continue
        if not isinstance(spec, dict):
            skipped.append((json_path, "not a JSON object"))
            continue
        if github:
            found = _reconstruct_github(json_path)
            if found is None:
                skipped.append((json_path,
                                "no summary.json entry names this file; "
                                "the PR it reviewed is recorded only there"))
                continue
            change, stats = found
            tag = ""
        else:
            tag = match.group(3) or ""
            change, stats = _reconstruct(
                json_path, int(match.group(1)), int(match.group(2)), tag)
        written.append(write_review_markdown(
            json_path.parent, change, spec, tag=tag, **stats))
    return written, skipped
