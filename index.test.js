/**
 * @jest-environment jsdom
 */
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function extractBody(htmlText) {
  const match = htmlText.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  return match ? match[1] : htmlText;
}

function extractScripts(htmlText) {
  const scripts = [];
  const re = /<script\b[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(htmlText)) !== null) {
    scripts.push(m[1]);
  }
  return scripts;
}

function loadApp() {
  const bodyContent = extractBody(html);
  // Strip script tags from body so they don't get parsed as text-only
  const bodyWithoutScripts = bodyContent.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  document.body.innerHTML = bodyWithoutScripts;

  const scripts = extractScripts(html);
  for (const code of scripts) {
    // eslint-disable-next-line no-new-func
    new Function(code).call(window);
  }
}

describe('Counter App', () => {
  let alertSpy;
  let confirmSpy;
  let promptSpy;

  beforeEach(() => {
    document.body.innerHTML = '';
    localStorage.clear();
    alertSpy = jest.spyOn(window, 'alert').mockImplementation(() => {});
    confirmSpy = jest.spyOn(window, 'confirm').mockImplementation(() => true);
    promptSpy = jest.spyOn(window, 'prompt').mockImplementation(() => '');
  });

  afterEach(() => {
    alertSpy.mockRestore();
    confirmSpy.mockRestore();
    promptSpy.mockRestore();
  });

  test('renders an h1 with the text "Counter"', () => {
    loadApp();
    const h1 = document.querySelector('h1');
    expect(h1).not.toBeNull();
    expect(h1.textContent).toMatch(/Counter/);
  });

  test('displays initial counter value of 0', () => {
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    expect(counter).not.toBeNull();
    expect(counter.textContent.trim()).toBe('0');
  });

  test('increment button increases the counter by 1', () => {
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    expect(incBtn).not.toBeNull();
    incBtn.click();
    expect(counter.textContent.trim()).toBe('1');
    incBtn.click();
    incBtn.click();
    expect(counter.textContent.trim()).toBe('3');
  });

  test('decrement button decreases the counter by 1', () => {
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');
    expect(decBtn).not.toBeNull();
    decBtn.click();
    expect(counter.textContent.trim()).toBe('-1');
    decBtn.click();
    expect(counter.textContent.trim()).toBe('-2');
  });

  test('reset button sets the counter back to 0', () => {
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    const resetBtn = document.querySelector('[data-testid="reset-btn"]');
    expect(resetBtn).not.toBeNull();
    incBtn.click();
    incBtn.click();
    incBtn.click();
    expect(counter.textContent.trim()).toBe('3');
    resetBtn.click();
    expect(counter.textContent.trim()).toBe('0');
  });

  test('increment then decrement returns to original value', () => {
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');
    incBtn.click();
    incBtn.click();
    decBtn.click();
    expect(counter.textContent.trim()).toBe('1');
  });

  test('persists counter value to localStorage under key "counter"', () => {
    loadApp();
    const incBtn = document.querySelector('[data-testid="increment-btn"]');
    incBtn.click();
    incBtn.click();
    expect(localStorage.getItem('counter')).toBe('2');
  });

  test('restores counter value from localStorage on reload', () => {
    localStorage.setItem('counter', '7');
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    expect(counter.textContent.trim()).toBe('7');
  });

  test('persists decremented value across reloads', () => {
    loadApp();
    const decBtn = document.querySelector('[data-testid="decrement-btn"]');
    decBtn.click();
    decBtn.click();
    decBtn.click();
    expect(localStorage.getItem('counter')).toBe('-3');

    // Simulate reload: wipe DOM but keep localStorage
    document.body.innerHTML = '';
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    expect(counter.textContent.trim()).toBe('-3');
  });

  test('reset persists 0 to localStorage', () => {
    localStorage.setItem('counter', '42');
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    expect(counter.textContent.trim()).toBe('42');
    const resetBtn = document.querySelector('[data-testid="reset-btn"]');
    resetBtn.click();
    expect(counter.textContent.trim()).toBe('0');
    expect(localStorage.getItem('counter')).toBe('0');
  });

  test('handles invalid localStorage value by defaulting to 0', () => {
    localStorage.setItem('counter', 'not-a-number');
    loadApp();
    const counter = document.querySelector('[data-testid="counter-value"]');
    expect(counter.textContent.trim()).toBe('0');
  });

  test('all required testid elements exist', () => {
    loadApp();
    expect(document.querySelector('[data-testid="counter-value"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="increment-btn"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="decrement-btn"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="reset-btn"]')).not.toBeNull();
  });
});
