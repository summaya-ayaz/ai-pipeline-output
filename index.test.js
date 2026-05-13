'use strict';

const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf-8');

function loadApp() {
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  const bodyContent = bodyMatch ? bodyMatch[1] : '';

  document.body.innerHTML = bodyContent;

  // Re-execute inline script blocks so the IIFE wires up event listeners against the fresh DOM
  const scriptRegex = /<script(?![^>]*\bsrc\b)[^>]*>([\s\S]*?)<\/script>/gi;
  let match;
  while ((match = scriptRegex.exec(bodyContent)) !== null) {
    const code = match[1];
    if (code && code.trim()) {
      // new Function shares the jsdom global scope without polluting the test scope
      // eslint-disable-next-line no-new-func
      new Function(code)();
    }
  }
}

describe('Counter App', () => {
  beforeEach(() => {
    localStorage.clear();
    loadApp();
  });

  // AC: h1 heading contains text "Counter"
  test('page has a visible <h1> heading containing the text "Counter"', () => {
    const h1 = document.querySelector('h1');
    expect(h1).not.toBeNull();
    expect(h1.textContent).toContain('Counter');
  });

  // AC: counter-value element exists and starts at 0
  test('element with data-testid="counter-value" exists and shows 0 initially', () => {
    const display = document.querySelector('[data-testid="counter-value"]');
    expect(display).not.toBeNull();
    expect(display.textContent).toBe('0');
  });

  // AC: increment button increases counter by 1
  test('increment-btn increases the counter by 1 on each click', () => {
    const display = document.querySelector('[data-testid="counter-value"]');
    const incBtn = document.querySelector('[data-testid="increment-btn"]');

    expect(incBtn).not.toBeNull();

    incBtn.click();
    expect(display.textContent).toBe('1');

    incBtn.click();
    expect(display.textContent).toBe('2');

    incBtn.click();
    expect(display.textContent).toBe('3');
  });

  // AC: decrement button decreases counter by 1
  test('decrement-btn decreases the counter by 1 on each click', () => {
    const display = document.querySelector('[data-testid="counter-value"]');
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');

    expect(decBtn).not.toBeNull();

    decBtn.click();
    expect(display.textContent).toBe('-1');

    decBtn.click();
    expect(display.textContent).toBe('-2');
  });

  // AC: reset button sets counter back to 0
  test('reset-btn sets the counter back to 0 after incrementing', () => {
    const display = document.querySelector('[data-testid="counter-value"]');
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    const resetBtn = document.querySelector('[data-testid="reset-btn"]');

    expect(resetBtn).not.toBeNull();

    incBtn.click();
    incBtn.click();
    incBtn.click();
    expect(display.textContent).toBe('3');

    resetBtn.click();
    expect(display.textContent).toBe('0');
  });

  test('reset-btn sets the counter back to 0 after decrementing', () => {
    const display = document.querySelector('[data-testid="counter-value"]');
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');
    const resetBtn = document.querySelector('[data-testid="reset-btn"]');

    decBtn.click();
    decBtn.click();
    expect(display.textContent).toBe('-2');

    resetBtn.click();
    expect(display.textContent).toBe('0');
  });

  // AC: counter persists across reloads via localStorage key "counter"
  test('increment writes the updated value to localStorage["counter"]', () => {
    const incBtn = document.querySelector('[data-testid="increment-btn"]');

    incBtn.click();
    expect(localStorage.getItem('counter')).toBe('1');

    incBtn.click();
    expect(localStorage.getItem('counter')).toBe('2');
  });

  test('decrement writes the updated value to localStorage["counter"]', () => {
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');

    decBtn.click();
    expect(localStorage.getItem('counter')).toBe('-1');
  });

  test('reset writes "0" to localStorage["counter"]', () => {
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    const resetBtn = document.querySelector('[data-testid="reset-btn"]');

    incBtn.click();
    incBtn.click();
    resetBtn.click();

    expect(localStorage.getItem('counter')).toBe('0');
  });

  test('counter reads a positive persisted value from localStorage on load (simulates reload)', () => {
    localStorage.setItem('counter', '42');
    loadApp();

    expect(document.querySelector('[data-testid="counter-value"]').textContent).toBe('42');
  });

  test('counter reads a negative persisted value from localStorage on load', () => {
    localStorage.setItem('counter', '-7');
    loadApp();

    expect(document.querySelector('[data-testid="counter-value"]').textContent).toBe('-7');
  });

  test('counter defaults to 0 when localStorage contains a non-numeric value', () => {
    localStorage.setItem('counter', 'not-a-number');
    loadApp();

    expect(document.querySelector('[data-testid="counter-value"]').textContent).toBe('0');
  });

  // Combined flow: all criteria exercised together
  test('combined increment / decrement / reset flow stays consistent with localStorage', () => {
    const display = document.querySelector('[data-testid="counter-value"]');
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');
    const resetBtn = document.querySelector('[data-testid="reset-btn"]');

    incBtn.click(); // 1
    incBtn.click(); // 2
    decBtn.click(); // 1
    incBtn.click(); // 2
    incBtn.click(); // 3
    expect(display.textContent).toBe('3');
    expect(localStorage.getItem('counter')).toBe('3');

    resetBtn.click(); // 0
    expect(display.textContent).toBe('0');
    expect(localStorage.getItem('counter')).toBe('0');

    decBtn.click(); // -1
    expect(display.textContent).toBe('-1');
    expect(localStorage.getItem('counter')).toBe('-1');
  });
});
