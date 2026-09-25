# ShowUsYourTDs

A GitHub Action emails a weekly recap (and optionally posts it to GroupMe) of our Sleeper fantasy football league every Tuesday at 8:00am Pacific, covering the week that ended Monday night.

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
   | `GROUPME_BOT_ID`    | no       | see step 4                                |
   | `EMAIL_FROM`        | no       | defaults to `SMTP_USERNAME`               |
   | `SMTP_HOST`         | no       | defaults to `smtp.gmail.com`              |
   | `SMTP_PORT`         | no       | defaults to `465`; use `587` for STARTTLS |

4. **Optional: post to GroupMe.** Sign in at [dev.groupme.com](https://dev.groupme.com/bots) with your GroupMe
   account, then click **Bots → Create Bot**. Pick the league group, give the bot a name (and an avatar image URL
   if you like), and leave the callback URL blank. Copy the **Bot ID** into a secret named `GROUPME_BOT_ID`.
   The chat gets a shorter version of the recap (results, awards, standings) across a few messages. GroupMe
   caps each message at 1,000 characters.

5. **Test it.** Go to **Actions → Weekly Sleeper Recap → Run workflow**. Tick **dry run** to build the recap
   without sending it; you can download the output (including `groupme.txt`) from the run's `recap` artifact. You
   can also enter a specific week, and use **channels** to send to only email or only GroupMe.

## A second league

The workflow runs each league as its own job: **Show Us Your TD's** (league 1) and **Sunday Fundays** (league 2).
League 2 uses the same secrets with a `_2` suffix:

| Secret                | For league 2                                            |
| --------------------- | ------------------------------------------------------- |
| `SLEEPER_LEAGUE_ID_2` | the second league's ID (league 2 is skipped until set)  |
| `EMAIL_TO_2`          | that league's recipients (leave unset for no email)     |
| `GROUPME_BOT_ID_2`    | a bot created in that league's GroupMe group (optional) |

The Gmail sender (`SMTP_USERNAME` / `SMTP_PASSWORD`) is shared. On manual runs, the **league** input picks one
league or both. To add a third league, add a row to the `matrix` in the workflow with its name and suffix `_3`, and add the
same name to the `league` input options.

## Trash talk

The recap roasts the league a little. The lines are in the `ROASTS` dictionary at the top of `recap.py`. Add, edit
or delete lines there to change the tone. Each line can use placeholders such as `{team}`, `{pts}`, `{w}` (winner),
`{l}` (loser) and `{m}` (margin). A test checks that every line formats. Lines are picked at random but seeded by
league and week, so re-running the same week gives the same email.

## Schedule

The workflow runs Tuesdays at 8:00am Pacific, all year round. GitHub cron only uses UTC and ignores daylight saving
time, so `.github/workflows/weekly-recap.yml` lists both UTC times (15:00 for PDT, 16:00 for PST). The "Check whether
to run" step skips whichever one doesn't match Pacific time that day. To change the time, update both `cron` lines and
the matching strings in that step. GitHub runs scheduled jobs a little late when it's busy, so expect the recap
a few minutes after 8.

The recap covers the last completed week. On Tuesday and Wednesday that's Sleeper's current week if it has scores
(Sleeper hasn't moved on yet), otherwise the week before. From Thursday to Monday it's always the week before the
one being played.

If no week needs a recap (offseason or preseason), the job exits without sending anything.

> GitHub turns off scheduled workflows in a repository that has had no activity for 60 days. If that happens,
> re-enable the workflow from the Actions tab before the season starts.

## Running locally

```sh
SLEEPER_LEAGUE_ID=... DRY_RUN=1 python3 recap.py   # writes out/recap.html and out/recap.txt
python3 -m unittest discover -s tests               # run the tests
```

There are no dependencies beyond the Python 3.10+ standard library.
