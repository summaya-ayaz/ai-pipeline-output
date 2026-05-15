# QA Report — SCRUM-5

**Deployment:** https://project-42up2-glyaj6f03-summaya-ayazs-projects.vercel.app

## Result table
| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Page has a visible `<h1>` heading containing the text "Counter" | PASS | `qa/01-initial-load.png` |
| 2 | Counter is initially `0` inside `data-testid="counter-value"` | PASS | `qa/01-initial-load.png` |
| 3 | Increment button (`data-testid="increment-btn"`) increases counter by 1 | PASS | `qa/02-after-increment.png` |
| 4 | Decrement button (`data-testid="decrement-btn"`) decreases counter by 1 | PASS | `qa/03-after-decrement.png` |
| 5 | Reset button (`data-testid="reset-btn"`) sets counter back to 0 | PASS | `qa/04-after-reset.png` |
| 6 | Counter value persists across page reloads via `localStorage` key `counter` | PASS | `qa/05-after-reload.png` |

## Browser console errors
None observed.

## Screenshots
- `qa/01-initial-load.png` — Page on first load; counter displays 0 and the "Counter" heading is visible.
- `qa/02-after-increment.png` — Counter after one click of the increment button; value updated to 1.
- `qa/03-after-decrement.png` — Counter after one click of the decrement button; value decremented correctly.
- `qa/04-after-reset.png` — Counter after clicking the reset button; value returned to 0.
- `qa/05-after-reload.png` — Counter value after a full page reload; localStorage persistence confirmed.

## Summary
All six acceptance criteria defined in `requirements.md` passed without issue. The counter initialises to 0, increments and decrements correctly by 1, resets to 0 on demand, and survives a page reload via `localStorage`. No browser console errors or page errors were recorded during the run.

## OVERALL
`OVERALL: PASS`
