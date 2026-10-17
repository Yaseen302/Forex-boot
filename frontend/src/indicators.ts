/** Closed-candle indicators. Warm-up samples are omitted, never padded or future-filled. */
export type PriceSample = {time: number; close: number};
export type IndicatorPoint = {time: number; value: number};
export type BollingerPoint = {time: number; middle: number; upper: number; lower: number};
export type MacdPoint = {time: number; macd: number; signal?: number; histogram?: number};

function validate(samples: PriceSample[], period: number): void {
  if (!Number.isInteger(period) || period < 1) throw new RangeError('Period must be a positive integer');
  if (samples.some((s, i) => !Number.isFinite(s.close) || !Number.isFinite(s.time) || (i > 0 && s.time <= samples[i - 1].time))) {
    throw new RangeError('Indicator samples must be finite and strictly chronological');
  }
}

export function sma(samples: PriceSample[], period: number): IndicatorPoint[] {
  validate(samples, period);
  let total = 0;
  const result: IndicatorPoint[] = [];
  samples.forEach((sample, i) => {
    total += sample.close;
    if (i >= period) total -= samples[i - period].close;
    if (i >= period - 1) result.push({time: sample.time, value: total / period});
  });
  return result;
}

/** EMA starts with the first complete SMA seed, the conventional charting definition. */
export function ema(samples: PriceSample[], period: number): IndicatorPoint[] {
  validate(samples, period);
  if (samples.length < period) return [];
  let value = samples.slice(0, period).reduce((sum, s) => sum + s.close, 0) / period;
  const result = [{time: samples[period - 1].time, value}];
  const alpha = 2 / (period + 1);
  for (let i = period; i < samples.length; i++) {
    value += alpha * (samples[i].close - value);
    result.push({time: samples[i].time, value});
  }
  return result;
}

/** Population deviation, matching standard Bollinger Bands. */
export function bollinger(samples: PriceSample[], period: number, deviations = 2): BollingerPoint[] {
  validate(samples, period);
  if (!Number.isFinite(deviations) || deviations <= 0) throw new RangeError('Deviation multiplier must be positive');
  return sma(samples, period).map((point, index) => {
    const window = samples.slice(index, index + period);
    const variance = window.reduce((sum, s) => sum + (s.close - point.value) ** 2, 0) / period;
    const width = deviations * Math.sqrt(variance);
    return {time: point.time, middle: point.value, upper: point.value + width, lower: point.value - width};
  });
}

/** Wilder smoothing; a flat series is neutral (50), with no losses is 100. */
export function rsi(samples: PriceSample[], period: number): IndicatorPoint[] {
  validate(samples, period);
  if (samples.length <= period) return [];
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = samples[i].close - samples[i - 1].close;
    gains += Math.max(change, 0);
    losses += Math.max(-change, 0);
  }
  gains /= period;
  losses /= period;
  const strength = () => losses === 0 ? (gains === 0 ? 50 : 100) : 100 - 100 / (1 + gains / losses);
  const result = [{time: samples[period].time, value: strength()}];
  for (let i = period + 1; i < samples.length; i++) {
    const change = samples[i].close - samples[i - 1].close;
    gains = (gains * (period - 1) + Math.max(change, 0)) / period;
    losses = (losses * (period - 1) + Math.max(-change, 0)) / period;
    result.push({time: samples[i].time, value: strength()});
  }
  return result;
}

export function macd(samples: PriceSample[], fast = 12, slow = 26, signalPeriod = 9): MacdPoint[] {
  validate(samples, fast);
  validate(samples, slow);
  validate(samples, signalPeriod);
  if (fast >= slow) throw new RangeError('MACD fast period must be below slow period');
  const fastValues = new Map(ema(samples, fast).map(p => [p.time, p.value]));
  const line = ema(samples, slow).map(p => ({time: p.time, close: fastValues.get(p.time)! - p.value}));
  const signals = new Map(ema(line, signalPeriod).map(p => [p.time, p.value]));
  return line.map(p => {
    const signal = signals.get(p.time);
    return {time: p.time, macd: p.close, ...(signal === undefined ? {} : {signal, histogram: p.close - signal})};
  });
}

export type IndicatorSettings = {
  ema: boolean; emaPeriod: number;
  sma: boolean; smaPeriod: number;
  bands: boolean; bandsPeriod: number; bandsDeviation: number;
  rsi: boolean; rsiPeriod: number;
  macd: boolean; macdFast: number; macdSlow: number; macdSignal: number;
  zones: boolean;
};

export const defaultIndicators: IndicatorSettings = {
  ema: true, emaPeriod: 20, sma: false, smaPeriod: 50,
  bands: false, bandsPeriod: 20, bandsDeviation: 2,
  rsi: false, rsiPeriod: 14, macd: false, macdFast: 12, macdSlow: 26, macdSignal: 9, zones: true,
};
