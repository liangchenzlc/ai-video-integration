export function parseYuan(value: string): number {
  if (!/^\d+(?:\.\d{1,6})?$/.test(value.trim()))
    throw new Error("金额需为非负数，最多保留六位小数。");
  const [whole, fraction = ""] = value.trim().split(".");
  const micro = BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, "0"));
  if (micro > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error("金额超出可保存范围。");
  return Number(micro);
}
export function formatYuan(value: number): string {
  const micro = BigInt(value);
  const fraction = (micro % 1000000n)
    .toString()
    .padStart(6, "0")
    .replace(/0+$/, "");
  return `${micro / 1000000n}${fraction ? `.${fraction}` : ""}`;
}
