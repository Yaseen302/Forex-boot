/** Do not guess a broker's instrument or show another instrument under its label. */
export function initialSymbol(symbols: string[], preferred = 'EURUSD'): string {
  if (symbols.includes(preferred)) return preferred;
  const suffixes = symbols.filter(symbol => /^EURUSD(?:m|c|r|pro|raw|zero|\.[A-Za-z0-9]+)$/i.test(symbol));
  return suffixes.length === 1 ? suffixes[0] : '';
}

export function candleResponseMatches(response: {symbol: string; timeframe: string}, symbol: string, timeframe: string): boolean {
  return response.symbol === symbol && response.timeframe === timeframe;
}
