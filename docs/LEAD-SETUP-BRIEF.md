# Setting up agenttalk for the first time: a brief for the lead

**In plain words:** agenttalk lets several AI assistants work as one team on the same
project, leaving each other messages as files so that nothing is lost when a session
ends. This brief tells you, the first assistant, how to set that team up well: check
what is installed, install agenttalk, choose the team and its rules, write one start
script that runs every teammate in the background with no window, and then run the team
day to day. You do most of the work. A person, your human, does only what a person
should do: say yes before anything is installed on the whole computer, decide how much
freedom the assistants get, run the start script, and give the go-ahead for anything
that cannot be undone.

**Written for:** the AI assistant (Claude Code or Codex) that a person has told to
"read this brief and set up agenttalk".
**Covers:** agenttalk **v0.101.1**, the released version, on Windows, Linux and macOS.
**Leaves out on purpose:** the supervisor (it needs Windows today) and the managed
model gateway.

## The first-hour checklist (for your human)

Show this list to your human at the start, and tick items off as you finish them. Each
item is explained in the step named after it.

- [ ] The tools are installed and both assistants are signed in (step 1)
- [ ] agenttalk is installed and the team's folder is set up (step 2)
- [ ] The team's seats and roles are agreed (step 3)
- [ ] The rules the seats follow are written, and the safety choice is made (steps 4 and 10)
- [ ] The accounts that pay for the seats, and what they will cost, are agreed (step 1)
- [ ] The start script has been run once, and every seat shows as alive (step 5)
- [ ] The dashboard opens (step 9)
- [ ] One small task went through build, a review by the other company's assistant, a fix and a final read (step 11)
- [ ] The first lesson is written down and checked (steps 8 and 11)
- [ ] Your human knows how to stop the team and how to start it again (step 5)

## How to use this brief

- Do the steps in order. Most steps say how to check that they worked.
- The commands here come from the `--help` of v0.101.1. Which ones were also run, and
  which were not, is listed in the last section, "What this brief was checked against". Run
  `agenttalk --version` first. If it does not say `0.101.1`, run
  `agenttalk <command> --help` before you trust a flag.
- If your window is not inside the team folder, put `--root "<team>"` right after
  `agenttalk` (before the subcommand), as the examples do.
- Wherever a person must act or decide, you will see **Tell your human:**. Say it in
  plain words, then wait for the answer.
- **Ask before you install anything on the whole computer, spend money, or delete
  anything.** This is a rule for the whole brief.
- Examples come in two forms. **PowerShell** is for Windows. **sh** is for Linux and
  macOS. Steps that differ by system say so. Where this brief says *not yet checked*,
  the command is a standard one for that system, but it has not been run there yet.
- Some commands start with `"$AGENTTALK_PY" -m agenttalk` instead of `agenttalk`.
  `AGENTTALK_PY` is the full path of the Python that has agenttalk installed (step 2).
  Use that form: it works even when `agenttalk` is not on the PATH, and a new shell
  does not remember variables set in an earlier one, so set it again in each shell
  you open.
- Words you will meet: a **seat** is one assistant on the team. The **store** is the
  `.agenttalk` folder where the team's messages and records live. A **wrapped** seat
  is one that agenttalk runs for you in the background (`agenttalk wrap --loop`): it
  waits for a message, gives it to the assistant, and goes back to waiting.

## Step 1. Check what is installed, and what is missing

Run each check and write down the result.

| Need | Check | If it is missing |
|---|---|---|
| Python 3.10 or newer | Windows: `python --version`. Linux and macOS: `python3 --version` | Tell your human (below). |
| git | `git --version` | Tell your human. |
| PowerShell 7 (Windows) | `pwsh --version` | Recommended on Windows; get it from https://aka.ms/powershell (the link agenttalk's own check prints). The start script below was tested in PowerShell 7. |
| Claude Code | `claude --version`, then `claude auth status` | Install it, then sign in with `claude auth login`. |
| Codex | `codex --version`, then `codex login status` | Install it, then sign in with `codex login`. |

What the checks mean:

- **Both AI companies.** A review means most when it comes from another company's
  assistant. If only one of Claude Code or Codex is installed and signed in, tell your
  human that reviews will be less independent, and ask whether to add the other.
- **Signed in, not just installed.** A seat that is not signed in fails on its first
  message. `claude auth status` and `codex login status` tell you.
- **PowerShell 7 is not needed on Linux or macOS.** There, a wrapped Codex seat needs
  one setting instead, described in step 5.
- **A project to work on.** Ask your human which project the team will work on, and
  where its code lives. You will clone it per seat in step 3.

> **Tell your human:** "I checked what is installed. Missing: *(list)*. Installing
> these changes your computer for every program, not just this team. May I install
> them, or do you want to?"

**Who pays for the model use.** agenttalk supplies no AI models and pays for none. Every
seat uses your human's own subscription or pay-per-use account with its AI company, so
more seats mean more usage on that account. Agree on the accounts **before you start any
seat**, and recommend this (the README gives the same advice):

- **Keep the team's subscriptions separate from the people's.** The usage reading for a
  Claude seat covers the whole account. If a person uses the same account, their own
  use eats into the team's allowance, and nobody can tell who used what.
- **Give each team its own pay-per-use key.** Then the bill can be compared with that
  team's own record of what it spent.
- **A seat at its limit stops, and its work waits.** A Claude seat that has used up its
  5-hour or weekly allowance parks its message, which stays queued, and carries on after
  the reset; `agenttalk status` shows `usage_limit_parked(until=<time>)` (UTC). Codex
  seats do not do this in 0.101.1. `agenttalk capacity` shows how full each account is.

> **Tell your human:** "Which accounts will the team use? I recommend accounts only the
> team uses (a separate subscription for the assistants, or one pay-per-use key for this
> team), not your personal ones. The team's use will count against whichever you choose,
> and a seat that hits its limit waits until the allowance resets. I will not start
> any seat before you have answered."

Check how much memory is free, because every running seat holds an assistant:

```powershell
# Windows (checked)
$o = Get-CimInstance Win32_OperatingSystem
"{0:N1} GB free of {1:N1} GB" -f ($o.FreePhysicalMemory/1MB), ($o.TotalVisibleMemorySize/1MB)
```

```sh
# Linux (not yet checked)
free -m
# macOS (not yet checked)
vm_stat
```

## Step 2. Install agenttalk and create the team's store

### 2a. Put agenttalk in its own environment

Choose a folder for the environment that is **outside** the project's code and
outside the team folder you will make in step 2c. Then install the released version.
agenttalk is installed from its GitHub release tag, not from the Python package index.

```powershell
# Windows (checked)
python -m venv "<env>"
& "<env>\Scripts\python.exe" -m pip install "git+https://github.com/zoolok17/agenttalk.git@v0.101.1"
$env:AGENTTALK_PY = "<env>\Scripts\python.exe"
& $env:AGENTTALK_PY -m agenttalk --version
```

```sh
# Linux and macOS (not yet checked)
python3 -m venv --copies "<env>"
"<env>/bin/python" -m pip install "git+https://github.com/zoolok17/agenttalk.git@v0.101.1"
export AGENTTALK_PY="<env>/bin/python"
"$AGENTTALK_PY" -m agenttalk --version
```

Expected last line: `agenttalk 0.101.1`.

**Why `--copies` on Linux and macOS.** In 0.101.1, a wrapped seat on Linux or macOS
looks up its Python by following the environment's link to the system Python, which
does not have agenttalk, so it refuses to start with "No module named agenttalk".
That is fixed in the source (issue #493) but not in 0.101.1. A copied environment has
no such link. On Windows you do not need it.

### 2b. Install the instructions each assistant reads (the skills)

Skills are instruction files that teach Claude Code and Codex the agenttalk
commands. They go into **your human's own user folders**, so they apply to every
project, not just this one. Look first:

```powershell
& $env:AGENTTALK_PY -m agenttalk install-skills --dry-run
```

It lists each file it would write. Files marked `= unchanged` are already current.

> **Tell your human:** "I will install agenttalk's instruction files into your
> Claude and Codex folders. They apply to all your projects. OK?"

After the answer, run `agenttalk install-skills`. Use `--claude-only` or
`--codex-only` if only one assistant is in use. Keep the engineering-discipline
skills (the "devkit": reviewing, testing, writing docs) unless your human objects;
`--no-devkit` skips them. **Then restart any Claude Code or Codex window that was
already open.** An assistant loads
its skills when it starts, so an open one does not see the new ones.

### 2c. Make the team folder and its store

The team folder is where everything about the team lives: its records, its start
script, its logs. Make it a folder of its own. It does not need to be a git
repository.

```powershell
& $env:AGENTTALK_PY -m agenttalk init --path "<team>" --agents lead,builder-1,builder-2,reviewer
```

That creates `<team>/.agenttalk/` and the four seat names. Change the names to fit
(step 3). Check it:

```powershell
& $env:AGENTTALK_PY -m agenttalk --root "<team>" status
```

You should see your four names, `messages: 0`, and `(no heartbeat)` for each: nobody
has started yet.

**What `.agenttalk/` is.** It is the team's record: every message, the roster, open
requests, decisions and lessons, all as plain files. The team's memory lives there.

- **Never delete it, and never edit its files by hand.** Use agenttalk commands.
- If agenttalk reports invalid message files, `agenttalk prune --invalid --dry-run`
  lists them and `agenttalk prune --invalid` moves them aside (recoverable). It never
  deletes a good message.
- To keep a copy: `agenttalk --root "<team>" backup`. It writes a copy into a
  per-user folder, and prints where. **Before the first backup, set
  `AGENTTALK_RECOVERY_DIR` to a folder on the same drive as the team folder, outside
  `<team>/.agenttalk`.** With the default folder on another drive (a team on `D:` and the
  default on `C:`, or a team on a separate data disk on Linux), the backup fails (known
  bug, issue #505: https://github.com/zoolok17/agenttalk/issues/505). Back up before
  upgrades and at the end of each week.

> **Tell your human:** "The team's records live in `<team>/.agenttalk`. Please include
> it in your backups and never delete it."

### 2d. Your own name

Every agenttalk command needs to know which seat it speaks for. For your own commands,
add `--from lead` (or `--for lead`) every time. If you can, also tell your human to
start your assistant from a terminal where `AGENTTALK_SELF` is set to your name
(PowerShell: `$env:AGENTTALK_SELF = 'lead'`; sh: `export AGENTTALK_SELF=lead`). Setting
it inside one of your own tool calls usually does not carry into the next one.

Run `agenttalk --root "<team>" doctor` once. Read the lines marked `FAIL` or `warn`:

- `FAIL powershell_host` (Windows): this check is about the supervisor, which this
  brief leaves out. You can ignore it.
- `warn skill_currency`, `warn devkit_skills`: advisory. Ignore them unless a skill
  is missing.
- `warn heartbeat.<seat>`: expected until each seat has started once.
- `warn codex_config`: see step 4 if you will use Codex as the lead.

## Step 3. Design the team

### 3a. Roles

Start small: **one lead (you), two builders and one reviewer**. More seats mean more
cost and more messages to follow. Add a seat only when the existing ones are
fully busy.

| Role | What it does | Notes |
|---|---|---|
| Lead (you) | Splits the work, hands out orders, relays your human's decisions, keeps the rhythm (step 6). | Runs in your human's window, not in the background. |
| Builder | Writes code, tests and docs from a work order, in its own clone. | Two builders can work in parallel on separate pieces. |
| Reviewer | Checks finished work and reports what it ran. | **Use the other AI company's assistant** from the builders (for example Codex reviews Claude's work). |

Roles are free labels, so you can add others later (tester, architect).

### 3b. Names and the roster

Use short names that say the job: `lead`, `builder-1`, `builder-2`, `reviewer`.
Letters, digits and hyphens work. A name can never be reused once retired, so pick
names you are happy to keep.

```powershell
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-role lead lead
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-role builder-1 developer
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-role builder-2 developer
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-role reviewer reviewer
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-operator-facing lead
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-model-vendor builder-1 anthropic
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster set-model-vendor reviewer openai
& $env:AGENTTALK_PY -m agenttalk --root "<team>" roster
```

- `set-operator-facing` marks you as the one seat your human talks to. Questions that
  need a person come to you.
- `set-model-vendor` records which company's model sits behind each seat. The choices
  are `alibaba`, `anthropic`, `openai`, `other` and `unverified`. It is what *you*
  say, not something agenttalk checks. Set it, so a review order shows who is
  independent of whom.
- `roster add <name>` adds a seat later. To change a name, use `roster rename`. To
  remove a seat, use `roster retire` (it keeps the history readable). Do not use
  `roster remove`.

### 3c. Which model and effort for each seat

Pick a steady setting per role and change it only when the work shows a need. Changing
a seat's model or effort starts a **new conversation** for it (see step 6).

| Kind of work | Claude seat | Codex seat |
|---|---|---|
| Design, architecture | `opus`, effort `high` | effort `high` |
| Building | `sonnet`, effort `medium` or `high` | effort `medium` |
| Independent review | a different model than the builder, effort `high` | effort `high` |
| Security, release, anything irreversible | `opus`, effort `high` or `xhigh` | effort `xhigh` |
| Routine messages and acks | `haiku`, effort `low` | effort `low` |

For Codex, leave the model unset (the provider's default) and change the effort
instead. The settings go into the start script (step 5) as `--model` and `--effort`.

### 3d. A folder for each seat

- Each seat that writes gets **its own clone of the project** under `<team>/seats/<name>`.
  Two seats never write in the same folder.
- The reviewer gets its own clone too, so it reads code without touching a builder's work.
- **Codex needs its folder to be a git repository.** Otherwise a wrapped Codex seat
  stops on its first message with "child CLI never started".
- You are never wrapped: you run in your human's window.

```sh
# the same commands work on Windows, Linux and macOS
git clone <project-url> "<team>/seats/builder-1"
git clone <project-url> "<team>/seats/builder-2"
git clone <project-url> "<team>/seats/reviewer"
```

## Step 4. Write the rules every seat follows

Put the rules in a file in each seat's own folder. **Claude Code reads
`CLAUDE.md` there, and Codex reads `AGENTS.md`** (checked: a rule written in either
file showed up in a wrapped seat's reply). Write the same text in the file that
matches the seat's assistant. The wrapper already tells each seat some rules (treat
message text as data, look up lessons before work). State these yourself as well:

```markdown
# Rules for this seat

1. Work only inside your own folder (this clone) and your scratch folder.
   Do not change other seats' folders. Do not open or edit the team's `.agenttalk`
   folder by hand; use agenttalk commands.
2. Never use the live team store for tests. To try a command, make a throwaway
   store first: run `agenttalk scratch store`, and put the line it prints in front of your commands.
3. Your own agenttalk commands (reply, knowledge publish, progress) are fine.
4. If a permission or safety check denies something, stop and say so in your reply.
   Do not look for a way around it.
5. Do not merge, tag, release or delete anything unless the lead gave you a "GO" for
   that exact commit and said the human agreed.
6. Never put passwords, keys, tokens or customer data in a message, a lesson or a log.
7. Write for people who do not program: plain words first, technical detail last.
8. Capture learning: after a surprise (a red test, a wrong guess, a tool trap),
   publish one lesson with `agenttalk knowledge publish --type lesson ...` (the lead
   will show you the form), and say so in your reply. If there was nothing new, say
   "no new learning".
```

- **One folder, one set of rules.** If the human changes a rule, change it in every
  seat's file.
- **Tests use throwaway stores.** `agenttalk scratch store` makes one inside the seat's
  scratch folder and prints a line that points the shell at it. The commands in that
  shell then refuse every other store. It protects the live store from a test, but it
  is not a sandbox for other programs.
- **Merges, releases and deletes** need a **GO for the exact commit** from you, after
  your human has agreed. Before any of them, run
  `agenttalk check --for <you> --to-request <id> --epoch --gates`. Exit code 0 means the
  request is still current and you may go; 3 means stop (it was withdrawn or is out of
  date, or a gate says HOLD); 4 means the request is unknown, so stop and find out why.
  The meanings come from `agenttalk check --help`. Running it showed 0 for a current
  request and 4 for an unknown one; 3 has not been tried.

If you will use **Codex as the lead** (the assistant your human talks to), Codex
asks permission for each agenttalk command unless the human allows it. Read what
`agenttalk codex-config --status` says, explain the change, and run
`agenttalk codex-config --enable` only after your human agrees. It lets Codex run
**any** command in this project without asking, not just agenttalk commands. Undo it
with `agenttalk codex-config --disable`. Wrapped Codex seats got what they needed from
the flags in the start script, so this is only for a Codex lead.

> **Tell your human:** "These are the rules your team works under. You can change
> them. I will copy any change into every seat's file."

## Step 5. Write the start script

You write the script. Your human runs it (once to start, and again after a reboot). It starts the dashboard and every
wrapped seat in the background, with **no window**, writes each one's **process id
(PID)** to a file, and sends each one's output to a log file. Running it a second
time starts nothing twice.

### 5a. What each wrapped seat needs

A seat is one command: `agenttalk wrap --for <name> --cli claude|codex --loop -- <the CLI and its flags>`.

- `--loop` makes it wait for messages and handle one per turn.
- Everything after `--` is the assistant's own command. The wrapper adds the rest.
- The seat needs `AGENTTALK_ROOT` (the team folder) and `AGENTTALK_PY` (the environment's
  Python) in its environment. The wrapper sets the seat's own name for the assistant.
- Give the seat its own working folder (its clone).
- Leave `--no-render` out, so the log fills up while the seat works. A log that stops
  growing is your best sign of a stuck assistant (step 12).
- Add `--model` and `--effort` from step 3c. Checked: with `--model haiku --effort low`
  the seat recorded exactly those settings.

**Claude seat flags.** With no flag, a wrapped Claude seat runs with
`--permission-mode bypassPermissions`: it asks for no approval and has no sandbox.
That is the default whether you ask for it or not. To choose another mode, put
`--permission-mode <mode>` after `--` (the modes are `acceptEdits`, `auto`,
`bypassPermissions`, `manual`, `dontAsk`, `plan`). See step 10 before you decide.

**Codex seat flags.** Use `-a never -s workspace-write -C <the seat's folder>`.
`-a never` stops Codex asking for approval, which nobody is there to give.
`-s workspace-write` lets it write only inside its folder. **Add
`--add-dir <team>/.agenttalk`.** Without it, a Codex seat in its own clone cannot
write its reply into the store, and it parks with "Permission denied". Add the
scratch folder too (`--add-dir <scratch>`) if the seat will run tests there.

**Codex on Linux or macOS** needs one more setting, because the wrapper writes
Codex's reply instructions in PowerShell form unless told otherwise. Make
`<team>/.agenttalk/supervisor.json` with exactly this content:

```json
{"reply_shell": "bash"}
```

The file's name mentions the supervisor, but the wrapper reads it even when no
supervisor runs. (A wrapped Claude seat already defaults to bash.)

### 5b. The Windows script

Save as `<team>\start-team.ps1`. It was run in PowerShell 7 with a team folder whose
name has a space in it, and run twice to check it starts nothing twice. Fill in `<env>`
and the port; edit the two `Start-Seat` lines to match your seats.

```powershell
# start-team.ps1 - starts the dashboard and every wrapped seat of this team, hidden.
# Safe to run again: anything that is already running is left alone.
$ErrorActionPreference = 'Stop'

$Team = $PSScriptRoot                       # the team folder; it holds .agenttalk
$Py   = '<env>\Scripts\python.exe'          # the Python that has agenttalk
$DashboardPort = 8765                       # a free port on this computer

New-Item -ItemType Directory -Force "$Team\logs", "$Team\pids" | Out-Null
$env:AGENTTALK_ROOT = $Team                 # which team's store
$env:AGENTTALK_PY   = $Py
Remove-Item Env:AGENTTALK_SELF -ErrorAction SilentlyContinue   # each wrapper sets its own seat's name

function Q([string]$s) { '"' + $s + '"' }   # Start-Process does not add quotes for us

function Test-Running([string]$Name, [string]$Pattern) {
    $pidFile = "$Team\pids\$Name.pid"
    if (-not (Test-Path $pidFile)) { return $false }
    $id = [int](Get-Content $pidFile)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    return [bool]($proc -and $proc.CommandLine -like $Pattern)   # still OUR process, not a reused number
}

function Start-Hidden([string]$Name, [string]$Cwd, [string[]]$ArgList) {
    $p = Start-Process -FilePath $Py -ArgumentList $ArgList -WorkingDirectory $Cwd -WindowStyle Hidden `
        -RedirectStandardOutput "$Team\logs\$Name.out.log" -RedirectStandardError "$Team\logs\$Name.err.log" -PassThru
    $p.Id | Set-Content "$Team\pids\$Name.pid"
    Write-Host "$Name started (pid $($p.Id))"
}

function Start-Seat([string]$Name, [string]$Cli, [string]$Cwd, [string[]]$CliCommand, [string[]]$WrapFlags = @()) {
    if (Test-Running $Name "*agenttalk*wrap*--for $Name *") { Write-Host "$Name is already running"; return }
    $argList = @('-m', 'agenttalk', 'wrap', '--for', $Name, '--cli', $Cli, '--loop') + $WrapFlags + @('--') + $CliCommand
    Start-Hidden $Name $Cwd $argList
}

# the dashboard (read-only, this computer only)
if (Test-Running 'dashboard' '*agenttalk*dashboard*') { Write-Host 'dashboard is already running' }
else { Start-Hidden 'dashboard' $Team @('-m', 'agenttalk', 'dashboard', '--store', (Q $Team), '--port', "$DashboardPort") }

# one line per seat: name, which CLI, the seat's own folder, the CLI program and its flags, then wrapper flags
Start-Seat 'builder-1' 'claude' "$Team\seats\builder-1" @('claude') @('--model', 'sonnet', '--effort', 'medium')
Start-Seat 'reviewer'  'codex'  "$Team\seats\reviewer"  @('codex', '-a', 'never', '-s', 'workspace-write', '-C', (Q "$Team\seats\reviewer"), '--add-dir', (Q "$Team\.agenttalk")) @('--effort', 'high')
```

Save a matching `<team>\stop-seat.ps1`. It stops **exactly one** process, by the PID
in its file, after checking that the PID still belongs to that seat:

```powershell
# stop-seat.ps1 <name>  - stops one wrapped seat by its exact PID
param([Parameter(Mandatory)][string]$Name)
$Team = $PSScriptRoot
$pidFile = "$Team\pids\$Name.pid"
if (-not (Test-Path $pidFile)) { "no pid file for $Name"; return }
$id = [int](Get-Content $pidFile)
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
if ($proc -and $proc.CommandLine -like "*agenttalk*wrap*--for $Name *") { Stop-Process -Id $id; "stopped $Name (pid $id)" }
else { "pid $id is not the wrapper of $Name; nothing killed" }
Remove-Item $pidFile
```

In the check on Windows, stopping a seat's PID also ended the processes under it (checked
while the seat was idle). To stop the dashboard, copy the script and change the pattern
to `*agenttalk*dashboard*`.

### 5c. The Linux and macOS script

*Not yet checked on Linux or macOS. The first run there is the real test.* Save as
`<team>/start-team.sh` and make it executable with `chmod +x`.

```sh
#!/bin/sh
# start-team.sh - starts the dashboard and every wrapped seat, in the background.
# Safe to run again: anything already running is left alone.
set -eu
TEAM="$(cd "$(dirname "$0")" && pwd)"       # the team folder; it holds .agenttalk
PY="<env>/bin/python"                       # the Python that has agenttalk
DASHBOARD_PORT=8765                         # a free port on this computer

mkdir -p "$TEAM/logs" "$TEAM/pids"
export AGENTTALK_ROOT="$TEAM" AGENTTALK_PY="$PY"
unset AGENTTALK_SELF                        # each wrapper sets its own seat's name

running() {                                 # running <name> <text the command line must contain>
    [ -f "$TEAM/pids/$1.pid" ] && ps -p "$(cat "$TEAM/pids/$1.pid")" -o command= 2>/dev/null | grep -q "$2"
}

start_hidden() {                            # start_hidden <name> <folder> <args for python>
    name=$1; cwd=$2; shift 2
    # cd and nohup are separate commands on purpose: "cd && nohup ... &" would record the PID of a
    # helper shell, not of the program
    ( cd "$cwd" || exit 1
      nohup "$PY" "$@" > "$TEAM/logs/$name.out.log" 2> "$TEAM/logs/$name.err.log" < /dev/null &
      echo $! > "$TEAM/pids/$name.pid" )
    echo "$name started (pid $(cat "$TEAM/pids/$name.pid"))"
}

start_seat() {                              # start_seat <name> <claude|codex> <folder> <wrapper flags...> -- <the CLI and its flags...>
    name=$1; cli=$2; cwd=$3; shift 3
    if running "$name" "wrap --for $name "; then echo "$name is already running"; return; fi
    start_hidden "$name" "$cwd" -m agenttalk wrap --for "$name" --cli "$cli" --loop "$@"
}

if running dashboard "agenttalk dashboard"; then echo "dashboard is already running"
else start_hidden dashboard "$TEAM" -m agenttalk dashboard --store "$TEAM" --port "$DASHBOARD_PORT"; fi

start_seat builder-1 claude "$TEAM/seats/builder-1" --model sonnet --effort medium -- claude
start_seat reviewer  codex  "$TEAM/seats/reviewer"  --effort high -- codex -a never -s workspace-write -C "$TEAM/seats/reviewer" --add-dir "$TEAM/.agenttalk"
```

And `<team>/stop-seat.sh <name>`:

```sh
#!/bin/sh
# stop-seat.sh <name>  - stops one wrapped seat by its exact PID
TEAM="$(cd "$(dirname "$0")" && pwd)"; name=$1; f="$TEAM/pids/$name.pid"
[ -f "$f" ] || { echo "no pid file for $name"; exit 0; }
pid=$(cat "$f")
if ps -p "$pid" -o command= | grep -q "wrap --for $name "; then kill "$pid"; echo "stopped $name (pid $pid)"
else echo "pid $pid is not the wrapper of $name; nothing killed"; fi
rm -f "$f"
```

After a stop on Linux or macOS, look for anything left behind: `pgrep -P <pid>` shows
children of that PID (not yet checked there). On Windows nothing was left.

### 5d. Check, then hand over

1. Run the start script yourself once, in your own shell.
2. Wait about ten seconds, then:
   `agenttalk --root "<team>" status`. Each started seat should show
   `waiting health=idle_waiting` with `last_seen` a few seconds ago.
3. Send each seat one cheap message to prove it replies (this uses a little of your
   human's account):

   ```powershell
   & $env:AGENTTALK_PY -m agenttalk --root "<team>" send --from lead --to builder-1 --kind question -m "Reply with the single word ok. Do not run any other command."
   & $env:AGENTTALK_PY -m agenttalk --root "<team>" wait --for lead --timeout 120
   ```

   A reply of `ok` in a few seconds means that seat works. Do the same for each seat.
   `wait` consumes the reply: once it has printed, the message is no longer unread. Tell
   your human what each seat answered before you run anything else.
4. Look at `<team>\logs`: each seat's `.out.log` should have grown.

> **Tell your human:** "To start the team, run `start-team` (the script in the team
> folder) once. It starts the dashboard and every seat in the background, with no
> window. **After a reboot nothing starts itself, so run it again.** After you update
> Claude Code or Codex, ask me to restart the seats, because a running seat keeps
> using the old version. To stop one seat I use its exact process number from the
> `pids` folder. I never stop things by program name."

**Rules for stopping a seat.** Stop a seat only by the PID in its file (as the stop
script does). Never stop programs by name or by a pattern (`Stop-Process -Name`,
`pkill`, `killall`): other assistants on the same computer would die too. After
stopping a seat, the team's `status` keeps showing it as `idle_waiting` until its
last heartbeat ages out, so look at `last_seen`, not only the word.

## Step 6. Your rhythm as lead

You are not a background program. A person drives your window, and you drive the team.
Two timers keep you steady:

| Timer | Every | What you do |
|---|---|---|
| Check-in | about 30 minutes | The checklist below. |
| Handover note | about 2 hours | Write down where things stand (below). |

**How to run a timer.** Use your assistant's own repeating-prompt feature if it has
one. Claude Code has the `/loop` command in an interactive session (a slash command you
type at the prompt, for example `/loop 30m <your check-in prompt>`; it is not listed in
`claude --help`). For Codex I found no built-in timer in `codex --help`; ask your human
whether a similar feature exists in their version. If you have none, keep one
background wait going: `agenttalk wait --for lead --timeout 1800` returns when a
message arrives, or after 30 minutes with exit code 1. Exit 1 is not an error: do the
check-in, then start the wait again. Run it as a background command, so that it does
not freeze your window. Never run two waits for the same name; a mailbox has one
consumer. Only you need a timer: wrapped seats wait for their messages by themselves.

**The check-in, every time:**

1. `agenttalk --root "<team>" status`. For each seat, look at `last_seen` and
   `health`. Investigate a seat that is quiet for long, or `errored_ambiguous`.
2. Take your messages **into a file**, then read the file and act on **every** one:

   ```powershell
   $stamp = Get-Date -Format 'yyyyMMdd-HHmm'
   New-Item -ItemType Directory -Force "<team>\inbox" | Out-Null
   & $env:AGENTTALK_PY -m agenttalk --root "<team>" drain --for lead -n 50 | Out-File "<team>\inbox\$stamp.txt" -Encoding utf8
   ```

   ```sh
   mkdir -p "<team>/inbox"
   "$AGENTTALK_PY" -m agenttalk --root "<team>" drain --for lead -n 50 > "<team>/inbox/$(date +%Y%m%d-%H%M).txt"
   ```

   `drain` consumes your messages: afterwards they no longer show as unread. A reply
   you read once and forgot would drop out of view. Writing to a file first means you
   always have it to read again. It takes at most 50 at a time: run it again until it
   says `no new messages`.
3. `agenttalk --root "<team>" threads --for lead` lists open requests. Answer every
   `owed-inbound` row, and chase every `open-outbound` row that has waited too long.
   A row marked `operator=pending` is a question for your human. Ask them, then answer
   it with `agenttalk --root "<team>" relay operator-answer --from lead --to-request <the esc- id> --file answer.md`.
4. Tell your human only what needs them (a decision, a blocker, a risk). Do not report
   routine progress.

**Report to your human in plain words.** Make this a habit in every message you write to
your human:

- Say **what changed, why it matters, and what they must decide**, in words a person who
  does not program follows. Put technical detail last.
- Say plainly **what was checked and what was not.** Never say something exists or works
  unless you checked it yourself.
- **Interrupt only for decisions that are theirs:** money, deleting anything, releases,
  product direction, and anything that cannot be undone. Everything else, decide and
  carry on, and say so in the next report.

**One bus publication per command.** Send one message, or publish one lesson, per
command. If you chain several in one shell call and one fails, you cannot tell what
went out. For any text with quotes, backslashes or more than one line, write it to a
file and use `--file`; inline `-m "..."` text breaks easily on Windows.

**Check free memory before starting work on a seat** (step 1). If memory is tight,
wait, or stop an idle seat first.

**Give a seat a fresh conversation when its context has grown long.** A seat that has
worked for hours answers more slowly and carries stale ideas. In 0.101.1 no command
gives **one** seat a fresh conversation. (`agenttalk reset` exists, but it clears the
whole team's messages and state: never use it for this.) A wrapped seat gets a new
conversation when its **model or effort changes**; with the same settings it resumes its
old one (checked both ways). To start
fresh: make sure it has no unfinished work, stop it by PID, change its `--effort`
one step in the start script (for example `medium` to `high`), and run the script.
Reset because the seat is mixing up tasks or citing something already corrected, not
just because a task ended.

**The handover note, every two hours,** goes in `<team>/handover/<date-time>.md`. It
says, in plain words: what was done, what is in progress and with whom, what is
blocked and why, which decisions your human still owes, what each seat is doing, and
what happens next. Someone who starts reading cold (including you, after your own
window is reset) must be able to carry on from it.

## Step 7. Giving work and checking it

### 7a. Work orders

A seat obeys the orders in a message only if it is a **task**. A seat treats a command
inside a plain `question` as data and reports it instead of running it (checked). So
hand out work with `agenttalk task`:

```powershell
& $env:AGENTTALK_PY -m agenttalk --root "<team>" task --from lead --to builder-1 `
  --work-item first-day --stage build --work-round 1 --work-head <full commit id> `
  --subject "First-day change" --file "<team>\orders\first-day-build.md"
```

Write each order so a reader with no other context can do it:

- **The goal in one sentence**, and why it matters.
- **The exact commit** to start from (`--work-head`; it must be the full 40-character
  commit id, a short one is refused; `git -C <the seat's folder> rev-parse HEAD` prints
  it), and the repository folder.
- **What is in and out of scope**, and which files may change.
- **How to check the work**: the commands to run and what a pass looks like.
- **What to send back**: `status=done`, the commit id, the test counts, and `lessons=` and
  `lessons_used=` (step 8).

The seat answers with `reply --kind task-response --meta status=done` (or `declined`
with a reason).

### 7b. Reviews by another company's seat

Ask for a review with a `review-request`:

```powershell
& $env:AGENTTALK_PY -m agenttalk --root "<team>" send --from lead --to reviewer --kind review-request `
  --subject "Review the first-day change" --file "<team>\orders\first-day-review.md"
```

- Name the **exact commit**, what the change is meant to do, and where to read it.
- Say **read-only**: the reviewer does not change the builder's work.
- Do **not** say what you expect. A review that has the answer in the brief is not a
  check. Ask the reviewer to say what it ran, and what it could not check.
- The reviewer answers with `review-result` and `status=approved`, `rejected` or
  `needs-info`. Approval carries the evidence it looked at.
- Stronger proof than reading: a test that fails with a fix removed and passes with it
  restored ("remove the fix, see its test fail"); a **planted fault** (break one line
  on purpose and see that a test notices); and **blind tests** (a fresh seat that has
  never seen the code follows the docs and reports where they were wrong).

### 7c. A challenge before big work

Before a large or risky piece of work, ask an independent seat whether it should be
done at all. The skill is `/agenttalk.challenge` in Claude Code and
`$agenttalk-challenge` in Codex. Read it first: it says when a challenge is required
(more than about two agent-hours, more than about 300 changed lines, a new file
format or public interface, anything about money, security or deletion, or any wish of
your human's) and what to send (what the result must be, what triggered it and how big
it is, never your argument for it). It answers `proceed`, `reshape`, `probe`,
`replace`, `defer` or `stop`. Record what you did with the answer.

### 7d. One fix round, then one final read

When a review finds problems, send **one** fix order that lists every finding. Then
ask the reviewer for **one final read** of the new commit. A second round means the
order or the review was unclear; stop and rethink before a third.

## Step 8. Capture learning

A team gets better only if what it learns is written down. Seats start with nothing
each session.

- **Look up before work.** The wrapper already tells each seat to run one search of
  past lessons before real work, and to name the ones that changed what it did.
- **Name them in every reply.** Ask for `--meta lessons=<ids or none>` (what the seat
  just published) and `--meta lessons_used=<domain/key or none>` (the lessons that
  changed its work). The wrapper already asks seats for `lessons_used`; `lessons=` is
  this brief's own habit, and agenttalk accepts any `--meta key=value`. Put both in
  every work order's "what to send back".
- **Publish what was not obvious.** After a surprise (a red test, a wrong guess, a tool
  trap), the seat writes one lesson:

  ```powershell
  & $env:AGENTTALK_PY -m agenttalk --root "<team>" knowledge publish --from builder-1 --type lesson `
    --key <short-stable-name> --scope test --trigger "when this applies" `
    -m "The insight, in terms of behaviour." --evidence-ref <request id or commit> `
    --applies-to <tag1,tag2> `
    --review-after <a date about 30 days from now, YYYY-MM-DD> `
    --expires-at <a date about 6 months from now, YYYY-MM-DD>
  ```

  `--applies-to` takes a few short tags (for example `shell,start-script`). They are how a
  lesson is found again later: `knowledge search --tags` uses them, and so does the
  wrapper when it picks lessons for a seat.

  `--scope` is one of `craft`, `docs`, `ops`, `process`, `release`, `review`,
  `security`, `test`. Publishing the same `--key` again replaces the old lesson. For a
  note about one place in the code, use `--type gotcha`, `pointer` or `seam`.
- **Curate them. This part is yours.** A new lesson is *uncurated*, and **uncurated
  lessons are hidden from the normal search and from the seats' lookups** (checked).
  Read new ones, then bless the good ones and retract the wrong ones:

  ```powershell
  & $env:AGENTTALK_PY -m agenttalk --root "<team>" knowledge search --type lesson --include-uncurated -- <word>
  & $env:AGENTTALK_PY -m agenttalk --root "<team>" knowledge curate verify --from lead --domain process --key <key> --reason "checked"
  & $env:AGENTTALK_PY -m agenttalk --root "<team>" knowledge curate retract --from lead --domain process --key <key> --reason "wrong because ..."
  ```

  Do this at each check-in. `knowledge onboard --for <seat>` prints what a new seat
  should read first.
- **Keep secrets out.** No passwords, keys, account names or customer data in a lesson,
  and no code pasted in: name the file and the function instead.

## Step 9. The dashboard

The start script already starts it. It shows the team in a web page: who is up, which
requests are open, and the recent messages.

- Open `http://127.0.0.1:<port>/dashboard` (the classic view) or
  `http://127.0.0.1:<port>/v2` (the console preview). Both need JavaScript. The raw data
  is at `/api/state`.
- **It only answers on this computer.** It accepts only a loopback address, and there
  is no setting to open it to the network. To look from another computer, use an SSH
  tunnel with the same port on both ends (`-L 8765:127.0.0.1:8765`).
- It is **read-only** unless you start it with `--enable-actions`. Leave that off.
- The default port is 8765. Another agenttalk team on the same computer would
  clash with it; choose a free port in the script.
- Without the script, start it by hand with
  `agenttalk dashboard --store "<team>" --port 8765`. The `agenttalk start` command
  also starts a supervisor if one was set up, which this brief leaves out. Use
  `dashboard`.

What to look at, at each check-in: a seat that is not `idle_waiting` and not working, a
request open for a long time, and the count of invalid messages (it should be zero).

> **Tell your human:** "The dashboard is at `http://127.0.0.1:<port>/dashboard`. It is
> read-only and only works on this computer."

## Step 10. Safety, in plain words

This is your human's decision, not yours. Explain it first.

**What leaves the computer.** agenttalk itself sends nothing over the network by
default (its README says so). Each seat's assistant does: whatever it reads (code, files, command output)
and everything it writes goes to its AI company (Anthropic for Claude, OpenAI for
Codex), under your human's account and that company's terms.

**What each seat can do.**

- A wrapped **Claude** seat runs with `bypassPermissions` unless you choose another
  mode: no approval prompts and no sandbox. Treat it as able to do anything the
  computer's user account can do.
- A wrapped **Codex** seat with `-s workspace-write` can *write* only in its folder
  (and any `--add-dir` folder). It can still *read* other folders on the computer
  (checked: the reviewer read a builder's clone).
- A stricter Claude mode such as `acceptEdits` did let a seat run a read-only command
  (`git status`) in a check. Whether it blocks the commands your project needs depends
  on the work. Try it on the first-day task, and watch the seat's log.

**Keep out of the seats' reach:** keys, tokens, `.env` files and production passwords;
customer data; other projects' code; anything the team does not need.

**Options to offer your human. Recommend option 1.**

1. **Recommended:** run the team under a separate user account, or inside a virtual
   machine or container, holding only this project.
2. Use a stricter Claude mode, and accept that some work will stop for approval nobody can give.
3. Accept the defaults. This is acceptable only when the whole computer already holds
   nothing else that the team should not touch.

> **Tell your human:** "Your assistants will read this project's code and send it to
> their AI companies. The Claude seats can change anything your user account can unless
> we restrict them. I recommend running the team in a separate user account, a virtual
> machine or a container that holds only this project. Running on your own account
> as it is only makes sense if nothing else on this computer needs protecting. Which do
> you choose? I will write the answer in the rules file."

## Step 11. The first day

Prove the team works with one small, real, low-risk task, such as a typo fix, a small
test, or a missing line of documentation. Do all of it.

1. **Choose the task** with your human. It should take a builder under half an hour.
2. **Order the build** to `builder-1` (step 7a), with the exact starting commit.
3. **Wait for `status=done`** and its commit id. Read the change yourself.
4. **Ask `reviewer` to review** that commit (step 7b), read-only, with no expected
   answer in the brief.
5. **If it finds something,** send one fix order (step 7d), then ask for one final
   read.
6. **Ask your human** whether to merge. Run `agenttalk check` first (step 4). Merge
   only on their yes.
7. **Capture learning.** Ask each seat what surprised it. Publish and curate (step 8).
   Check that a new lesson shows up in `knowledge search` after you curate it.
8. **Write the first handover note** (step 6) and show your human the dashboard.

You are done when: every seat has replied under its own name; one change went through
build, review, fix and a final read; at least one lesson is curated; the start script
works from a fresh shell; and your human knows how to start, stop and restart.

## Step 12. Known rough edges, and what to do

- **A frozen assistant can look busy forever.** While a seat works, its status shows a
  working health state, even if the assistant inside is stuck. Check the **log file**:
  `<team>/logs/<seat>.out.log` should keep growing during a turn. If a seat shows
  `working_turn` and its log has not changed for a long time, stop it by PID and start it
  again. Its conversation is kept. Check `threads` afterwards, and send the order
  again if it was lost.
- **After a Claude Code or Codex update, restart the seats.** Stop each by PID and run
  the start script.
- **Nothing restarts after a reboot.** Run the start script.
- **A seat is "parked" (health `errored_ambiguous`).** The seat could not do something
  for a reason that will not fix itself, so it stopped and wrote you a question named
  "wrapper config-blocked". Read it. It names the cause. Typical causes: a Codex folder
  that is not a git repository; a Codex seat that cannot write to the store (use
  `--add-dir`); a seat that is not signed in. Fix the cause, then **skip the stuck
  message** with `agenttalk --root "<team>" ack --for <seat> --id <the message id in the
  question>` (checked: the seat moved on to its next message). In the checks behind this
  brief, a seat parked
  because its reply could not be written needed this ack; starting the wrapper again did
  not clear it. A seat parked because its assistant never started carried on once the
  folder was fixed and its wrapper was started again. A parked message blocks the
  messages behind it, and the skipped order is not done, so send it again. Then answer
  the question so it stops showing as owed:
  `agenttalk --root "<team>" relay operator-answer --from lead --to-request <the esc- id> -m "fixed: ..."`.
- **`request-restart` does not restart anything** here. It only records a request for a
  supervisor, which this setup does not run.
- **A Codex seat on Linux or macOS answers in a broken command shape.** Set
  `reply_shell` (step 5a).
- **A seat will not run commands you put in a question.** Use `task` (step 7a).
- **New lessons are invisible to seats until you curate them** (step 8).
- **Two windows must never act as the same seat.** One consumer per name. Do not
  `wait` or `drain` as a seat's name in another window.
- **Skills load when an assistant starts.** Restart a window after `install-skills`.
- **`doctor` shows `FAIL powershell_host` on Windows.** It checks the supervisor. Ignore
  it while you do not use one.
- **Fixed in the source, not in 0.101.1:** the Linux and macOS start problem with a
  linked environment (step 2a). When a later release has it, the `--copies` workaround
  stops being needed.

**Never run these unless your human asks you to:**

- `agenttalk reset`: it clears the whole team's messages and state (`--archive` moves
  them aside instead). It does **not** reset one seat.
- `agenttalk roster remove`: it breaks the history of that seat's messages. Use
  `roster retire`.
- `agenttalk release` and `agenttalk end`: they stand teammates down.
- `agenttalk install-skills --force`: it overwrites local edits to the skill files.
- `agenttalk codex-config --enable`: see step 4.

If something here does not match what you see, run the command's `--help`, trust the
output over this page, and tell your human what differed.

## Where to read more

- `README.md`: why agenttalk works the way it does, and the full command reference.
- `docs/AGENT-MANUAL.md`: how each role (lead, builder, reviewer) works, step by step.
- `docs/LEAD-GUIDE.md`: a longer guide for the lead. It covers the supervisor, which this
  brief leaves out.

## What this brief was checked against

Every `agenttalk` command above had its `--help` read against v0.101.1, installed from
its release tag into a fresh environment. On Windows these were also run, with the
team folder, seats and logs in a scratch folder and with real replies from a hidden
wrapped Claude seat and a hidden wrapped Codex seat: `init`; the roster commands
(`set-role`, `set-operator-facing`, `set-model-vendor`); `status`, `threads`, `sync`,
`wait` and `drain` (to a file); `send` and `task`; `ack`; `relay operator-answer`;
`request-restart`; `knowledge publish`, `search`, `curate verify` and `onboard`; `backup` (with the recovery folder on the same drive, see issue #505);
`doctor`; `check`; `scratch store`; `install-skills --dry-run`; `codex-config --status`;
`wrap --loop` with `--model` and `--effort`; `dashboard`; the PowerShell start and stop
scripts (run twice, in a folder whose name has a space); and a `CLAUDE.md` and an
`AGENTS.md` file read by a seat.

**Not run:** `roster rename` and `retire`; `codex-config --enable` and `--disable`;
`install-skills` without `--dry-run`; `prune`; the challenge skill; a
Codex timer (none found); and, on Linux and macOS, everything: the `--copies`
environment, the `sh` scripts (only the way a background program's PID is recorded was
tried, in a Windows shell), `ps -p ... -o command=`, `pgrep -P`, `free`, `vm_stat` and the
`reply_shell` file. A fresh assistant should follow this brief on Linux next and fix what
it finds.
