'use strict';

const fs = require('fs');
const path = require('path');

// ── App loader ─────────────────────────────────────────────────────────────────
// Tracks the single keydown handler added by the app so we can remove it before
// each re-load, preventing stale listeners from accumulating on document.
let _appKeydownHandler = null;

function loadApp() {
  if (_appKeydownHandler) {
    document.removeEventListener('keydown', _appKeydownHandler);
    _appKeydownHandler = null;
  }

  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  const bodyContent = bodyMatch ? bodyMatch[1] : html;
  document.body.innerHTML = bodyContent;

  // Intercept addEventListener to capture the keydown handler reference.
  let captured = null;
  const origAdd = document.addEventListener;
  document.addEventListener = function (type, handler, opts) {
    if (type === 'keydown') captured = handler;
    return origAdd.call(this, type, handler, opts);
  };

  const scriptRe = /<script(?:\s[^>]*)?>([^]*?)<\/script>/gi;
  let m;
  while ((m = scriptRe.exec(bodyContent)) !== null) {
    if (m[1].trim()) {
      // eslint-disable-next-line no-new-func
      new Function(m[1])();
    }
  }

  // Restore native addEventListener and save the captured handler for cleanup.
  delete document.addEventListener;
  _appKeydownHandler = captured;
}

// ── Test utilities ─────────────────────────────────────────────────────────────
const q = (tid) => document.querySelector(`[data-testid="${tid}"]`);
const click = (tid) => q(tid).click();
const val = () => q('display-value').textContent;
const expr = () => q('display-expression').textContent;
const key = (k) =>
  document.dispatchEvent(
    new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })
  );

// ── Tests ──────────────────────────────────────────────────────────────────────
describe('Calculator App', () => {
  beforeEach(() => {
    localStorage.clear();
    loadApp();
  });

  // ── Initial state ────────────────────────────────────────────────────────────
  describe('Initial state', () => {
    test('display shows 0 on load', () => {
      expect(val()).toBe('0');
    });

    test('expression is empty on load', () => {
      expect(expr()).toBe('');
    });

    test('history panel is hidden when there is no history', () => {
      expect(q('history-panel').classList.contains('visible')).toBe(false);
    });
  });

  // ── UI elements present ──────────────────────────────────────────────────────
  describe('UI elements present', () => {
    test('display container exists', () => {
      expect(document.getElementById('display')).not.toBeNull();
    });

    test('display-value element exists', () => {
      expect(q('display-value')).not.toBeNull();
    });

    test('display-expression element exists', () => {
      expect(q('display-expression')).not.toBeNull();
    });

    test.each([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])(
      'number button %d exists',
      (n) => expect(q(`btn-${n}`)).not.toBeNull()
    );

    test.each(['add', 'subtract', 'multiply', 'divide'])(
      'operator button %s exists',
      (op) => expect(q(`btn-${op}`)).not.toBeNull()
    );

    test.each(['ac', 'backspace', 'decimal', 'equals', 'percent'])(
      'functional button %s exists',
      (b) => expect(q(`btn-${b}`)).not.toBeNull()
    );

    test('history panel element exists', () => {
      expect(q('history-panel')).not.toBeNull();
    });

    test('history clear button exists', () => {
      expect(q('history-clear')).not.toBeNull();
    });
  });

  // ── Number input ─────────────────────────────────────────────────────────────
  describe('Number input', () => {
    test('pressing a digit shows that digit', () => {
      click('btn-5');
      expect(val()).toBe('5');
    });

    test('pressing multiple digits builds a multi-digit number', () => {
      click('btn-1');
      click('btn-2');
      click('btn-3');
      expect(val()).toBe('123');
    });

    test('initial 0 is replaced by first non-zero digit', () => {
      click('btn-9');
      expect(val()).toBe('9');
    });

    test('pressing 0 when display already shows 0 keeps a single 0', () => {
      click('btn-0');
      expect(val()).toBe('0');
    });

    test('input is capped at 16 characters', () => {
      for (let i = 0; i < 20; i++) click('btn-1');
      expect(val().length).toBeLessThanOrEqual(16);
    });
  });

  // ── Operator buttons ─────────────────────────────────────────────────────────
  describe('Operator buttons', () => {
    test('pressing + after a number moves it to the expression', () => {
      click('btn-5');
      click('btn-add');
      expect(expr()).toContain('5');
      expect(expr()).toContain('+');
    });

    test('pressing − after a number moves it to the expression', () => {
      click('btn-8');
      click('btn-subtract');
      expect(expr()).toContain('8');
      expect(expr()).toContain('-');
    });

    test('pressing × after a number moves it to the expression', () => {
      click('btn-3');
      click('btn-multiply');
      expect(expr()).toContain('3');
      expect(expr()).toContain('×');
    });

    test('pressing ÷ after a number moves it to the expression', () => {
      click('btn-9');
      click('btn-divide');
      expect(expr()).toContain('9');
      expect(expr()).toContain('÷');
    });

    test('pressing operator twice replaces the previous operator', () => {
      click('btn-5');
      click('btn-add');
      click('btn-subtract');
      expect(expr()).not.toContain('+');
      expect(expr()).toContain('-');
    });

    test('pressing an operator with nothing entered does nothing', () => {
      click('btn-add');
      expect(val()).toBe('0');
      expect(expr()).toBe('');
    });
  });

  // ── Arithmetic calculations ──────────────────────────────────────────────────
  describe('Arithmetic calculations', () => {
    test('5 + 3 = 8', () => {
      click('btn-5'); click('btn-add'); click('btn-3'); click('btn-equals');
      expect(val()).toBe('8');
    });

    test('10 − 4 = 6', () => {
      click('btn-1'); click('btn-0');
      click('btn-subtract');
      click('btn-4');
      click('btn-equals');
      expect(val()).toBe('6');
    });

    test('6 × 7 = 42', () => {
      click('btn-6'); click('btn-multiply'); click('btn-7'); click('btn-equals');
      expect(val()).toBe('42');
    });

    test('15 ÷ 3 = 5', () => {
      click('btn-1'); click('btn-5');
      click('btn-divide');
      click('btn-3');
      click('btn-equals');
      expect(val()).toBe('5');
    });

    test('1 ÷ 4 = 0.25 (decimal result)', () => {
      click('btn-1'); click('btn-divide'); click('btn-4'); click('btn-equals');
      expect(val()).toBe('0.25');
    });

    test('division by zero shows Error', () => {
      click('btn-5'); click('btn-divide'); click('btn-0'); click('btn-equals');
      expect(val()).toBe('Error');
    });

    test('pressing = on a single number shows that number', () => {
      click('btn-7'); click('btn-equals');
      expect(val()).toBe('7');
    });

    test('expression shows completed equation including = after evaluation', () => {
      click('btn-3'); click('btn-add'); click('btn-4'); click('btn-equals');
      expect(expr()).toContain('=');
    });

    test('pressing = again after result does not change value', () => {
      click('btn-5'); click('btn-add'); click('btn-3'); click('btn-equals');
      const first = val();
      click('btn-equals');
      expect(val()).toBe(first);
    });

    test('typing a digit after = starts a new fresh input', () => {
      click('btn-5'); click('btn-add'); click('btn-3'); click('btn-equals');
      click('btn-2');
      expect(val()).toBe('2');
    });

    test('chained: 5 + 3 = 8, then + 2 = 10', () => {
      click('btn-5'); click('btn-add'); click('btn-3'); click('btn-equals');
      click('btn-add'); click('btn-2'); click('btn-equals');
      expect(val()).toBe('10');
    });

    test('multi-step: 2 × 3 + 4 = 10 (left-to-right evaluation)', () => {
      click('btn-2'); click('btn-multiply');
      click('btn-3'); click('btn-add');
      click('btn-4'); click('btn-equals');
      expect(val()).toBe('10');
    });
  });

  // ── Clear (AC) ───────────────────────────────────────────────────────────────
  describe('Clear (AC)', () => {
    test('AC resets display to 0', () => {
      click('btn-5'); click('btn-add'); click('btn-3');
      click('btn-ac');
      expect(val()).toBe('0');
    });

    test('AC clears the expression', () => {
      click('btn-5'); click('btn-add');
      click('btn-ac');
      expect(expr()).toBe('');
    });

    test('AC after evaluation resets value and expression', () => {
      click('btn-5'); click('btn-add'); click('btn-3'); click('btn-equals');
      click('btn-ac');
      expect(val()).toBe('0');
      expect(expr()).toBe('');
    });
  });

  // ── Backspace ────────────────────────────────────────────────────────────────
  describe('Backspace', () => {
    test('removes the last digit', () => {
      click('btn-1'); click('btn-2'); click('btn-3');
      click('btn-backspace');
      expect(val()).toBe('12');
    });

    test('backspace on a single digit shows 0', () => {
      click('btn-5');
      click('btn-backspace');
      expect(val()).toBe('0');
    });

    test('backspace after evaluation resets to 0', () => {
      click('btn-5'); click('btn-add'); click('btn-3'); click('btn-equals');
      click('btn-backspace');
      expect(val()).toBe('0');
    });

    test('backspace removes a decimal point', () => {
      click('btn-3'); click('btn-decimal');
      click('btn-backspace');
      expect(val()).toBe('3');
    });
  });

  // ── Decimal input ────────────────────────────────────────────────────────────
  describe('Decimal input', () => {
    test('appends a decimal point to the current number', () => {
      click('btn-3'); click('btn-decimal'); click('btn-1'); click('btn-4');
      expect(val()).toBe('3.14');
    });

    test('prevents a duplicate decimal point in the same number', () => {
      click('btn-3'); click('btn-decimal'); click('btn-decimal'); click('btn-1');
      expect(val()).toBe('3.1');
    });

    test('decimal with no preceding digit prepends 0', () => {
      click('btn-decimal');
      expect(val()).toBe('0.');
    });

    test('1.5 + 2.5 = 4', () => {
      click('btn-1'); click('btn-decimal'); click('btn-5');
      click('btn-add');
      click('btn-2'); click('btn-decimal'); click('btn-5');
      click('btn-equals');
      expect(val()).toBe('4');
    });

    test('decimal after evaluation starts 0.', () => {
      click('btn-5'); click('btn-equals');
      click('btn-decimal');
      expect(val()).toBe('0.');
    });
  });

  // ── Percent ──────────────────────────────────────────────────────────────────
  describe('Percent', () => {
    test('50 → % = 0.5', () => {
      click('btn-5'); click('btn-0'); click('btn-percent');
      expect(val()).toBe('0.5');
    });

    test('100 → % = 1', () => {
      click('btn-1'); click('btn-0'); click('btn-0'); click('btn-percent');
      expect(val()).toBe('1');
    });

    test('25 → % = 0.25', () => {
      click('btn-2'); click('btn-5'); click('btn-percent');
      expect(val()).toBe('0.25');
    });

    test('percent on empty input does nothing', () => {
      click('btn-percent');
      expect(val()).toBe('0');
    });
  });

  // ── Calculation history ──────────────────────────────────────────────────────
  describe('Calculation history', () => {
    test('history panel becomes visible after a calculation', () => {
      click('btn-2'); click('btn-add'); click('btn-3'); click('btn-equals');
      expect(q('history-panel').classList.contains('visible')).toBe(true);
    });

    test('a history item is rendered after a calculation', () => {
      click('btn-4'); click('btn-multiply'); click('btn-5'); click('btn-equals');
      expect(q('history-item-0')).not.toBeNull();
    });

    test('history item displays the result of the calculation', () => {
      click('btn-4'); click('btn-multiply'); click('btn-5'); click('btn-equals');
      expect(q('history-item-0').textContent).toContain('20');
    });

    test('clicking a history item restores its result to the display', () => {
      click('btn-4'); click('btn-multiply'); click('btn-5'); click('btn-equals');
      click('btn-ac');
      q('history-item-0').click();
      expect(val()).toBe('20');
    });

    test('clear-history button empties the history panel', () => {
      click('btn-2'); click('btn-add'); click('btn-3'); click('btn-equals');
      click('history-clear');
      expect(q('history-panel').classList.contains('visible')).toBe(false);
    });

    test('calculation is persisted to localStorage', () => {
      click('btn-3'); click('btn-add'); click('btn-2'); click('btn-equals');
      const stored = JSON.parse(localStorage.getItem('calc_history'));
      expect(stored).not.toBeNull();
      expect(stored.length).toBeGreaterThan(0);
      expect(stored[stored.length - 1].result).toBe('5');
    });

    test('history is restored from localStorage on app init', () => {
      localStorage.setItem(
        'calc_history',
        JSON.stringify([{ expr: '9 + 1 =', result: '10' }])
      );
      loadApp();
      expect(q('history-panel').classList.contains('visible')).toBe(true);
      expect(q('history-item-0')).not.toBeNull();
    });

    test('clearing history writes an empty array to localStorage', () => {
      click('btn-5'); click('btn-add'); click('btn-2'); click('btn-equals');
      click('history-clear');
      expect(JSON.parse(localStorage.getItem('calc_history'))).toEqual([]);
    });

    test('multiple calculations produce multiple history entries', () => {
      click('btn-1'); click('btn-add'); click('btn-2'); click('btn-equals');
      click('btn-ac');
      click('btn-3'); click('btn-add'); click('btn-4'); click('btn-equals');
      expect(q('history-item-0')).not.toBeNull();
      expect(q('history-item-1')).not.toBeNull();
    });

    test('recalled history result can be used in a new calculation', () => {
      click('btn-4'); click('btn-multiply'); click('btn-5'); click('btn-equals');
      q('history-item-0').click();
      click('btn-add');
      click('btn-5');
      click('btn-equals');
      expect(val()).toBe('25');
    });
  });

  // ── Keyboard support ─────────────────────────────────────────────────────────
  describe('Keyboard support', () => {
    test('digit key 7 enters the digit 7', () => {
      key('7');
      expect(val()).toBe('7');
    });

    test('digit key 0 does not duplicate a leading zero', () => {
      key('0');
      expect(val()).toBe('0');
    });

    test('+ key sets the addition operator', () => {
      key('3'); key('+');
      expect(expr()).toContain('+');
    });

    test('- key sets the subtraction operator', () => {
      key('3'); key('-');
      expect(expr()).toContain('-');
    });

    test('* key sets the multiplication operator', () => {
      key('3'); key('*');
      expect(expr()).toContain('×');
    });

    test('/ key sets the division operator', () => {
      key('3'); key('/');
      expect(expr()).toContain('÷');
    });

    test('Enter key evaluates the expression', () => {
      key('5'); key('+'); key('3'); key('Enter');
      expect(val()).toBe('8');
    });

    test('= key evaluates the expression', () => {
      key('6'); key('-'); key('2'); key('=');
      expect(val()).toBe('4');
    });

    test('Backspace key removes the last digit', () => {
      key('1'); key('2'); key('Backspace');
      expect(val()).toBe('1');
    });

    test('Escape key clears the calculator', () => {
      key('5'); key('Escape');
      expect(val()).toBe('0');
    });

    test('Delete key clears the calculator', () => {
      key('5'); key('Delete');
      expect(val()).toBe('0');
    });

    test('. key adds a decimal point', () => {
      key('3'); key('.'); key('1');
      expect(val()).toBe('3.1');
    });

    test('% key applies percent', () => {
      key('5'); key('0'); key('%');
      expect(val()).toBe('0.5');
    });

    test('Ctrl+key combinations are ignored', () => {
      key('5');
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: '3', ctrlKey: true, bubbles: true, cancelable: true })
      );
      expect(val()).toBe('5');
    });

    test('Meta+key combinations are ignored', () => {
      key('5');
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: '3', metaKey: true, bubbles: true, cancelable: true })
      );
      expect(val()).toBe('5');
    });

    test('Alt+key combinations are ignored', () => {
      key('5');
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: '3', altKey: true, bubbles: true, cancelable: true })
      );
      expect(val()).toBe('5');
    });

    test('keyboard: full expression 9 * 9 = 81', () => {
      key('9'); key('*'); key('9'); key('Enter');
      expect(val()).toBe('81');
    });
  });
});
