import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

async function loadModule(file) {
  const source = await fs.readFile(new URL(file, import.meta.url), 'utf8');
  const {outputText} = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}});
  return import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
}
const {sma, ema, bollinger, rsi, macd} = await loadModule('../src/indicators.ts');
const {initialSymbol, candleResponseMatches} = await loadModule('../src/market.ts');
const samples = values => values.map((close, i) => ({time: 1_700_000_000 + i * 60, close}));
const approx = (actual, expected, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) < tolerance, `${actual} differs from ${expected}`);

test('SMA uses a complete lookback and EMA starts at its complete SMA seed', () => {
  const values = samples([1, 2, 3, 4, 5, 6]);
  assert.deepEqual(sma(values, 3).map(p => p.value), [2, 3, 4, 5]);
  assert.equal(sma(values, 3)[0].time, values[2].time);
  assert.deepEqual(ema(values, 3).map(p => p.value), [2, 3, 4, 5]);
  ema(samples([2, 4, 8, 10, 20]), 3).forEach((point, i) => approx(point.value, [14 / 3, 22 / 3, 41 / 3][i]));
  assert.deepEqual(sma(values, 7), []);
});

test('Bollinger fixture has a known population deviation and does not emit warm-up bands', () => {
  const values = bollinger(samples([2, 4, 4, 4, 5, 5, 7, 9]), 8, 2);
  assert.equal(values.length, 1);
  assert.equal(values[0].middle, 5);
  assert.equal(values[0].upper, 9);
  assert.equal(values[0].lower, 1);
});

test('Wilder RSI matches the published 14-period calculation example', () => {
  const closes = [44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.00,46.03,46.41,46.22,45.64,46.21];
  const values = rsi(samples(closes), 14);
  approx(values[0].value, 70.4641350211, 1e-8);
  approx(values[1].value, 66.2496185536, 1e-8);
  assert.equal(rsi(samples(Array(20).fill(10)), 14)[0].value, 50);
  assert.equal(rsi(samples(Array.from({length: 20}, (_, i) => i + 1)), 14)[0].value, 100);
  assert.equal(rsi(samples(Array.from({length: 20}, (_, i) => 20 - i)), 14)[0].value, 0);
});

test('MACD of a linear trend is its exact EMA lag difference and starts signal after its own warm-up', () => {
  const values = macd(samples(Array.from({length: 50}, (_, i) => i + 1)), 12, 26, 9);
  assert.equal(values.length, 25);
  values.forEach(p => approx(p.macd, 7));
  assert.equal(values[7].signal, undefined);
  approx(values[8].signal, 7);
  approx(values[8].histogram, 0);
  const constant = macd(samples(Array(40).fill(100)));
  constant.forEach(p => assert.equal(p.macd, 0));
});

test('indicators reject invalid periods, invalid prices, and non-chronological input', () => {
  assert.throws(() => sma(samples([1, 2]), 0), RangeError);
  assert.throws(() => ema(samples([1, 2]), 1.5), RangeError);
  assert.throws(() => bollinger(samples([1, 2]), 2, 0), RangeError);
  assert.throws(() => rsi(samples([1, NaN]), 2), RangeError);
  assert.throws(() => sma([{time: 1, close: 2}, {time: 1, close: 3}], 2), RangeError);
  assert.throws(() => macd(samples([1, 2]), 26, 12, 9), RangeError);
});

test('indicator histories are causal when later prices change', () => {
  const prices = samples(Array.from({length: 80}, (_, i) => 100 + Math.sin(i) * 2 + i * .2));
  for (const calculate of [p => sma(p, 14), p => ema(p, 14), p => bollinger(p, 20), p => rsi(p, 14), p => macd(p)]) {
    const past = calculate(prices.slice(0, 60));
    const changed = prices.map((p, i) => i < 60 ? p : {...p, close: 10000});
    assert.deepEqual(calculate(changed).filter(p => p.time <= prices[59].time), past);
  }
});

test('broker selection preserves exact symbols and requires a choice when suffixes are ambiguous', () => {
  assert.equal(initialSymbol(['XAUUSD', 'EURUSDm']), 'EURUSDm');
  assert.equal(initialSymbol(['EURUSDm', 'EURUSD']), 'EURUSD');
  assert.equal(initialSymbol(['EURUSDm', 'EURUSDc']), '');
  assert.equal(initialSymbol(['GBPUSD', 'XAUUSD']), '');
  assert.equal(initialSymbol(['EURUSDJPY']), '');
  assert.equal(candleResponseMatches({symbol: 'EURUSDm', timeframe: 'H4'}, 'EURUSDm', 'H4'), true);
  assert.equal(candleResponseMatches({symbol: 'EURUSD', timeframe: 'H4'}, 'EURUSDm', 'H4'), false);
});
