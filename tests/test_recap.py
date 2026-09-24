import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import recap  # noqa: E402

LEAGUE = {"name": "Show Us Your TDs", "season": "2026"}
USERS = [
    {"user_id": "u1", "display_name": "alice", "metadata": {"team_name": "Alice's Aces"}},
    {"user_id": "u2", "display_name": "bob", "metadata": {}},
    {"user_id": "u3", "display_name": "cara"},
    {"user_id": "u4", "display_name": "dan"},
]
ROSTERS = [
    {"roster_id": 1, "owner_id": "u1", "settings": {"wins": 2, "losses": 1, "fpts": 350, "fpts_decimal": 50}},
    {"roster_id": 2, "owner_id": "u2", "settings": {"wins": 1, "losses": 2, "fpts": 300, "fpts_decimal": 0}},
    {"roster_id": 3, "owner_id": "u3", "settings": {"wins": 3, "losses": 0, "fpts": 400, "fpts_decimal": 25}},
    {"roster_id": 4, "owner_id": "u4", "settings": {"wins": 0, "losses": 3, "fpts": 280, "fpts_decimal": 10}},
]
MATCHUPS = [
    {"roster_id": 1, "matchup_id": 1, "points": 120.5, "starters": ["p1", "0"], "players": ["p1", "p2"],
     "players_points": {"p1": 30.2, "p2": 25.0}},
    {"roster_id": 2, "matchup_id": 1, "points": 118.0, "starters": ["p3"], "players": ["p3"],
     "players_points": {"p3": 18.0}},
    {"roster_id": 3, "matchup_id": 2, "points": 150.0, "starters": ["KC"], "players": ["KC"],
     "players_points": {"KC": 12.0}},
    {"roster_id": 4, "matchup_id": 2, "points": 80.0, "starters": ["p4"], "players": ["p4"],
     "players_points": {"p4": 8.0}},
]
TXNS = [
    {"type": "waiver", "status": "complete", "roster_ids": [2], "adds": {"p5": 2}, "drops": {"p6": 2},
     "settings": {"waiver_bid": 12}, "status_updated": 1},
    {"type": "trade", "status": "complete", "roster_ids": [1, 3], "adds": {"p2": 3, "p7": 1},
     "draft_picks": [{"season": "2027", "round": 2, "owner_id": 1}], "status_updated": 2},
    {"type": "free_agent", "status": "failed", "roster_ids": [4], "adds": {"p8": 4}},
]
PLAYERS = {
    "p1": {"full_name": "Star Back", "position": "RB", "team": "SF"},
    "p2": {"full_name": "Bench Guy", "position": "WR", "team": "DAL"},
    "p5": {"first_name": "Waiver", "last_name": "Pickup", "position": "TE", "team": None},
    "p6": {"full_name": "Cut Man", "position": "K", "team": "NYJ"},
    "p7": {"full_name": "Trade Chip", "position": "QB", "team": "BUF"},
}


class RecapTest(unittest.TestCase):
    def setUp(self):
        self.r = recap.build_recap(LEAGUE, USERS, ROSTERS, MATCHUPS, TXNS, PLAYERS, 3)

    def test_games(self):
        self.assertEqual(len(self.r.games), 2)
        g = self.r.games[0]
        self.assertEqual(g.winner.name, "Alice's Aces")
        self.assertEqual(g.loser.name, "bob")
        self.assertAlmostEqual(g.margin, 2.5)
        # empty "0" starter slot is ignored
        self.assertEqual([p for p, _ in g.home.starters], ["p1"])

    def test_standings(self):
        self.assertEqual([s.name for s in self.r.standings], ["cara", "Alice's Aces", "bob", "dan"])
        self.assertAlmostEqual(self.r.standings[1].points_for, 350.5)

    def test_awards(self):
        a = dict(self.r.awards)
        self.assertIn("cara", a["Top Score"])
        self.assertIn("150.00", a["Top Score"])
        self.assertIn("dan", a["Basement Dweller"])
        self.assertIn("80.00", a["Basement Dweller"])
        self.assertIn("70.00", a["Biggest Blowout"])
        self.assertIn("2.50", a["Nail-Biter"])
        self.assertIn("bob", a["Robbed"])
        self.assertIn("118.00", a["Robbed"])
        self.assertIn("Alice's Aces", a["Stolen Win"])
        self.assertIn("Star Back (RB, SF)", a["Player of the Week"])
        self.assertIn("30.20", a["Player of the Week"])
        self.assertIn("Bench Guy (WR, DAL)", a["Bench Blunder"])

    def test_roasts(self):
        close, blowout = self.r.games
        self.assertIn(close.quip, [q.format(w="Alice's Aces", l="bob", m="2.50") for q in recap.ROASTS["game_close"]])
        self.assertIn(blowout.quip, [q.format(w="cara", l="dan", m="70.00") for q in recap.ROASTS["game_blowout"]])
        self.assertIn("cara", self.r.standings_note)
        self.assertIn("dan", self.r.standings_note)
        # same league/week always produces the same roasts
        again = recap.build_recap(LEAGUE, USERS, ROSTERS, MATCHUPS, TXNS, PLAYERS, 3)
        self.assertEqual(recap.render_text(again), recap.render_text(self.r))

    def test_every_roast_template_formats(self):
        kw = dict(week=1, w="W", l="L", m="1.00", team="T", pts="1.00", player="P")
        for key, lines in recap.ROASTS.items():
            for line in lines:
                line.format(**kw)

    def test_transactions(self):
        t = self.r.transactions
        self.assertEqual(len(t), 2)  # failed transaction skipped
        self.assertEqual(t[0], "bob added Waiver Pickup (TE, FA) and dropped Cut Man (K, NYJ) ($12 FAAB)")
        self.assertIn("Alice's Aces gets Trade Chip (QB, BUF), 2027 Rd 2 pick", t[1])
        self.assertIn("cara gets Bench Guy (WR, DAL)", t[1])

    def test_render(self):
        text = recap.render_text(self.r)
        self.assertIn("Week 3 Recap", text)
        self.assertIn("Alice's Aces 120.50 def. bob 118.00", text)
        html_out = recap.render_html(self.r)
        self.assertIn("Alice&#x27;s Aces", html_out)

    def test_detect_week_is_previous_week(self):
        self.assertEqual(recap.detect_week({"season_type": "regular", "week": 4}), 3)
        self.assertIsNone(recap.detect_week({"season_type": "regular", "week": 1}))
        self.assertIsNone(recap.detect_week({"season_type": "off", "week": 0}))
        self.assertIsNone(recap.detect_week({"season_type": "pre", "week": 2}))


if __name__ == "__main__":
    unittest.main()
