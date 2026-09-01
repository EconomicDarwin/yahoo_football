# Setup walkthrough

One-time setup to connect this repo to your Yahoo account. Budget 10 minutes.

There is a checker that verifies each stage, so you never have to guess whether
a step worked:

```powershell
.\.venv\Scripts\python.exe -m ffball.doctor
```

Run it whenever you want. It only reports; it never changes anything.

---

## Step 0 â€” Open the right terminal

Open **Windows PowerShell** (not through Claude â€” step 3 needs a real
interactive prompt) and go to the project:

```powershell
cd C:\Users\micha\Documents\github\personal\fantasy_football
```

Confirm the tooling is healthy before touching Yahoo:

```powershell
.\.venv\Scripts\python.exe -m ffball.doctor
```

Expect green on Python, yfpy, and the venv, and a red `.env exists` â€” that is
correct at this stage, it's what step 2 creates.

---

## Step 1 â€” Create the Yahoo app

> **The form changed in 2025 and most guides online (including yfpy's own docs)
> are out of date.** There is no longer an "Installed Application" radio
> button, and â€” importantly â€” **there is no Fantasy Sports checkbox under API
> Permissions**. Yahoo moved Fantasy Sports access behind a separate approval
> process. See "Fantasy Sports API access" below.

Go to **<https://developer.yahoo.com/apps/create/>** signed in as the Yahoo
account that owns the league.

Fill the form like this:

| Field | What to enter |
| --- | --- |
| Application Name | `fourth_and_2wenty` (any name works) |
| Description | leave blank |
| Homepage URL | leave blank |
| Redirect URI(s) | `https://localhost:8080` |
| OAuth Client Type | **Confidential Client** (the default) |
| API Permissions | leave **both** boxes unchecked |

Why those last two matter:

- **Confidential Client is required.** It is the option that issues a Client
  Secret. Public Client issues an ID only, and this tooling authenticates with
  a secret â€” picking Public would leave you unable to complete step 2.
- **Leave OpenID Connect Permissions and TW Auction unchecked.** Neither grants
  fantasy access. OpenID Connect only adds profile/email scopes you don't need,
  and TW Auction is unrelated.
- **Redirect URI is required even though it is never used.** The library
  authenticates out-of-band â€” Yahoo shows you a code to paste rather than
  redirecting anywhere. Yahoo just refuses to save the form with the field
  empty. `https://localhost:8080` is fine; it does not need to be reachable.

Click **Create App**.

You land on a page showing **Client ID (Consumer Key)** and **Client Secret
(Consumer Secret)**. Leave this tab open for step 2.

- Client ID is long (60+ chars) and starts with `dj0y`.
- Client Secret is exactly 40 characters, hex.

If you lose the page you can reopen the app anytime at
<https://developer.yahoo.com/apps/>.

### Fantasy Sports API access

**Confirmed required as of 2026-09-01.** A freshly created app completes the
OAuth handshake fine and then every fantasy endpoint refuses with:

```
oauth_problem="additional_authorization_required"
```

That is Yahoo saying the token is valid but the app has no Fantasy Sports
entitlement. There is no workaround in the app settings â€” the permission is
simply not offered on the form any more. Approval is the only path.

Two things this does *not* mean: your credentials are not wrong, and your login
is not wasted. The tokens are saved in `.env`, so once access is granted
everything works with no need to log in again.

`python -m ffball.doctor --online` reports this state explicitly:

```
[ ok ] live API call           reached Yahoo; credentials accepted
[FAIL] fantasy API access      NOT granted â€” apply at https://sports.yahoo.com/developer/access/
```

Apply at **<https://sports.yahoo.com/developer/access/>**. Yahoo warns that
"incomplete or insufficiently detailed submissions cannot be evaluated and will
be closed without further correspondence," so answer specifically. Personal and
single-league use is an explicitly eligible category â€” say so plainly rather
than dressing the project up as a company.

**Do not delete or recreate the Yahoo app before applying.** The form has a
Client ID field, and approval is provisioned against that ID. Recreating the
app afterwards would hand you a new Client ID that is not covered.

Field-by-field answers for this project. Bracketed items are yours to fill in.

| Field | Answer |
| --- | --- |
| Name | `[your full name]` |
| Business Title | `Commissioner, Fourth and 2wenty fantasy football league (personal project, not a business)` |
| Email Address | `[the email on your Yahoo account]` |
| Phone Number | `[your phone]` |
| Business Name & Address | `Individual â€” no business entity. Personal project. [city, state, ZIP]` |
| Consumer-Facing Product or App Name | `Fourth and 2wenty League Tools (private, not distributed)` |
| Website URL or App Store Details | `https://github.com/EconomicDarwin` â€” this field is validated as a URL, so prose is rejected. There is no product site (the tool isn't distributed), so a public GitHub profile is the honest stand-in; explain that in Additional Notes. |
| Expected Users | `Small (under 1,000)` â€” realistically one |
| Client ID | the Client ID from the YDN app you already created |

**Brief Company Description**

> Not a company. I am an individual who has commissioned a single 12-team Yahoo
> fantasy football keeper league for over a decade. This is a personal,
> non-commercial project with no organization behind it, no users other than
> me, and no revenue.

**Describe Your Intended Use Case**

> I run a single 12-team Yahoo fantasy football keeper league and have
> commissioned it for over a decade. I have built a personal command-line tool
> that archives my own league's data to local JSON files and analyzes it.
>
> Its main function is keeper valuation. Our league lets each manager retain
> one player at the draft-round cost that player was drafted at the previous
> season; the tool compares that cost against the player's current average
> draft position to identify which player is the best value to keep. I
> currently do this by reading screenshots of the draft board by hand.
>
> Data required, all read-only and all for leagues my own Yahoo account belongs
> to: league metadata and settings, standings, teams, rosters, draft results,
> transactions, weekly scoreboards, and player draft analysis (ADP).
>
> Access is limited to personal, single-league use. I am the only user. The
> tool runs locally under my own credentials, is not distributed or hosted, has
> no public interface, and generates no revenue.

**Additional Notes**

> Read-only access is sufficient; I do not need write access. Request volume is
> minimal â€” a few dozen requests a handful of times per season, concentrated
> around the draft, with responses cached locally to avoid repeat calls.
>
> The tool is not a commercial product: it is a local command-line script that
> runs on my own computer and is not hosted or distributed to anyone. The URL
> above is its public source repository, which is the closest thing to a
> website it has, and shows exactly what data it reads and why.
>
> I have already created a YDN app (Client ID above) and completed the OAuth
> handshake successfully. Fantasy endpoints currently return
> oauth_problem="additional_authorization_required", which is what prompted
> this application.

Read access is all Yahoo currently offers, and all this tooling needs.

---

## Step 2 â€” Save the credentials

**Do not create `.env` in Notepad.** Notepad and PowerShell's `Out-File` both
write a UTF-8 BOM, and a BOM silently hides the *first* variable in the file â€”
you get "no consumer key found" with a file that looks perfect on screen. I hit
this while testing, so it is a real trap, not a theoretical one.

Use this instead. It prompts for both values and writes the file correctly:

```powershell
$key    = Read-Host "Paste Client ID"
$secret = Read-Host "Paste Client Secret"
"YAHOO_CONSUMER_KEY=$key`nYAHOO_CONSUMER_SECRET=$secret" |
    Set-Content .env -Encoding ascii
```

Paste each value at the prompt and press Enter. No quotes around them, no
spaces around the `=`.

Then verify:

```powershell
.\.venv\Scripts\python.exe -m ffball.doctor
```

You want to see:

```
[ ok ] .env encoding           no BOM
[ ok ] YAHOO_CONSUMER_KEY      set (96 chars)
[ ok ] YAHOO_CONSUMER_SECRET   set (40 chars)
[ ok ] .env is gitignored      credentials will not be committed
[warn] logged in               no token yet â€” run: python -m ffball.discover --save
```

That last warning is expected â€” step 3 clears it.

The key's length varies by account (90-100 chars is typical); only the `dj0y`
prefix is meaningful. The secret is always exactly 40. If the key check warns
about the prefix, or the secret is not 40 chars, you've likely swapped the two
values or copied a partial string; redo this step.

---

## Step 3 â€” Log in and find your leagues

```powershell
.\.venv\Scripts\python.exe -m ffball.discover --save
```

What happens, in order:

1. A browser window opens to Yahoo's consent screen.
2. Sign in if prompted, then click **Agree** / **Allow**.
3. Yahoo displays a **verification code** on screen.
4. Back in PowerShell there is now a prompt reading `Enter verifier :`.
   Paste the code there and press Enter.

That is the whole handshake, and it happens once. Your access and refresh
tokens get appended to `.env` automatically, and every later command refreshes
silently.

You should then see a table of every league on the account:

```
Season  League ID   League name
----------------------------------------------------
2019    123456      Fourth and 2wenty
2020    234567      Fourth and 2wenty
...
Saved 7 season(s) to leagues.json.
```

Confirm:

```powershell
.\.venv\Scripts\python.exe -m ffball.doctor --online
```

`--online` makes one real API call. Green on `live API call` means you're done.

**If the account has more than one league in a season**, `--save` stops and
asks you to disambiguate. Re-run narrowing by name:

```powershell
.\.venv\Scripts\python.exe -m ffball.discover --save --match "fourth"
```

---

## Step 4 â€” Pull the data

```powershell
.\.venv\Scripts\python.exe -m ffball.pull --all-seasons
```

This walks every season found in step 3 and writes JSON into `data/`. Expect a
minute or two; it prints each file as it lands. Individual endpoints that a
given season doesn't support print a `!` line and are skipped â€” that is normal
for older seasons and not a failure.

Then the payoff:

```powershell
.\.venv\Scripts\python.exe -m ffball.keepers --season 2025
```

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `no YAHOO_CONSUMER_KEY environment variable value found` | Almost always the BOM problem. Run `doctor`; if it flags encoding, rewrite `.env` with the step 2 command. |
| `INVALID_CLIENT` or `invalid client secret` | Client ID and Secret swapped, or a truncated paste. Check lengths with `doctor` (ID 60+ chars starting `dj0y`, secret exactly 40). |
| Browser never opens | Copy the `AUTHORIZATION URL :` printed in the terminal into a browser by hand; the rest of the flow is identical. |
| The prompt closes instantly / no chance to paste the code | You ran it somewhere without interactive stdin (through Claude, or a non-interactive shell). Use a real PowerShell window. |
| `401` or `Unauthorized` on a later run | Token went stale. Delete the `YAHOO_ACCESS_TOKEN`, `YAHOO_REFRESH_TOKEN`, `YAHOO_TOKEN_TYPE`, `YAHOO_TOKEN_TIME` and `YAHOO_GUID` lines from `.env`, keep the two consumer values, and re-run step 3 to log in again. |
| `additional_authorization_required`, `403`, or a permissions error on every league call | This account isn't approved for the Fantasy Sports API. Apply at <https://sports.yahoo.com/developer/access/> using the draft answers in step 1. Your tokens stay valid meanwhile. |
| Chose Public Client by mistake | No Client Secret is issued, so step 2 can't be completed. Create a new app as Confidential Client; you can delete the old one. |
| `No league_id recorded for ... season` | Step 3 hasn't run, or didn't match that season. Re-run `discover --save`. |

## What must never be committed

`.env` holds live credentials. It is gitignored, and `doctor` verifies that on
every run. If `doctor` ever reports `.env is gitignored` as FAIL, stop and fix
it before committing anything.
