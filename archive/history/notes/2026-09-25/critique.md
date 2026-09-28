# Critique — Your Life as a Royal Elephant Keeper in Mughal India

Re-reading `draft1.md` cold, as three separate critics.

## Bedtime viewer

The opening lands well — a grieving calf and a frightened boy is a gentle, specific hook, not a shocking one. The washing/routine stretch in Chapter Two feels calm and lived-in. But a few places jolt: "Ain thirty-five of the emperor's household regulations lists exactly how much grain, ghee and sugar a royal elephant is owed each single day" reads like a textbook footnote dropped into the middle of a bedtime story — it pulls me out of the boy's body and into a lecture. The musth scene ("Pari strains against her post so hard the whole stable timber groans") is genuinely tense, which is fine once, but it needs to resolve faster than it currently does or it will keep a drowsy listener alert too long. The jump from the wedding scene straight into "Some elephants here are trained for the emperor's harsher justice, and you have seen, once, from a careful distance, what that training is for" is the biggest problem — it swings from joy to something dark with no breath in between, and the vagueness ("what that training is for") is more unsettling than a plainer, softer sentence would be. I also don't feel the smell and sound of the stable enough in Chapter Two — I'm told what the boy learns, not what fills his senses while he learns it.

## Historian

Cross-checking against `research.md`: the claim that "Ain thirty-five of the emperor's household regulations lists exactly how much grain, ghee and sugar a royal elephant is owed each single day" overstates fact 1, which only says Ain 35 covers upkeep, branding and "the food given to animals" in general — it does not itemise grain, ghee and sugar amounts, so this line invents specificity the source doesn't support. "Pari learns twenty words from your mouth before her third year" invents a timeframe; fact 11 only supports elephants learning more than twenty commands generally, with no age attached. Biggest issue: "standing in the dust beside four tons of trained strength" — fact 16 gives four tons specifically for an adult male elephant, but Pari is established as female throughout the script; an adult cow is lighter, so this line misapplies a male-only statistic to a female animal. The elephant-executions material (fact 19) is real and well documented by the V&A's Akbarnama painting, so keeping it is right — but the draft states it too starkly for how thin the historical hedge is; it should read as a known, documented practice rather than a mysterious dark rumour.

## YouTube strategist

No AI-sounding filler words present (no "tapestry," "testament," "delve," "little did you know"), which is good. The first thirty seconds hook cleanly on a real stake. Chapter-end open loops mostly work well ("But a calf who eats from your hand is not yet an elephant..."; "you do not yet understand what it means to be responsible..."; "But even a day so full of joy cannot erase..."), but Chapter Four's closing line — "You begin, without quite noticing, to walk more slowly beside her, matching a pace that used to feel impossibly patient to a restless boy" — is purely reflective, not a forward-pulling tease, and will cost some retention going into the final chapter. The repeated intensifier in "Once Pari refuses, absolutely refuses, to cross a stretch of riverbank" reads as padding rather than voice. `narrator_voice` and per-scene `tone` had not yet been chosen in the draft — needed before this can be scored on delivery fit.

## Round 1 scores
hook: 8
immersion: 7
comfort: 6
accuracy: 7
pacing: 7
originality: 9

## Must fix
1. Fix the female-elephant/four-tons mismatch — quoted: "standing in the dust beside four tons of trained strength" — remove the specific tonnage claim (research only supports ~4 tons for adult males) and describe her size without an unsupported number.
2. Hedge the invented regulation specifics — quoted: "Ain thirty-five of the emperor's household regulations lists exactly how much grain, ghee and sugar a royal elephant is owed each single day" — generalise to what `research.md` actually supports (that a regulation covered feeding and upkeep), without inventing itemised amounts.
3. Remove the invented age/timeframe for commands — quoted: "Pari learns twenty words from your mouth before her third year" — drop "before her third year," since `research.md` supports the number of commands, not a timeline.
4. Soften the joy-to-darkness transition into Chapter Four — quoted: "Some elephants here are trained for the emperor's harsher justice, and you have seen, once, from a careful distance, what that training is for." — add a gentler bridging line first, and make the historical detail feel documented rather than ominously vague.
5. Give Chapter Four a real forward-pulling open loop instead of a purely reflective closer — quoted: "You begin, without quite noticing, to walk more slowly beside her, matching a pace that used to feel impossibly patient to a restless boy." — rewrite so it explicitly teases what is coming in the final chapter.
6. Add sensory texture (sound/smell, not just sight) to the Chapter Two routine — quoted: "You learn to read her mood from her ears alone, from the set of her trunk, from the particular way she shifts her weight before deciding." — work in something heard or smelled, not only watched.
7. Clarify that the whip is the rejected, harsher alternative, not a normalised default — quoted: "tonight he has carried home a problem no rope or whip can solve" — reword so it's clear your father specifically refuses those harsher methods, matching the safety guidance on treating harsh historical practices soberly rather than casually.
8. Soften the musth peak slightly and keep it to one clean beat rather than lingering — quoted: "Pari strains against her post so hard the whole stable timber groans, and you do not move from the doorway." — trim the intensity so it resolves within a scene or two without over-extending the tense stretch.
9. Cut the padding repetition in the river-danger scene — quoted: "Once Pari refuses, absolutely refuses, to cross a stretch of riverbank that later proves to hide a current strong enough to have drowned you both." — remove the doubled "refuses, absolutely refuses" for cleaner narration.
10. Choose and lock `narrator_voice`, and assign a `tone` to every scene, before final scoring — the draft has neither, and the strategist can't evaluate delivery fit without them.

---

## Rewrite

The full script was rewritten scene-by-scene applying all ten fixes above (see `scripts/2026-09-25.json` for the final chapters): the tonnage claim was replaced with a non-numeric comparison ("an animal larger than the emperor's carriage"); the Ain thirty-five line now says only that a regulation set down "exactly how such a royal elephant must be watered, fed and housed," without inventing itemised amounts; "before her third year" was cut; a new bridging scene ("Not every animal in the imperial stables is trained for joy and procession, and every mahout learns this eventually, usually without being told twice.") now leads into a calmer, "documented" phrasing of the executions detail; Chapter Four's closing scene was rewritten to tease the final chapter directly ("the slow, patient pace you matched to hers for years is about to become the pace of your remaining life"); a sound/smell cue ("the low rumble in her chest") was added to the Chapter Two mood-reading scene; the whip line now reads "a problem he refuses to solve with rope or whip," making the rejection explicit; the musth scene's peak line was trimmed to a single clean beat; the river scene's repetition was cut to "simply will not cross"; and `narrator_voice: bm_lewis` plus a `tone` on every one of the fifty-eight scenes were locked in, with tense/urgent kept to isolated beats and never dominating two chapters in a row.

## Round 2 — re-critique after rewrite

**Bedtime viewer:** The Ain-regulation line no longer reads like a footnote. The Chapter Three-to-Four transition now has a soft bridging scene before the harder material, so the tone shift feels earned rather than jolting. The musth peak resolves in one clean beat and the following scene brings it straight back to tenderness. The Chapter Two routine now has a heard, not just seen, detail. I feel immersed throughout and never jarred out of the calm.

**Historian:** The tonnage mismatch is gone — Pari's size is now conveyed by comparison, not an unsupported statistic. The regulation line is honest to what `research.md` actually supports. The commands line no longer claims an invented age. The executions detail is now explicitly framed as "documented," matching the V&A source rather than reading as vague rumour. Every remaining factual claim traces to a numbered fact in `research.md`, and the two genuinely uncertain items (musth-inducing methods, the frequency of panicking elephants) were already hedged as "(debated)" in the research file and are kept suitably soft in the narration ("Handlers say," "you learn").

**YouTube strategist:** Chapter Four now ends on a real forward tease. The river scene reads cleanly with the repetition removed. `narrator_voice: bm_lewis` (a warm, unhurried male storytelling voice) fits a working man's lifelong bond with one animal well, and it is distinct from the only other script on file (`2026-09-24`, which set no `narrator_voice`). Tones are assigned scene-by-scene: tense beats are isolated (musth onset and peak; the river refusal) and never carry two consecutive chapters, exactly as required. No AI-sounding stock phrases anywhere in the final text.

## Round 2 scores
hook: 9
immersion: 9
comfort: 9
accuracy: 9
pacing: 9
originality: 9

All categories reached nine or above in round two; no round three was needed.
