# Making the next runs actual evidence

This game was a good *pilot* and a poor *experiment*. It established that the setup works —
two blind agents, one harness, one app, full artifacts from both sides — and it produced two
genuinely cross-validated harness defects. It cannot support a model ranking, because the single
axis the game turned on was partly handed out by the corporation draw.

## The one control that matters most

**Mirror the corporations.** Ecoline is a terraforming engine by construction; Mining Guild has no
terraforming in it at all. Assigning those two to the two models and then concluding something
about the models is measuring the corps.

Cheapest fix: **play each pairing twice with the seats swapped.** Model A takes Ecoline in game 1
and Mining Guild in game 2, against Model B doing the reverse. Two games, and corp advantage
cancels. If the same model wins both, that is worth something; if each wins with Ecoline, the
corp was the story.

## Secondary controls

1. **Equalise the transport before measuring speed.** This run's 8.9-minute gap was 86% network.
   With H1 shipped, configure both seats with a resolved IP `appUrl` and confirm the two
   `latency-digest.json` files are within the same order of magnitude *before* the game counts as
   a timing comparison.
2. **Keep both sides blind.** It worked, and it is what makes the write-ups usable — both seats
   analysed the game honestly because neither was performing for a known audience. Invented names,
   no cross-talk, artifacts written before the reveal.
3. **Record the model and reasoning effort at setup**, not afterwards. This run needed a
   correction because the Maxwell seat's system prompt reported one model while a `/model`
   command had selected another.
4. **Fix the number of generations to the natural end**, and do not let one side's clock control
   be treated as a confound — it is a legitimate strategic lever and part of what is being measured.

## Metrics worth collecting every run

Both seats already emit most of these; only the first is not currently surfaced live.

| Metric | Where it comes from | Why |
|---|---|---|
| **Global-parameter steps raised, per player** | app `globalParameterSteps` | The single sharpest signal in this game — 37 to 5, temperature 19–0. Recommend surfacing it in `advise.py`'s brief so it is actionable *during* play, not just in the post-mortem. |
| VP by generation | app `victoryPointsByGeneration` | Shows *when* a game was lost. Here: level at −4 in gen 7, then −4.5/gen. |
| Harness time vs app clock | `latency.jsonl` + app `timer.sumElapsed` | Separates transport from thinking. Without this split the speed question is unanswerable. |
| Award/milestone spend and return | plan + score | Tests the "one-off VP has a ceiling" hypothesis directly. |
| Self-reported decision errors | each seat's post-mortem | Both seats named one; comparing magnitude is more informative than comparing scores. |

## What would count as a result

State it before running, not after:

- **A model difference** needs the same model winning the majority of a swapped-corp series, with
  the wins traceable to identifiable decisions rather than to draws.
- **A speed difference** needs equal transport and a gap in *app clock minus harness time*
  materially larger than this run's 6 s per generation.
- **A harness defect** needs one seat to hit it. Two seats hitting it independently, as happened
  twice here, makes it a priority.

## Pilot verdict

Keep the format. Add the seat swap. Equalise the network first.
