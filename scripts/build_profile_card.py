#!/usr/bin/env python3
"""Build the profile README SVG cards."""

from __future__ import annotations

import argparse
import calendar
import html
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIDTH = 1280
HEIGHT = 720
ASCII_COLS = 48
ASCII_ROWS = 44
ASCII_FONT_SIZE = 15
ASCII_LINE_HEIGHT = 14.4
TERM_X = 535
TERM_Y = 88
TERM_LINE_HEIGHT = 25
TERM_FONT_SIZE = 19
TERM_COLUMNS = 61
REQUEST_TIMEOUT = 12
LINE_STAT_WORKERS = 8
TICK_X = 1190

DATE_OF_BIRTH = date(2002, 12, 21)
DEFAULT_LOGIN = "CryptoMaN-Rahul"
DEFAULT_LINKEDIN = "linkedin.com/in/0x-rahul"
DEFAULT_X = "@100x_rahul"
DEFAULT_ASCII = ROOT / "assets" / "profile_ascii.txt"
DEFAULT_STATS_CACHE = ROOT / "assets" / "profile_stats_cache.json"
USER_AGENT = "cryptoman-rahul-profile-card"
DEFAULT_PHOTO_CROP = "0.20,0.07,0.80,0.64"


@dataclass(frozen=True)
class RepoSnapshot:
    name: str
    head_oid: str | None


@dataclass(frozen=True)
class GitHubStats:
    login: str
    name: str
    location: str
    created_at: date | None
    public_repos: int
    stars: int
    forks: int
    default_branch_commits: int
    authored_commits: int | None
    lines_added: int | None
    lines_deleted: int | None
    visible_contributions: int | None
    private_contributions: int | None
    commit_contributions: int | None
    pull_request_contributions: int | None
    merged_pull_requests: int | None
    followers: int
    languages: list[str]
    repos_for_line_stats: list[RepoSnapshot]


THEMES = {
    "dark": {
        "file": "dark_mode.svg",
        "canvas": "#0d1117",
        "panel": "#161b22",
        "border": "#30363d",
        "ascii": "#c9d1d9",
        "title": "#e6edf3",
        "muted": "#6e7681",
        "label": "#ffa657",
        "value": "#a5d6ff",
        "green": "#3fb950",
        "red": "#ff7b72",
    },
    "light": {
        "file": "light_mode.svg",
        "canvas": "#ffffff",
        "panel": "#f6f8fa",
        "border": "#d0d7de",
        "ascii": "#57606a",
        "title": "#24292f",
        "muted": "#8c959f",
        "label": "#bc4c00",
        "value": "#0969da",
        "green": "#1a7f37",
        "red": "#cf222e",
    },
}


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def escape_text(value: str) -> str:
    return html.escape(value, quote=False)


def format_int(value: int | None) -> str:
    return f"{value:,}" if value is not None else "unavailable"


def env_or(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value or not value.strip():
        return default
    return int(value)


def age_since(start: date, today: date | None = None) -> str:
    today = today or date.today()
    years = today.year - start.year
    months = today.month - start.month
    days = today.day - start.day

    if days < 0:
        months -= 1
        previous_month = today.month - 1 or 12
        previous_year = today.year if today.month > 1 else today.year - 1
        days += calendar.monthrange(previous_year, previous_month)[1]
    if months < 0:
        years -= 1
        months += 12

    return f"{years} years, {months} months, {days} days"


def age_since_short(start: date, today: date | None = None) -> str:
    today = today or date.today()
    years = today.year - start.year
    months = today.month - start.month
    days = today.day - start.day

    if days < 0:
        months -= 1
        previous_month = today.month - 1 or 12
        previous_year = today.year if today.month > 1 else today.year - 1
        days += calendar.monthrange(previous_year, previous_month)[1]
    if months < 0:
        years -= 1
        months += 12

    return f"{years}y {months}m {days}d"


def parse_github_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def format_date(value: date | None) -> str:
    if value is None:
        return "unknown"
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[value.month - 1]} {value.day}, {value.year}"


def github_token() -> str | None:
    for name in ("PROFILE_STATS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()

    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    return token or None


def request_json(url: str, token: str | None = None, payload: dict | None = None) -> tuple[int, object]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub request failed ({error.code}) for {url}: {raw}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"GitHub request failed for {url}: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError(f"GitHub request timed out for {url}") from error


def graphql(token: str, query: str, variables: dict) -> dict:
    _status, payload = request_json(
        "https://api.github.com/graphql",
        token=token,
        payload={"query": query, "variables": variables},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub GraphQL returned an unexpected response")
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload


def repository_commit_count(repo: dict) -> int:
    branch = repo.get("defaultBranchRef") or {}
    target = branch.get("target") or {}
    history = target.get("history") or {}
    return int(history.get("totalCount") or 0)


def fetch_graphql_stats(login: str, token: str) -> GitHubStats:
    query = """
    query($login: String!, $after: String, $mergedPrQuery: String!) {
      user(login: $login) {
        login
        name
        location
        createdAt
        followers { totalCount }
        contributionsCollection {
          totalCommitContributions
          totalPullRequestContributions
          restrictedContributionsCount
          contributionCalendar { totalContributions }
        }
        repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes {
            nameWithOwner
            stargazerCount
            forkCount
            primaryLanguage { name }
            defaultBranchRef {
              target {
                oid
                ... on Commit {
                  history(first: 0) { totalCount }
                }
              }
            }
          }
        }
      }
      mergedPullRequests: search(query: $mergedPrQuery, type: ISSUE, first: 0) {
        issueCount
      }
    }
    """
    repos: list[dict] = []
    user: dict | None = None
    merged_pull_requests: int | None = None
    after: str | None = None

    while True:
        payload = graphql(
            token,
            query,
            {
                "login": login,
                "after": after,
                "mergedPrQuery": f"author:{login} is:pr is:merged",
            },
        )
        data = payload.get("data", {})
        user = data.get("user")
        if not user:
            raise RuntimeError(f"GitHub user not found: {login}")
        merged_search = data.get("mergedPullRequests") or {}
        if merged_pull_requests is None and "issueCount" in merged_search:
            merged_pull_requests = int(merged_search["issueCount"])
        repositories = user["repositories"]
        repos.extend(repositories["nodes"])
        page_info = repositories["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]

    language_counts = Counter(
        repo["primaryLanguage"]["name"]
        for repo in repos
        if repo.get("primaryLanguage") and repo["primaryLanguage"].get("name")
    )
    contributions = user.get("contributionsCollection") or {}
    calendar_data = contributions.get("contributionCalendar") or {}

    return GitHubStats(
        login=user["login"],
        name=user.get("name") or user["login"],
        location=user.get("location") or "",
        created_at=parse_github_date(user.get("createdAt")),
        public_repos=int(user["repositories"]["totalCount"]),
        stars=sum(int(repo.get("stargazerCount") or 0) for repo in repos),
        forks=sum(int(repo.get("forkCount") or 0) for repo in repos),
        default_branch_commits=sum(repository_commit_count(repo) for repo in repos),
        authored_commits=None,
        lines_added=None,
        lines_deleted=None,
        visible_contributions=calendar_data.get("totalContributions"),
        private_contributions=contributions.get("restrictedContributionsCount"),
        commit_contributions=contributions.get("totalCommitContributions"),
        pull_request_contributions=contributions.get("totalPullRequestContributions"),
        merged_pull_requests=merged_pull_requests,
        followers=int(user["followers"]["totalCount"]),
        languages=[name for name, _count in language_counts.most_common(8)],
        repos_for_line_stats=[
            RepoSnapshot(
                name=repo["nameWithOwner"],
                head_oid=((repo.get("defaultBranchRef") or {}).get("target") or {}).get("oid"),
            )
            for repo in repos
        ],
    )


def fetch_merged_pr_count(login: str, token: str | None) -> int | None:
    query = urllib.parse.urlencode({"q": f"author:{login} is:pr is:merged"})
    try:
        _status, payload = request_json(f"https://api.github.com/search/issues?{query}", token=token)
    except RuntimeError as error:
        warn(f"Merged PR stats unavailable: {error}")
        return None
    if not isinstance(payload, dict):
        return None
    total = payload.get("total_count")
    return int(total) if isinstance(total, int) else None


def fetch_rest_stats(login: str, token: str | None) -> GitHubStats:
    _status, user = request_json(f"https://api.github.com/users/{login}", token=token)
    if not isinstance(user, dict):
        raise RuntimeError(f"GitHub user not found: {login}")

    repos: list[dict] = []
    page = 1
    while True:
        _status, payload = request_json(
            f"https://api.github.com/users/{login}/repos?per_page=100&type=owner&page={page}",
            token=token,
        )
        if not isinstance(payload, list) or not payload:
            break
        repos.extend(payload)
        page += 1

    language_counts = Counter(repo.get("language") for repo in repos if repo.get("language"))
    return GitHubStats(
        login=user["login"],
        name=user.get("name") or user["login"],
        location=user.get("location") or "",
        created_at=parse_github_date(user.get("created_at")),
        public_repos=int(user.get("public_repos") or len(repos)),
        stars=sum(int(repo.get("stargazers_count") or 0) for repo in repos),
        forks=sum(int(repo.get("forks_count") or 0) for repo in repos),
        default_branch_commits=0,
        authored_commits=None,
        lines_added=None,
        lines_deleted=None,
        visible_contributions=None,
        private_contributions=None,
        commit_contributions=None,
        pull_request_contributions=None,
        merged_pull_requests=fetch_merged_pr_count(login, token),
        followers=int(user.get("followers") or 0),
        languages=[name for name, _count in language_counts.most_common(8)],
        repos_for_line_stats=[
            RepoSnapshot(
                name=repo["full_name"],
                head_oid=repo.get("pushed_at") or repo.get("updated_at"),
            )
            for repo in repos
            if repo.get("full_name")
        ],
    )


def fetch_contributor_totals(repo: str, login: str, token: str | None) -> tuple[int, int, int] | None:
    url = f"https://api.github.com/repos/{repo}/stats/contributors"
    for attempt in range(2):
        status, payload = request_json(url, token=token)
        if status == 202:
            time.sleep(1 + attempt)
            continue
        if not isinstance(payload, list):
            return None
        for contributor in payload:
            author = contributor.get("author") or {}
            if (author.get("login") or "").lower() != login.lower():
                continue
            weeks = contributor.get("weeks") or []
            commits = int(contributor.get("total") or 0)
            additions = sum(int(week.get("a") or 0) for week in weeks)
            deletions = sum(int(week.get("d") or 0) for week in weeks)
            return commits, additions, deletions
        return None
    return None


def load_stats_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        warn(f"Could not read stats cache {path}: {error}")
        return {}
    return payload if isinstance(payload, dict) else {}


def write_stats_cache(path: Path, login: str, repos: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "login": login,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "repos": dict(sorted(repos.items())),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def valid_line_entry(entry: object, repo: RepoSnapshot) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("head_oid") != repo.head_oid:
        return False
    return all(isinstance(entry.get(key), int) for key in ("commits", "additions", "deletions"))


def add_line_totals(entry: dict, totals: dict[str, int]) -> None:
    totals["commits"] += int(entry["commits"])
    totals["additions"] += int(entry["additions"])
    totals["deletions"] += int(entry["deletions"])


def with_line_stats(
    stats: GitHubStats,
    token: str | None,
    cache_path: Path,
    refresh_all: bool = False,
) -> GitHubStats:
    commits = 0
    additions = 0
    deletions = 0
    found_any = False
    max_repos = env_int("PROFILE_LINE_STAT_REPOS", len(stats.repos_for_line_stats))
    repos = stats.repos_for_line_stats[:max_repos]
    workers = max(1, env_int("PROFILE_LINE_STAT_WORKERS", LINE_STAT_WORKERS))
    cache = load_stats_cache(cache_path)
    cached_entries = cache.get("repos") if isinstance(cache.get("repos"), dict) else {}
    next_entries: dict[str, dict] = {}
    aggregate = {"commits": 0, "additions": 0, "deletions": 0}
    repos_to_fetch: list[RepoSnapshot] = []

    for repo in repos:
        cached = cached_entries.get(repo.name)
        if not refresh_all and valid_line_entry(cached, repo):
            next_entries[repo.name] = cached
            add_line_totals(cached, aggregate)
            found_any = True
        else:
            repos_to_fetch.append(repo)

    if repos_to_fetch:
        warn(f"Refreshing line stats for {len(repos_to_fetch)} changed/new repo(s)")

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(repos_to_fetch)))) as executor:
        futures = {
            executor.submit(fetch_contributor_totals, repo.name, stats.login, token): repo
            for repo in repos_to_fetch
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                repo_totals = future.result()
            except RuntimeError as error:
                warn(f"{repo.name}: {error}")
                stale = cached_entries.get(repo.name)
                if valid_line_entry(stale, repo):
                    next_entries[repo.name] = stale
                    add_line_totals(stale, aggregate)
                    found_any = True
                continue
            if repo_totals is None:
                stale = cached_entries.get(repo.name)
                if valid_line_entry(stale, repo):
                    next_entries[repo.name] = stale
                    add_line_totals(stale, aggregate)
                    found_any = True
                else:
                    next_entries[repo.name] = {
                        "head_oid": repo.head_oid,
                        "commits": 0,
                        "additions": 0,
                        "deletions": 0,
                    }
                    found_any = True
                continue
            found_any = True
            repo_commits, repo_additions, repo_deletions = repo_totals
            entry = {
                "head_oid": repo.head_oid,
                "commits": repo_commits,
                "additions": repo_additions,
                "deletions": repo_deletions,
            }
            next_entries[repo.name] = entry
            add_line_totals(entry, aggregate)

    if not found_any:
        return stats

    if repos_to_fetch:
        write_stats_cache(cache_path, stats.login, next_entries)

    return replace(
        stats,
        authored_commits=aggregate["commits"],
        lines_added=aggregate["additions"],
        lines_deleted=aggregate["deletions"],
    )


def fetch_github_stats(
    login: str,
    cache_path: Path = DEFAULT_STATS_CACHE,
    refresh_line_stats: bool = False,
) -> GitHubStats:
    token = github_token()
    if token:
        try:
            return with_line_stats(fetch_graphql_stats(login, token), token, cache_path, refresh_line_stats)
        except RuntimeError as error:
            warn(f"GraphQL stats failed, falling back to REST: {error}")
    return with_line_stats(fetch_rest_stats(login, token), token, cache_path, refresh_line_stats)


def language_summary(stats: GitHubStats) -> str:
    languages = [language for language in stats.languages if language != "HTML"]
    if languages:
        return ", ".join(languages[:5])
    return "TypeScript, Python, Go, JavaScript"


def contribution_summary(stats: GitHubStats) -> str:
    if stats.visible_contributions is None:
        return "Contributed: unavailable"
    if stats.private_contributions is None:
        return f"{format_int(stats.visible_contributions)} visible"
    return f"{format_int(stats.visible_contributions)} visible + {format_int(stats.private_contributions)} private"


def commit_summary(stats: GitHubStats) -> str:
    commits = stats.authored_commits
    if commits is None:
        commits = stats.default_branch_commits
    return format_int(commits)


def lines_summary(stats: GitHubStats) -> str:
    if stats.lines_added is None or stats.lines_deleted is None:
        return "unavailable"
    net = stats.lines_added - stats.lines_deleted
    return f"{format_int(net)} ({format_int(stats.lines_added)}++, {format_int(stats.lines_deleted)}--)"


def animated_seconds(y: int) -> str:
    frames = []
    for second in range(60):
        start = second / 60
        end = (second + 1) / 60
        if second == 0:
            key_times = "0;0.0165;0.0167;1"
            values = "1;1;0;0"
        elif second == 59:
            key_times = f"0;{start:.4f};{start + 0.0001:.4f};1"
            values = "0;0;1;1"
        else:
            key_times = f"0;{start:.4f};{start + 0.0001:.4f};{end:.4f};{end + 0.0001:.4f};1"
            values = "0;0;1;1;0;0"
        frames.append(
            f'<text x="{TICK_X}" y="{y}" class="terminal value" opacity="0">'
            f"{second:02d}s"
            f'<animate attributeName="opacity" dur="60s" repeatCount="indefinite" '
            f'keyTimes="{key_times}" values="{values}"/>'
            "</text>"
        )
    return "\n".join(frames)


def parse_crop_spec(spec: str) -> tuple[float, float, float, float]:
    values = [float(part.strip()) for part in spec.split(",")]
    if len(values) != 4:
        raise ValueError("crop must contain four comma-separated ratios")
    left, top, right, bottom = values
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("crop ratios must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
    return left, top, right, bottom


def profile_lines(stats: GitHubStats) -> list[tuple[str, str | None]]:
    os_label = env_or("PROFILE_OS", "macOS 26.5, Linux servers")
    kernel = env_or("PROFILE_KERNEL", "Darwin 25.5.0, zsh")
    host = env_or("PROFILE_HOST", "cloud servers + backend systems")
    focus = env_or("PROFILE_FOCUS", "backend, cloud, security")
    linkedin = env_or("PROFILE_LINKEDIN", DEFAULT_LINKEDIN)
    x_handle = env_or("PROFILE_X", DEFAULT_X)

    return [
        ("System", None),
        ("OS", os_label),
        ("Uptime", age_since_short(DATE_OF_BIRTH)),
        ("Host", host),
        ("Kernel", kernel),
        ("Focus", focus),
        ("Since", f"GitHub: {format_date(stats.created_at)}"),
        ("", ""),
        ("Work", None),
        ("Backend", "APIs, services, databases, integrations"),
        ("Cloud", "Linux servers, deployments, infra automation"),
        ("Security", "AppSec research, bug bounty, secure design"),
        ("Automation", "AI agents, scrapers, workflow tooling"),
        ("Languages", language_summary(stats)),
        ("", ""),
        ("Contact", None),
        ("GitHub", f"github.com/{stats.login}"),
        ("LinkedIn", linkedin),
        ("X", f"x.com/{x_handle.removeprefix('@')}"),
        ("", ""),
        ("GitHub Stats", None),
        ("Repos", f"{format_int(stats.public_repos)} | Stars: {format_int(stats.stars)} | Followers: {format_int(stats.followers)}"),
        ("Commits", f"{commit_summary(stats)} repo | {format_int(stats.commit_contributions)} contrib | Merged PRs: {format_int(stats.merged_pull_requests)}"),
        ("Contribs", contribution_summary(stats)),
        ("Lines of Code on GitHub", lines_summary(stats)),
    ]


def photo_to_ascii(photo: Path) -> list[str]:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    image = Image.open(photo).convert("L")
    width, height = image.size
    left, top, right, bottom = parse_crop_spec(env_or("PROFILE_PHOTO_CROP", DEFAULT_PHOTO_CROP))
    image = image.crop((
        int(width * left),
        int(height * top),
        int(width * right),
        int(height * bottom),
    ))
    image = ImageOps.autocontrast(image, cutoff=1)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=180, threshold=3))
    image = ImageEnhance.Contrast(image).enhance(1.75)
    image = ImageEnhance.Brightness(image).enhance(1.07)
    image = image.resize((ASCII_COLS, ASCII_ROWS), Image.Resampling.LANCZOS)

    ramp = "    .:-=+*#%@"
    gamma = 1.42
    rows: list[str] = []
    for y in range(ASCII_ROWS):
        chars = []
        for x in range(ASCII_COLS):
            pixel = image.getpixel((x, y))
            darkness = ((255 - pixel) / 255) ** gamma
            if darkness < 0.04:
                chars.append(" ")
                continue
            index = int(darkness * (len(ramp) - 1))
            chars.append(ramp[index])
        rows.append("".join(chars).rstrip())
    return rows


def read_ascii(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def write_ascii(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def leader(label: str, value: str) -> str:
    prefix = f"{label}: "
    dot_count = max(3, TERM_COLUMNS - len(prefix) - len(value) - 1)
    return "." * dot_count


def section_label(name: str) -> str:
    fill = "-" * max(3, TERM_COLUMNS - len(name) - 5)
    return f"- {name} {fill}"


def svg_text_lines(lines: Iterable[str], x: int, y: int) -> str:
    result = []
    for index, line in enumerate(lines):
        safe = escape_text(line)
        result.append(
            f'<tspan x="{x}" y="{y + index * ASCII_LINE_HEIGHT:.1f}">{safe}</tspan>'
        )
    return "\n".join(result)


def render_line(label: str, value: str, y: int, theme: dict[str, str]) -> str:
    dots = leader(label, value)
    if label == "Uptime":
        tick_value = f"{value} + 59s"
        dots = leader(label, tick_value)
        return (
            f'<text x="{TERM_X}" y="{y}" class="terminal">'
            f'<tspan class="label">{escape_text(label)}:</tspan> '
            f'<tspan class="muted">{dots}</tspan> '
            f'<tspan class="value">{escape_text(value)}</tspan> '
            f'<tspan class="muted">+</tspan>'
            f'<tspan class="cursor">_</tspan>'
            "</text>\n"
            f"{animated_seconds(y)}"
        )
    if label == "Lines of Code on GitHub" and " (" in value and "++, " in value and "--)" in value:
        net, rest = value.split(" (", 1)
        additions, deletions = rest.removesuffix(")").split(", ", 1)
        return (
            f'<text x="{TERM_X}" y="{y}" class="terminal">'
            f'<tspan class="label">{escape_text(label)}:</tspan> '
            f'<tspan class="muted">{dots}</tspan> '
            f'<tspan class="value">{escape_text(net)}</tspan> '
            f'<tspan class="muted">(</tspan>'
            f'<tspan class="green">{escape_text(additions)}</tspan>'
            f'<tspan class="muted">, </tspan>'
            f'<tspan class="red">{escape_text(deletions)}</tspan>'
            f'<tspan class="muted">)</tspan>'
            "</text>"
        )
    return (
        f'<text x="{TERM_X}" y="{y}" class="terminal">'
        f'<tspan class="label">{escape_text(label)}:</tspan> '
        f'<tspan class="muted">{dots}</tspan> '
        f'<tspan class="value">{escape_text(value)}</tspan>'
        "</text>"
    )


def terminal_lines(stats: GitHubStats, theme: dict[str, str]) -> str:
    y = TERM_Y
    header_user = (stats.name.split()[0] if stats.name else "rahul").lower()
    header_host = stats.login.lower()
    parts = [
        f'<text x="{TERM_X}" y="{y}" class="terminal title">'
        f'{escape_text(header_user)}@{escape_text(header_host)} <tspan class="muted">{"-" * 27}</tspan>'
        "</text>"
    ]
    y += TERM_LINE_HEIGHT + 12

    for label, value in profile_lines(stats):
        if label == "" and value == "":
            y += TERM_LINE_HEIGHT // 2
            continue
        if value is None:
            parts.append(
                f'<text x="{TERM_X}" y="{y}" class="terminal muted">'
                f"{escape_text(section_label(label))}</text>"
            )
            y += TERM_LINE_HEIGHT
            continue

        parts.append(render_line(label, value, y, theme))
        y += TERM_LINE_HEIGHT

    return "\n".join(parts)


def build_svg(ascii_lines: list[str], stats: GitHubStats, theme: dict[str, str]) -> str:
    ascii_spans = svg_text_lines(ascii_lines, 70, 72)
    title = f"{stats.name} GitHub profile card"
    return f'''<svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{escape_text(title)}</title>
  <desc id="desc">A terminal-style GitHub profile card with ASCII art generated from Rahul R M's photo.</desc>
  <style>
    .ascii {{
      fill: {theme["ascii"]};
      font: {ASCII_FONT_SIZE}px "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      white-space: pre;
    }}
    .terminal {{
      font: 700 {TERM_FONT_SIZE}px "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      letter-spacing: 0;
    }}
    .title {{ fill: {theme["title"]}; }}
    .muted {{ fill: {theme["muted"]}; }}
    .label {{ fill: {theme["label"]}; }}
    .value {{ fill: {theme["value"]}; }}
    .green {{ fill: {theme["green"]}; }}
    .red {{ fill: {theme["red"]}; }}
    .cursor {{
      fill: {theme["value"]};
      animation: blink 1s steps(2, start) infinite;
    }}
    @keyframes blink {{
      50% {{ opacity: 0; }}
    }}
  </style>
  <rect width="{WIDTH}" height="{HEIGHT}" rx="18" fill="{theme["canvas"]}"/>
  <rect x="24" y="24" width="{WIDTH - 48}" height="{HEIGHT - 48}" rx="18" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <text class="ascii" xml:space="preserve">
{ascii_spans}
  </text>
  {terminal_lines(stats, theme)}
</svg>
'''


def build(ascii_lines: list[str], stats: GitHubStats) -> None:
    for theme in THEMES.values():
        (ROOT / theme["file"]).write_text(build_svg(ascii_lines, stats, theme), encoding="utf-8")


def load_ascii(args: argparse.Namespace) -> list[str]:
    if args.ascii:
        return read_ascii(args.ascii.expanduser().resolve())

    photo_arg = args.photo_option or args.photo
    if photo_arg:
        ascii_lines = photo_to_ascii(photo_arg.expanduser().resolve())
        if args.write_ascii:
            write_ascii(args.write_ascii.expanduser().resolve(), ascii_lines)
        return ascii_lines

    if DEFAULT_ASCII.exists():
        return read_ascii(DEFAULT_ASCII)

    raise SystemExit("Provide --ascii, --photo, or create assets/profile_ascii.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", nargs="?", type=Path, help="Photo to convert into ASCII art")
    parser.add_argument("--photo", dest="photo_option", type=Path, help="Photo to convert into ASCII art")
    parser.add_argument("--ascii", type=Path, help="Prebuilt ASCII art file")
    parser.add_argument("--write-ascii", type=Path, help="Write generated ASCII art to this file")
    parser.add_argument("--login", default=env_or("PROFILE_LOGIN", DEFAULT_LOGIN), help="GitHub login to render")
    parser.add_argument("--stats-cache", type=Path, default=DEFAULT_STATS_CACHE, help="Per-repo line stats cache")
    parser.add_argument("--refresh-line-stats", action="store_true", help="Refresh every repo's line stats")
    args = parser.parse_args()

    ascii_lines = load_ascii(args)
    stats = fetch_github_stats(
        args.login,
        args.stats_cache.expanduser().resolve(),
        args.refresh_line_stats,
    )
    build(ascii_lines, stats)


if __name__ == "__main__":
    main()
