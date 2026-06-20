export function hashShort(h: string): string {
  return `${h.slice(0, 10)}…`;
}

export function money(v: number | string): string {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return isNaN(n)
    ? String(v)
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const currencyFormatters = new Map<string, Intl.NumberFormat>();
const tokenFormatters = new Map<number, Intl.NumberFormat>();

export function formatMoney(amount: number | string, currency = "USD"): string {
  const value = Number(amount);
  const safeValue = Number.isFinite(value) ? value : 0;
  const maximumFractionDigits = safeValue % 1 === 0 ? 0 : 2;
  const normalizedCurrency = currency.trim().toUpperCase() || "USD";

  // Intl currency identifiers are exactly three letters. Ledger asset codes such
  // as RLUSD are tokens, so format their amount as a number and append the code.
  if (!/^[A-Z]{3}$/.test(normalizedCurrency)) {
    let formatter = tokenFormatters.get(maximumFractionDigits);
    if (!formatter) {
      formatter = new Intl.NumberFormat("en-US", { maximumFractionDigits });
      tokenFormatters.set(maximumFractionDigits, formatter);
    }
    return `${formatter.format(safeValue)} ${normalizedCurrency}`;
  }

  const key = `${normalizedCurrency}:${maximumFractionDigits}`;
  let formatter = currencyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: normalizedCurrency,
      maximumFractionDigits,
    });
    currencyFormatters.set(key, formatter);
  }
  return formatter.format(safeValue);
}
