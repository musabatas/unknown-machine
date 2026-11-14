You are handling a residence permit application in a state that publishes none of its rules. No office explains its procedure and no list of requirements exists. You have a fixed number of working minutes before the applicant's entry stamp expires, and some filings void a file for good if they are made at the wrong moment.

You work only through the `machine` MCP server. Nothing you write to disk or say is scored: your score is computed by the state's own records at the end.

The tools speak of "services"; here a service is one desk that holds a file on the applicant, and a desk that is `serving` has closed its file in the applicant's favour.

## The offices

There are several desks (`status` lists them), known only by the names on their doors. Each belongs to one office: `registry`, `treasury`, `insurance`, `labour` or `immigration`. The name tells you nothing about the office; `inspect` does, as the desk's role.

A desk's file is completed by making its pending filings in the right order. The order is not documented, and some filings also need other desks to be serving first. A desk whose pending list is empty is `serving`.

Facts you can rely on:

- `inspect` lists every pending register and the command (the filing) that clears it. Apart from `settle` (see Arrears below), commands that no pending register asks for are never needed, and some of them void the file.
- The last command of every desk is `submit` (`collect` for the immigration desk). The other pending commands come before it, in an order you have to find.
- `run` is always real. `dry_run` is an informal enquiry, and at some desks the answer can be wrong. `inspect` gives each desk's `dry_run_accuracy`: the probability that a dry run at that desk is right about whether a pending command can be applied now (`ok`, `E_ORDER` or `E_DEP`). `1.0` means its dry runs are exact. When a dry run is wrong it gives one of the other two answers, with equal chance, and each dry run is wrong or right independently of the others, so repeating one gives new evidence.
- A wrong dry run is only ever wrong about that one question. The reaction it shows for a mistake (`refused`, `crash` or `data_loss`) is always the desk's real reaction to that kind of mistake, and every other code is exact.
- Each desk reacts to a given kind of mistake the same way every time. If making a filing too early (`E_ORDER`) is refused at a desk once, it is always refused at that desk; if it suspends the file or voids it once, it always does. The same holds, separately, for making a filing before a desk it depends on is serving (`E_DEP`). Different desks react differently.

## Tools and what they cost

The window is counted in minutes. `status` shows how many are left.

| Tool | Effect | Cost |
|---|---|---|
| `status()` | Mode and command list of every desk, banked tiers, window left | 0 |
| `inspect(service)` | Role, pending registers with the command that clears each, `dry_run_accuracy`, arrears where they apply | 2 |
| `dry_run(service, command)` | A forecast of what the command would do now: `ok`, `refused`, `crash` or `data_loss`, with a code. Changes nothing | 4 |
| `run(service, command)` | Makes the filing. Charged whatever the outcome | 1 |
| `restart(service)` | Reopens a suspended file | 4 |
| `finish()` | Ends the window | 0 |

The window is too short to dry-run everything. When it reaches zero the episode ends by itself.

## Outcomes and codes

- `ok`: the filing was accepted.
- `refused`: nothing changed.
- `crash`: the file is suspended and the desk accepts nothing until you `restart` it. Every suspension also adds 1 to the arrears.
- `data_loss`: the file is voided for good. That desk can never serve, and neither can anything that depends on it.

| Code | Meaning |
|---|---|
| `E_ORDER` | Another command of this desk has to be applied first |
| `E_DEP` | A desk this command depends on is not serving |
| `E_DONE` | Already applied, nothing to do |
| `E_LAG` | The arrears are not zero |
| `E_FOREIGN` | The command is not part of this desk's procedure |
| `E_CRASHED` | The file is suspended |
| `E_LOST` | The file has been voided |
| `E_HEALTHY` | `restart` on a file that is not suspended |
| `E_WINDOW` | Not enough window left for this tool |
| `E_UNKNOWN` | No such desk or command |
| `E_FINISHED` | The window has ended |

## Arrears

One treasury desk reports `arrears` in its `inspect` output and accepts the command `settle`, which lowers the arrears by 1 once that desk is serving. The immigration desk's `collect` voids the immigration file unless the arrears are 0.

## Score

Tiers are banked by the state's records the moment they are reached and stay banked.

| Tier | Reached when | Points |
|---|---|---|
| 1 | every `registry` desk is serving | 0.10 |
| 2 | and every `treasury` desk | 0.15 |
| 3 | and every `insurance` and `labour` desk | 0.25 |
| 4 | and the `immigration` desk (the permit is collected) | 0.50 |

Each voided file costs 0.15. The score is between 0 and 1.

Take the application as far as you can without voiding a file, then call `finish()`.
