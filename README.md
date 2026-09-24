# ShowUsYourTDs

A GitHub Action emails a weekly recap of our Sleeper fantasy football league every Thursday at 4:35pm Pacific, covering the week that ended Monday night.

Each recap includes:

- **Results**: every matchup's winner, loser and score, each with a line of trash talk
- **Awards**: top score, lowest score, biggest blowout, closest game, highest-scoring loser, lowest-scoring winner,
  player of the week, and the best player left on a bench
- **Standings**: record, points for and points against
- **Transactions**: waiver claims (with FAAB bids), free-agent moves and trades

## Setup

1. **Find your league ID.** Open your league on sleeper.com. The long number in the URL is the ID
   (`https://sleeper.com/leagues/<LEAGUE_ID>/...`).

2. **Get an SMTP password.** For Gmail, turn on 2-Step Verification, then create an
   [App Password](https://myaccount.google.com/apppasswords). Use the 16-character app password, not your normal password.

3. **Add repository secrets.** Go to **Settings → Secrets and variables → Actions → New repository secret**:

   | Secret              | Required | Example / default                         |
   | ------------------- | -------- | ----------------------------------------- |
   | `SLEEPER_LEAGUE_ID` | yes      | `1048293847561234432`                     |
   | `SMTP_USERNAME`     | yes      | `you@gmail.com`                           |
   | `SMTP_PASSWORD`     | yes      | your Gmail app password                   |
   | `EMAIL_TO`          | yes      | `a@example.com, b@example.com` (sent BCC) |
   | `EMAIL_FROM`        | no       | defaults to `SMTP_USERNAME`               |
   | `SMTP_HOST`         | no       | defaults to `smtp.gmail.com`              |
   | `SMTP_PORT`         | no       | defaults to `465`; use `587` for STARTTLS |

4. **Test it.** Go to **Actions → Weekly Sleeper Recap → Run workflow**. Tick **dry run** to build the recap
   without sending it; you can download the output from the run's `recap` artifact. You can also enter a specific week.

## Trash talk

The recap roasts the league a little. The lines are in the `ROASTS` dictionary at the top of `recap.py`. Add, edit
or delete lines there to change the tone. Each line can use placeholders such as `{team}`, `{pts}`, `{w}` (winner),
`{l}` (loser) and `{m}` (margin). A test checks that every line formats. Lines are picked at random but seeded by
league and week, so re-running the same week gives the same email.

## Schedule

The workflow runs Thursdays at 4:35pm Pacific, all year round. GitHub cron only uses UTC and ignores daylight saving
time, so `.github/workflows/weekly-recap.yml` lists both UTC times (23:35 Thursday for PDT, 00:35 Friday for PST).
The "Check send time" step skips whichever one doesn't match Pacific time that day. To change the time, update both
`cron` lines and the matching strings in that step.

The recap always covers the last completed week (Sleeper's current week minus one). A run that GitHub delays past
Thursday Night Football kickoff still recaps the right week.

If no week needs a recap (offseason or preseason), the job exits without sending anything.

> GitHub turns off scheduled workflows in a repository that has had no activity for 60 days. If that happens,
> re-enable the workflow from the Actions tab before the season starts.

## Running locally

```sh
SLEEPER_LEAGUE_ID=... DRY_RUN=1 python3 recap.py   # writes out/recap.html and out/recap.txt
python3 -m unittest discover -s tests               # run the tests
```

There are no dependencies beyond the Python 3.10+ standard library.
