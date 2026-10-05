# NLP vs human extraction

50 human-labelled CT head reports (`vaiables_final.csv`), 943 non-NR human values.
Scored with `evaluation/compare_to_human.py`. Thickness and midline shift are compared
in mm whichever unit the report used. Vocabulary-only differences ("Mixed" vs "Yes",
"Medium" vs "Moderate", "Well aerated" vs "Unremarkable") are not counted as errors.

| | Recall | Precision |
|---|---:|---:|
| Before (original notebook) | 46% | 71% |
| After (new rules) | **91%** | **91%** |

Recall = human values the code reproduced. Precision = code values that match the human.

## Test on 9 new reports (not used to write the rules)

| | Recall | Precision |
|---|---:|---:|
| Original notebook | 35% | 57% |
| New rules, **before seeing these reports** (honest held-out score) | **74%** | **75%** |
| After fixing the misses they showed | 89% | 81% |

The middle row is the one to quote: it is how the code did on reports it had never
seen. The last row is no longer a fair test, because those 9 reports were then used
to add rules (the first 50 stayed at 91% / 92%, so nothing regressed).

Fixes from the new reports: "midline shift**s**", "shift of the septum pellucidum",
"partially effaced", "lateral and third ventricles", keys containing "/"
("acute/subacute", "gray/white") were never merged by the phrase matcher,
broken words with a real right half ("hemorrh age"), sinus sentences that also
mention a fracture, normal anatomy said before a negation, acuity of a
tentorial / falcine bleed kept off the convexity, "small volume of ... blood"
not taken as the SDH size, density words about the parenchyma / thyroid not
given to the SDH.

## Test on 13 more new reports (third batch)

| | Recall | Precision |
|---|---:|---:|
| Original notebook | 35% | 58% |
| New rules, **before seeing these reports** | **68%** | **72%** |
| After fixes (incl. phrases supplied by the labeller) | 86% | 80% |

Across the two unseen batches the honest score is about **70-75%** on reports the
rules have never seen. Fixes from this batch: one-line COMPARISON / TECHNIQUE
sections, "-RIGHT: / -LEFT:" list labels, "Right subdural, 1.0 cm", "was 14 mm and is
now 15 mm", "On the left, this measures ...", "mass-effect", "compressed", "bowing of
the midline", "the midline is intact", "panhemispheric", "massive", "falco tentorial",
"interhemispheric fissure", glued side words ("rightinterhemispheric"), soft tissue
hematomas kept out of the SDH, "no hemorrhage in the basilar cisterns" = no SAH,
"history of ..." sentences skipped, facial vs skull fractures, "minimal" as a size,
"mixed densities", "more than one compartment" / "multi septated" = septations,
an acute / high-density part on a low-density or chronic background = acute on
chronic, "subacute and chronic components" = subacute on chronic, de-identification
names in "X-white differentiation", and words between two bleeds in one sentence
given to the right one.

Labelling conventions that differ between the sheets (worth agreeing on):
"No fracture" is `skull_fracture` on the first sheet but `bony_lesion` on the
later ones; `midline_shift_present` is sometimes left blank when a size is given.

## Labelling decisions applied (from the conventions worksheet)

- Fractures use three variables: `bony_lesion` (any fracture = Yes, "No ... fracture" = No),
  `fracture_location` (Calvarial / Skull base / Facial, joined with " + " when several; "No skull
  fracture" or "calvarium intact" = No; "No fracture" with no bone named = NR, cleaned downstream) and
  `fracture_type` (most severe said: Comminuted > Depressed > Displaced > Nondisplaced).
  Older sheets' per-bone columns (`skull_fracture`, `calvarial_ / skullbase_ / facial_fracture_present`)
  are converted to `fracture_location` for scoring.
- Parafalcine / tentorial bleeds are separate from the convexity SDH: their size only goes to
  `parafalcine_ / tentorium_thickness`, and a sentence only about them gives nothing to L_ / R_.
  "This hematoma extends to ... the falx" right after a tentorial bleed is the same bleed.
- Atrophy / microangiopathy / hydrocephalus with no grade = Yes NS.
- A midline shift with a size is at least Yes NS; the adjective directly in front gives the grade.
- Cistern effacement variables removed.

Scores after these changes (old sheets still use some old conventions, e.g. fractures):
first 50: 89% / 91%, second batch: 90% / 81%, third batch: 87% / 81%.

## What the original code did well
- Dictionary + PhraseMatcher tokenising, and the association parser for effects joined by
  "with": mass effect, sulcal / ventricular effacement, subfalcine / uncal herniation and
  midline shift size were mostly right when the SDH was a single, clearly lateralised one.
- Density, convexity / lobe locations, white–grey differentiation and orbits were precise
  (few false positives) when they were found.

## What consistently failed, and the rule that fixes it

| Failure | Rule added (same token-saving style) |
|---|---|
| SDH side = last laterality anywhere in the tree (midline shift "to the right", sinus "left frontal") | **Side scoping** in `SDH_characteristics`: walk children in order, words said before the first side are saved and given to it, a laterality switches the side, "bilateral" gives to both; effects / secondary sentences never set the SDH side |
| A new tree for every wording ("collection" → "hematoma" → "SDH") | One SDH tree per report; `bleed_type()` routes subdural / SAH / IPH / IVH; generic words follow the last bleed named |
| Bilateral SDH dropped entirely | Per-side records, "respectively" pairing, "right … and left …" sharing, overall `laterality` |
| "No A, B or C" only negated A (commas / "or" cut the list) | `parse_negation_branch` reads the whole list: acuity applies to all heads, magnitude / side to the next head, anatomy before or after a head belongs to it |
| Thickness missed in follow-on sentences ("It measures…", "Maximal thickness 14 mm", "This has a maximal depth of 1 cm") | Anaphoric thickness in secondary sentences; parser stops at the second number; "11 x 2.5 cm" keeps the thickness; side taken from the clause |
| `thickness_max` set for "measuring up to" | "up to" is not a maximum (matches the sheet); "thickest", "maximal separation", "largest component" are |
| Severity = last word ("severe generalized" → Yes NS, then "Cerebral atrophy." overwrote it) | `magnitude_function` takes the strongest grade, keeps ranges ("Moderate/ Severe"), "age-related" only when nothing else; array writes are ranked (grade > Yes > No > NR, otherwise first said wins) |
| "with the large … SDH" opened a mass-effect association and swallowed the SDH | A grade only opens an association when it leads to an effect; effect severity only from the adjective in front of it |
| Infarcts all "Yes/No" and often the wrong type | Type from saved modifiers (territory / cortical / lacunar); qualifier from acuity → "No Acute", "No NS", "Yes Chronic" |
| Fractures mapped to `bony_lesion` | `fracture` → `skull_fracture`; "lesion / abnormality" → `bony_lesion`; intact calvarium → both No |
| Sinus sentences leaked into the SDH (and no sinus variables) | `SINUS` bucket + `parse_sinus_sentence` → paranasal / maxillary / sphenoid / ethmoid / mastoid |
| Clinical history / technique text read as findings; glued headings ("reviewFINDINGS") | Preprocessing (split / glued words, "\|"), section filter that ends early when a sentence reports a finding |
| Falx / tentorium SDH not captured | Compartments: `parafalcine_hematoma` / `tentorium_hematoma` with side, thickness and acuity |

## Per field

| Field | Human values | Recall before | Recall after | Precision before | Precision after |
|---|---:|---:|---:|---:|---:|
| `laterality` | 50 | 0% | 92% | – | 94% |
| `L_description` | 18 | 56% | 94% | 77% | 89% |
| `L_acuity` | 22 | 68% | 91% | 79% | 80% |
| `L_mixed_density` | 13 | 69% | 100% | 100% | 100% |
| `L_morphology` | 9 | 33% | 78% | 50% | 78% |
| `L_hyper_dense` | 10 | 50% | 100% | 71% | 91% |
| `L_hypo_dense` | 4 | 50% | 75% | 50% | 75% |
| `L_iso_dense` | 5 | 60% | 100% | 75% | 83% |
| `L_thickness_max` | 13 | 54% | 100% | 47% | 100% |
| `L_thickness` | 32 | 62% | 97% | 87% | 100% |
| `L_convexity_hematoma` | 12 | 67% | 92% | 100% | 100% |
| `L_holohemispheric_hematoma` | 2 | 100% | 100% | 67% | 100% |
| `L_vertex` | 2 | 50% | 50% | 100% | 50% |
| `L_frontal_lobe` | 15 | 60% | 87% | 100% | 100% |
| `L_parietal_lobe` | 10 | 50% | 90% | 62% | 100% |
| `L_temporal_lobe` | 7 | 71% | 86% | 83% | 100% |
| `R_description` | 15 | 60% | 100% | 69% | 88% |
| `R_acuity` | 20 | 65% | 100% | 76% | 95% |
| `R_mixed_density` | 6 | 0% | 100% | 0% | 100% |
| `R_morphology` | 3 | 33% | 100% | 25% | 75% |
| `R_hyper_dense` | 9 | 44% | 89% | 80% | 100% |
| `R_hypo_dense` | 4 | 75% | 75% | 75% | 100% |
| `R_iso_dense` | 4 | 75% | 100% | 75% | 100% |
| `R_thickness_max` | 11 | 36% | 100% | 44% | 100% |
| `R_thickness` | 27 | 41% | 96% | 73% | 100% |
| `R_convexity_hematoma` | 11 | 73% | 91% | 89% | 100% |
| `R_holohemispheric_hematoma` | 4 | 75% | 100% | 100% | 100% |
| `R_vertex` | 2 | 100% | 100% | 100% | 100% |
| `R_frontal_lobe` | 11 | 64% | 91% | 78% | 100% |
| `R_parietal_lobe` | 6 | 67% | 100% | 57% | 86% |
| `R_temporal_lobe` | 1 | 100% | 100% | 50% | 100% |
| `parafalcine_hematoma` | 13 | 0% | 85% | – | 92% |
| `tentorium_hematoma` | 9 | 0% | 89% | – | 100% |
| `mass_effect_present` | 35 | 60% | 86% | 68% | 81% |
| `midline_shift_present` | 37 | 70% | 95% | 76% | 85% |
| `midline_shift` | 33 | 79% | 100% | 100% | 100% |
| `midline_shift_direction` | 27 | 30% | 93% | 33% | 89% |
| `effacement_sulci` | 29 | 62% | 76% | 75% | 85% |
| `effacement_sulci_laterality` | 19 | 63% | 79% | 100% | 88% |
| `effacement_ventricular_system` | 5 | 100% | 100% | 56% | 100% |
| `effacement_lateral_ventricle` | 28 | 50% | 93% | 74% | 96% |
| `l_ventricle_laterality` | 27 | 67% | 100% | 95% | 100% |
| `ventricular_prominence` | 10 | 40% | 80% | 80% | 89% |
| `ex_vacuo_dilatation` | 2 | 50% | 100% | 100% | 67% |
| `effacement_cisterns` | 3 | 33% | 67% | 100% | 50% |
| `herniation_subfalcine` | 17 | 65% | 94% | 92% | 94% |
| `herniation_uncal` | 24 | 58% | 96% | 93% | 100% |
| `herniation_transtentorial` | 8 | 12% | 75% | 100% | 86% |
| `herniation_tonsillar` | 15 | 33% | 93% | 71% | 100% |
| `hydrocephalus` | 13 | 38% | 92% | 83% | 92% |
| `microangiopathy` | 16 | 62% | 81% | 67% | 76% |
| `cerebral_atrophy` | 22 | 50% | 73% | 61% | 94% |
| `white_dark_differentiation` | 7 | 86% | 100% | 86% | 100% |
| `mass` | 10 | 80% | 80% | 80% | 89% |
| `territorial_infarct` | 15 | 7% | 80% | 11% | 80% |
| `lacunar_infarct` | 6 | 33% | 67% | 40% | 57% |
| `unspecified_infarct` | 14 | 7% | 71% | 6% | 71% |
| `bony_lesion` | 23 | 65% | 100% | 60% | 79% |
| `skull_fracture` | 25 | 0% | 96% | – | 100% |
| `scalp_hematoma` | 3 | 67% | 100% | 67% | 75% |
| `soft_tissue_lesion` | 6 | 33% | 83% | 50% | 83% |
| `orbital_lesion` | 14 | 86% | 100% | 100% | 100% |
| `subarachnoid_hemorrhage` | 8 | 0% | 62% | – | 100% |
| `intraparenchymal_hemorrhage` | 10 | 0% | 70% | – | 70% |
| `intraventricular_hemorrhage` | 5 | 0% | 40% | – | 67% |
| `paranasal_sinuses` | 23 | 0% | 96% | – | 96% |
| `mastoid_air_cells` | 24 | 0% | 100% | – | 100% |

## Remaining differences
Most of the ~9% left are places where the human sheet is not consistent with itself,
so a rule that matches one report breaks another, e.g.
- "old infarct" is "Yes NS" in some reports and "Yes Chronic" in others;
- "marked midline shift" is Yes NS but "significant 1.4 cm midline shift" is Severe;
- mass effect is sometimes recorded without the words "mass effect" (from midline shift /
  herniation) and sometimes left NR when "mass effect" is written — inferring it was tested
  and lowered the overall score, so the code only records what is written;
- side-less sulcal effacement is sometimes given the SDH side, usually not — the code only
  uses a side that is written ("left", "ipsilateral", "both").
