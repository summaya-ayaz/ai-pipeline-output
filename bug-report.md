# QA Report — SCRUM-3

**Deployment:** https://project-42up2-hkmof4j0v-summaya-ayazs-projects.vercel.app

## Result table
| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Counter initially displays `0` inside `data-testid="counter-value"` | PASS | qa/01-initial-load.png |
| 2 | Page has a visible `<h1>` heading containing "Counter" | PASS | qa/01-initial-load.png |
| 3 | `data-testid="increment-btn"` increases the counter by 1 | PASS | qa/03-after-increment.png |
| 4 | `data-testid="decrement-btn"` decreases the counter by 1 | PASS | qa/04-after-decrement.png |
| 5 | `data-testid="reset-btn"` sets the counter back to 0 | PASS | qa/05-after-reset.png |
| 6 | Counter value persists across reloads via `localStorage` key `counter` | PASS | qa/06-after-reload-persistence.png |

## Browser console errors
None observed.

## Screenshots
- `qa/01-initial-load.png` — Initial page load showing counter at 0.
- `qa/02-post-clear-reload.png` — Page state after clearing localStorage and reloading.
- `qa/03-after-increment.png` — Counter state after clicking the increment button.
- `qa/04-after-decrement.png` — Counter state after clicking the decrement button.
- `qa/05-after-reset.png` — Counter state after clicking the reset button.
- `qa/06-after-reload-persistence.png` — Counter state after reload, verifying localStorage persistence.

## Summary
All six acceptance criteria for the Counter App passed automated verification against the live deployment. The counter initializes at 0, the increment, decrement, and reset buttons behave correctly, the `<h1>` heading is present, and the counter value persists across page reloads via the `counter` localStorage key. No browser console errors or page errors were observed during the run.

## OVERALL
OVERALL: PASS
