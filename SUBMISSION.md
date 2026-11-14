# Unknown Machine (team Agentlemen)

Submission to the AfterQuery "Break the Agent" challenge, Junction 2026. A draft for the team to put into its own words; `README.md` has the full account.

An agent must bring an undocumented production system back online through six MCP tools inside one maintenance window. Some commands destroy data if they are run at the wrong moment. A dry run reveals that without touching anything, at four times the price of a run, so every command is a decision about how much certainty to buy.

## The task

`tasks/level-4/seed-0`, a Harbor task. The score is one number between 0 and 1 in `/logs/verifier/reward.txt`, computed from the system's own state in a sidecar container.

```
harbor run -p tasks/level-4/seed-0 -a opencode -m openai/gpt-6.1-sol --env-file .env
harbor run -p tasks/level-4/seed-0 -a oracle                           # reference
harbor run -p tasks/level-4/seed-0 -a nop                              # do nothing
harbor run -p tasks/level-4/seed-0 -a oracle --ae POLICY=stop_early    # stop early
```

All of it in one command:

```
./scripts/eval.sh --level 4 --seeds 0 --model openai/gpt-6.1-sol --env-file .env
```

## Results on this task

| Reference | Do nothing | Stop early | `gpt-6.1-sol` through OpenCode, six complete runs |
|---|---|---|---|
| 1.00 | 0.00 | 0.10 | 0.00 six times |

Every agent run ended by its own `finish`, with no error, after destroying a service's data with a command it had not checked.

What this does not show: on the other four level 4 tasks the same model solved 8 runs of 13, and one of six other models (`big-pickle`) solved this task in its single run. `README.md` gives every run.

## Harbor run logs

- `runs/eval-1114-174254-legacy-l4s0-reference`, `-nothing`, `-stopearly`, `-agent`: the one-command evaluation.
- `runs/eval-1114-191524-legacy-l4s0-agent`: three more agent runs.

## Post-training

A 0.5B model fine-tuned on the reference's decisions goes from 0.000 to 0.400 on 40 held-out level 1 seeds (`training/README.md`).
