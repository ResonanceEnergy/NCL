# Wave 14W-F backlog — F7 synthesis

8 P0 items, 12 P1, 12 P2. P0 directly retires all 4 of NATRIX's stated
complaints.

## P0 — Ship this session

1. **P0-1** Add timestamps to surfaces with data — OptionsFlowView,
   RotationRRG, NightWatch, MorningQuiz, GOAT/BRAVO scan timing, Position
   rows. Apply existing FSFormat.relativeTime. Impact 5, effort S.
2. **P0-2** Delete 7 ad-hoc "time ago" impls, use FSFormat everywhere.
   Impact 4, effort S.
3. **P0-3** Add tab + sub-tab mandate subtitles via new FSSectionHeader.
   AGENDA/BRIEF/NIGHTWATCH/FOCUS get their mandates from F4. Impact 5,
   effort S.
4. **P0-4** Unify Intel signal-card pattern (delete signalRow inline,
   route through IntelSignalCard sheet). Impact 5, effort M.
5. **P0-5** Wire PositionDetailSheet (orphan sheet → tap sheet). Impact
   4, effort S.
6. **P0-6** Make fake-tappable surfaces work or stop pretending: LifePlan
   rows, RotationRRG sector dots, Calendar CITIES rows, green broker
   chips. Impact 4, effort S.
7. **P0-7** Scrub 6 internal codename strings: "M3 harness",
   "/intelligence/digest", "bounce brain", "Page-Hinkley", "Awarebot
   ticks", lane refactor history. Impact 4, effort S.
8. **P0-8** Retire News sub-tab + 4 Journal ghost enum cases + reorder
   Intel so AGENDA first. Impact 3, effort S.

## NATRIX's complaints → backlog mapping

- "no time stamps" → P0-1, P0-2
- "some clickable some not" → P0-4, P0-5, P0-6
- "hard to read / understand" → P0-7 + jargon glossary in P1
- "agenda/brief/nightwatch/focus needs mandate" → P0-3 + F9 mandate docs

(Full P1/P2 backlog in synthesizer report — see commit_msg.)
