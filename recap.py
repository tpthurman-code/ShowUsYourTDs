#!/usr/bin/env python3
"""Build and email a weekly recap for a Sleeper fantasy football league.

Uses only the Python standard library. Configuration comes from environment
variables (see README.md):

    SLEEPER_LEAGUE_ID   required
    RECAP_WEEK          optional, recap this week instead of auto-detecting
    EMAIL_TO            comma-separated recipients (required unless DRY_RUN)
    EMAIL_FROM          defaults to SMTP_USERNAME
    SMTP_HOST           defaults to smtp.gmail.com
    SMTP_PORT           defaults to 465 (implicit TLS); 587 uses STARTTLS
    SMTP_USERNAME       required unless DRY_RUN
    SMTP_PASSWORD       required unless DRY_RUN
    DRY_RUN             "1"/"true" writes the email to OUTPUT_DIR instead of sending
    OUTPUT_DIR          defaults to "out"
"""

from __future__ import annotations

import html
import json
import os
import random
import smtplib
import ssl
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

API = "https://api.sleeper.app/v1"

# Trash talk. One line is picked at random from each list; the choice is
# seeded by league/season/week so re-running a week gives the same roasts.
ROASTS = {
    "intro": [
        "Another week, another round of questionable lineup decisions. Here's the damage.",
        "The scores are final and the excuses are already rolling in.",
        "Week {week} is in the books. Some of you managed. Some of you just clicked buttons.",
        "Grab a victory cigar or a box of tissues. Week {week} results are in.",
    ],
    "game_tie": [
        "{w} and {l} tied. Nobody wins, everybody sulks.",
        "A tie. Both of you should think about what you've done.",
    ],
    "game_close": [
        "{l} lost by {m}. That's one extra point. Think about it all week.",
        "{w} survived by {m}. Don't get cocky.",
        "Decided by {m}. {l} will be refreshing stat corrections until Thursday.",
    ],
    "game_blowout": [
        "{w} won by {m}. {l}, blink twice if you need help.",
        "A {m}-point beatdown. {l} never got off the bus.",
        "{l} got flattened by {m}. Somebody get the license plate.",
    ],
    "game_normal": [
        "{w} handled business. {l}, maybe try a better lineup next week.",
        "{w} takes it. {l} gets a whole week to think about it.",
        "Clean win for {w}. No excuses, {l}.",
    ],
    "top": [
        "{team} dropped {pts}. Leave some points for the rest of the league.",
        "{team} put up {pts} and will be unbearable in the group chat all week.",
    ],
    "low": [
        "{team} managed {pts}. Did you set a lineup or just close your eyes and tap?",
        "{team} scored {pts}. Bold of you to show up at all.",
        "{team} put up {pts}. Rock bottom has a basement, apparently.",
    ],
    "blowout": [
        "{w} beat {l} by {m}. Somebody check on {l}.",
        "{w} beat {l} by {m}. That wasn't a matchup, it was a hostage situation.",
    ],
    "nail": [
        "{w} edged {l} by {m}. {l}, that one's going to sting.",
        "{w} beat {l} by {m}. Somewhere, {l} is staring at a bench player.",
    ],
    "robbed": [
        "{team} scored {pts} and still lost. Life comes at you fast.",
        "{team} put up {pts} and took an L anyway. Brutal.",
    ],
    "stolen": [
        "{team} won with just {pts}. Didn't earn it, still counts.",
        "{team} squeaked out a win with {pts}. Thank your opponent's lineup.",
    ],
    "player": [
        "{player} put up {pts} for {team}. You're welcome, {team}.",
        "{player} dropped {pts} for {team}, who will absolutely take all the credit.",
    ],
    "bench": [
        "{team} left {player} on the bench for {pts}. Bold strategy.",
        "{team} benched {player}, who scored {pts}. The start/sit gods are laughing.",
    ],
    "first": [
        "{team} sits on top. Enjoy it while it lasts.",
        "{team} leads the league. Everyone else, you know who to target.",
    ],
    "last": [
        "{team} is propping up the whole table from the bottom. Thanks for your service.",
        "{team} is in last. Every trade offer is now officially a cry for help.",
    ],
}


def roast(rng: random.Random, key: str, **kw) -> str:
    return rng.choice(ROASTS[key]).format(**kw)


def fetch(path: str):
    req = urllib.request.Request(f"{API}{path}", headers={"User-Agent": "weekly-recap"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class TeamWeek:
    roster_id: int
    name: str
    points: float
    starters: list[tuple[str, float]] = field(default_factory=list)  # (player_id, pts)
    bench: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Game:
    home: TeamWeek
    away: TeamWeek
    quip: str = ""

    @property
    def winner(self) -> TeamWeek | None:
        if self.home.points == self.away.points:
            return None
        return self.home if self.home.points > self.away.points else self.away

    @property
    def loser(self) -> TeamWeek | None:
        w = self.winner
        if w is None:
            return None
        return self.away if w is self.home else self.home

    @property
    def margin(self) -> float:
        return abs(self.home.points - self.away.points)


@dataclass
class Standing:
    name: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


@dataclass
class Recap:
    league_name: str
    season: str
    week: int
    intro: str
    games: list[Game]
    standings: list[Standing]
    standings_note: str
    awards: list[tuple[str, str]]  # (title, description)
    transactions: list[str]


# --------------------------------------------------------------------------- #
# Building the recap
# --------------------------------------------------------------------------- #


def team_names(users: list[dict], rosters: list[dict]) -> dict[int, str]:
    by_user = {}
    for u in users:
        meta = u.get("metadata") or {}
        by_user[u["user_id"]] = meta.get("team_name") or u.get("display_name") or "Unknown"
    return {
        r["roster_id"]: by_user.get(r.get("owner_id"), f"Team {r['roster_id']}")
        for r in rosters
    }


def player_name(players: dict, pid: str) -> str:
    p = players.get(pid)
    if not p:
        return pid  # team defenses are keyed by team abbreviation, e.g. "KC"
    full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    pos = p.get("position") or ""
    team = p.get("team") or "FA"
    return f"{full} ({pos}, {team})" if pos else full


def build_team_weeks(matchups: list[dict], names: dict[int, str]) -> list[tuple[int | None, TeamWeek]]:
    out = []
    for m in matchups:
        starters = [s for s in (m.get("starters") or []) if s and s != "0"]
        pts = m.get("players_points") or {}
        starter_set = set(starters)
        tw = TeamWeek(
            roster_id=m["roster_id"],
            name=names.get(m["roster_id"], f"Team {m['roster_id']}"),
            points=float(m.get("points") or 0),
            starters=[(p, float(pts.get(p, 0))) for p in starters],
            bench=[(p, float(pts.get(p, 0))) for p in (m.get("players") or []) if p not in starter_set],
        )
        out.append((m.get("matchup_id"), tw))
    return out


def pair_games(team_weeks: list[tuple[int | None, TeamWeek]]) -> list[Game]:
    grouped: dict[int, list[TeamWeek]] = defaultdict(list)
    for mid, tw in team_weeks:
        if mid is not None:
            grouped[mid].append(tw)
    games = [Game(ts[0], ts[1]) for mid, ts in sorted(grouped.items()) if len(ts) == 2]
    return games


def build_standings(rosters: list[dict], names: dict[int, str]) -> list[Standing]:
    rows = []
    for r in rosters:
        s = r.get("settings") or {}
        pf = s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100
        pa = s.get("fpts_against", 0) + s.get("fpts_against_decimal", 0) / 100
        rows.append(
            Standing(
                name=names[r["roster_id"]],
                wins=s.get("wins", 0),
                losses=s.get("losses", 0),
                ties=s.get("ties", 0),
                points_for=pf,
                points_against=pa,
            )
        )
    rows.sort(key=lambda x: (x.wins + 0.5 * x.ties, x.points_for), reverse=True)
    return rows


def build_awards(
    team_weeks: list[TeamWeek], games: list[Game], players: dict, rng: random.Random
) -> list[tuple[str, str]]:
    awards: list[tuple[str, str]] = []
    if not team_weeks:
        return awards

    top = max(team_weeks, key=lambda t: t.points)
    low = min(team_weeks, key=lambda t: t.points)
    awards.append(("Top Score", roast(rng, "top", team=top.name, pts=f"{top.points:.2f}")))
    awards.append(("Basement Dweller", roast(rng, "low", team=low.name, pts=f"{low.points:.2f}")))

    decided = [g for g in games if g.winner]
    if decided:
        blowout = max(decided, key=lambda g: g.margin)
        close = min(decided, key=lambda g: g.margin)
        awards.append((
            "Biggest Blowout",
            roast(rng, "blowout", w=blowout.winner.name, l=blowout.loser.name, m=f"{blowout.margin:.2f}"),
        ))
        awards.append((
            "Nail-Biter",
            roast(rng, "nail", w=close.winner.name, l=close.loser.name, m=f"{close.margin:.2f}"),
        ))
    if len(decided) > 1:
        robbed = max((g.loser for g in decided), key=lambda t: t.points)
        stolen = min((g.winner for g in decided), key=lambda t: t.points)
        awards.append(("Robbed", roast(rng, "robbed", team=robbed.name, pts=f"{robbed.points:.2f}")))
        awards.append(("Stolen Win", roast(rng, "stolen", team=stolen.name, pts=f"{stolen.points:.2f}")))

    starters = [(t, pid, pts) for t in team_weeks for pid, pts in t.starters]
    if starters:
        t, pid, pts = max(starters, key=lambda x: x[2])
        awards.append((
            "Player of the Week",
            roast(rng, "player", player=player_name(players, pid), pts=f"{pts:.2f}", team=t.name),
        ))

    bench = [(t, pid, pts) for t in team_weeks for pid, pts in t.bench]
    if bench:
        t, pid, pts = max(bench, key=lambda x: x[2])
        if pts > 0:
            awards.append((
                "Bench Blunder",
                roast(rng, "bench", team=t.name, player=player_name(players, pid), pts=f"{pts:.2f}"),
            ))

    return awards


def game_quip(g: Game, rng: random.Random) -> str:
    if g.winner is None:
        return roast(rng, "game_tie", w=g.home.name, l=g.away.name)
    kind = "close" if g.margin < 5 else "blowout" if g.margin >= 40 else "normal"
    return roast(rng, f"game_{kind}", w=g.winner.name, l=g.loser.name, m=f"{g.margin:.2f}")


def standings_note(standings: list[Standing], rng: random.Random) -> str:
    if len(standings) < 2:
        return ""
    return " ".join([
        roast(rng, "first", team=standings[0].name),
        roast(rng, "last", team=standings[-1].name),
    ])


def describe_transactions(txns: list[dict], names: dict[int, str], players: dict) -> list[str]:
    lines = []
    for t in sorted(txns, key=lambda x: x.get("status_updated") or 0):
        if t.get("status") != "complete":
            continue
        kind = t.get("type")
        adds = t.get("adds") or {}
        drops = t.get("drops") or {}
        if kind == "trade":
            parts = []
            for rid in t.get("roster_ids") or []:
                got = [player_name(players, p) for p, r in adds.items() if r == rid]
                picks = [
                    f"{pk['season']} Rd {pk['round']} pick"
                    for pk in (t.get("draft_picks") or [])
                    if pk.get("owner_id") == rid
                ]
                received = got + picks
                if received:
                    parts.append(f"{names.get(rid, rid)} gets {', '.join(received)}")
            if parts:
                lines.append("Trade: " + "; ".join(parts))
        elif kind in ("waiver", "free_agent"):
            rid = (t.get("roster_ids") or [None])[0]
            team = names.get(rid, rid)
            bits = []
            if adds:
                bits.append("added " + ", ".join(player_name(players, p) for p in adds))
            if drops:
                bits.append("dropped " + ", ".join(player_name(players, p) for p in drops))
            if bits:
                bid = (t.get("settings") or {}).get("waiver_bid")
                suffix = f" (${bid} FAAB)" if kind == "waiver" and bid else ""
                lines.append(f"{team} {' and '.join(bits)}{suffix}")
    return lines


def detect_week(state: dict) -> int | None:
    """Return the last fully completed week.

    Sleeper moves its current week forward midweek, so by Thursday the current
    week is the one about to kick off and the week before it is complete. This
    stays correct even if the scheduled run is delayed past Thursday kickoff.
    """
    if state.get("season_type") not in ("regular", "post"):
        return None
    week = int(state.get("week") or 0) - 1
    return week if week >= 1 else None


def build_recap(league: dict, users, rosters, matchups, txns, players, week: int) -> Recap:
    rng = random.Random(f"{league.get('league_id')}-{league.get('season')}-{week}")
    names = team_names(users, rosters)
    tws = build_team_weeks(matchups, names)
    games = pair_games(tws)
    for g in games:
        g.quip = game_quip(g, rng)
    standings = build_standings(rosters, names)
    return Recap(
        league_name=league.get("name", "League"),
        season=str(league.get("season", "")),
        week=week,
        intro=roast(rng, "intro", week=week),
        games=games,
        standings=standings,
        standings_note=standings_note(standings, rng),
        awards=build_awards([tw for _, tw in tws], games, players, rng),
        transactions=describe_transactions(txns, names, players),
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_text(r: Recap) -> str:
    out = [f"{r.league_name} - Week {r.week} Recap ({r.season})", "", r.intro, ""]
    out.append("RESULTS")
    for g in r.games:
        w, l = (g.winner, g.loser) if g.winner else (g.home, g.away)
        verb = "def." if g.winner else "tied"
        out.append(f"  {w.name} {w.points:.2f} {verb} {l.name} {l.points:.2f}")
        out.append(f"    {g.quip}")
    if r.awards:
        out += ["", "AWARDS"]
        out += [f"  {title}: {desc}" for title, desc in r.awards]
    out += ["", "STANDINGS"]
    for i, s in enumerate(r.standings, 1):
        rec = f"{s.wins}-{s.losses}" + (f"-{s.ties}" if s.ties else "")
        out.append(f"  {i:>2}. {s.name} ({rec})  PF {s.points_for:.2f}  PA {s.points_against:.2f}")
    if r.standings_note:
        out.append(f"  {r.standings_note}")
    if r.transactions:
        out += ["", "TRANSACTIONS"]
        out += [f"  - {t}" for t in r.transactions]
    return "\n".join(out) + "\n"


def render_html(r: Recap) -> str:
    e = html.escape
    td = 'style="padding:6px 10px;border-bottom:1px solid #e5e7eb"'
    tdr = 'style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:right"'
    th = 'style="padding:6px 10px;text-align:left;border-bottom:2px solid #111827"'
    thr = 'style="padding:6px 10px;text-align:right;border-bottom:2px solid #111827"'
    h2 = 'style="font-size:18px;margin:28px 0 8px"'

    games = []
    for g in r.games:
        w, l = (g.winner, g.loser) if g.winner else (g.home, g.away)
        games.append(
            f"<tr><td {td}><b>{e(w.name)}</b></td><td {tdr}><b>{w.points:.2f}</b></td>"
            f"<td {td}>{e(l.name)}</td><td {tdr}>{l.points:.2f}</td></tr>"
            f'<tr><td colspan="4" style="padding:0 10px 10px;color:#6b7280;font-style:italic;'
            f'border-bottom:1px solid #e5e7eb">{e(g.quip)}</td></tr>'
        )

    awards = "".join(f"<li style=\"margin:4px 0\"><b>{e(t)}:</b> {e(d)}</li>" for t, d in r.awards)

    standings = []
    for i, s in enumerate(r.standings, 1):
        rec = f"{s.wins}-{s.losses}" + (f"-{s.ties}" if s.ties else "")
        standings.append(
            f"<tr><td {td}>{i}</td><td {td}>{e(s.name)}</td><td {tdr}>{rec}</td>"
            f"<td {tdr}>{s.points_for:.2f}</td><td {tdr}>{s.points_against:.2f}</td></tr>"
        )

    txns = "".join(f"<li style=\"margin:4px 0\">{e(t)}</li>" for t in r.transactions)

    parts = [
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'max-width:640px;margin:0 auto;color:#111827">',
        f'<h1 style="font-size:24px;margin:0 0 4px">{e(r.league_name)}</h1>',
        f'<div style="color:#6b7280">Week {r.week} Recap &middot; {e(r.season)} season</div>',
        f'<p style="margin:16px 0 0">{e(r.intro)}</p>',
        f"<h2 {h2}>Results</h2>",
        f'<table style="border-collapse:collapse;width:100%"><tr><th {th}>Winner</th><th {thr}></th>'
        f"<th {th}>Loser</th><th {thr}></th></tr>{''.join(games)}</table>",
    ]
    if awards:
        parts += [f"<h2 {h2}>Awards</h2>", f'<ul style="padding-left:20px">{awards}</ul>']
    parts += [
        f"<h2 {h2}>Standings</h2>",
        f'<table style="border-collapse:collapse;width:100%"><tr><th {th}>#</th><th {th}>Team</th>'
        f"<th {thr}>Record</th><th {thr}>PF</th><th {thr}>PA</th></tr>{''.join(standings)}</table>",
    ]
    if r.standings_note:
        parts.append(f'<p style="margin:10px 0 0;color:#6b7280;font-style:italic">{e(r.standings_note)}</p>')
    if txns:
        parts += [f"<h2 {h2}>Transactions</h2>", f'<ul style="padding-left:20px">{txns}</ul>']
    parts.append("</div>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


def send_email(subject: str, text: str, html_body: str) -> None:
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    user = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("EMAIL_FROM") or user
    recipients = [a.strip() for a in os.environ["EMAIL_TO"].split(",") if a.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = sender
    msg["Bcc"] = ", ".join(recipients)  # keep league members' addresses private
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)


def main() -> int:
    league_id = os.environ.get("SLEEPER_LEAGUE_ID", "").strip()
    if not league_id:
        print("SLEEPER_LEAGUE_ID is not set", file=sys.stderr)
        return 1
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

    league = fetch(f"/league/{league_id}")
    if (os.environ.get("RECAP_WEEK") or "").strip():
        week = int(os.environ["RECAP_WEEK"])
    else:
        week = detect_week(fetch("/state/nfl"))
        if week is None:
            print("No completed week to recap (offseason or preseason). Nothing sent.")
            return 0

    print(f"Building recap for {league.get('name')} week {week}")
    recap = build_recap(
        league,
        fetch(f"/league/{league_id}/users"),
        fetch(f"/league/{league_id}/rosters"),
        fetch(f"/league/{league_id}/matchups/{week}") or [],
        fetch(f"/league/{league_id}/transactions/{week}") or [],
        fetch("/players/nfl"),
        week,
    )

    subject = f"{recap.league_name}: Week {week} Recap"
    text, html_body = render_text(recap), render_html(recap)

    out_dir = Path(os.environ.get("OUTPUT_DIR") or "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recap.txt").write_text(text)
    (out_dir / "recap.html").write_text(html_body)
    print(text)

    if dry_run:
        print(f"DRY_RUN set; wrote recap to {out_dir}/ and skipped sending.")
        return 0
    send_email(subject, text, html_body)
    print("Email sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
