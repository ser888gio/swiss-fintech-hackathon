export function hashShort(h: string): string {
  return `${h.slice(0, 10)}…`;
}

export function money(v: number | string): string {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return isNaN(n)
    ? String(v)
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
