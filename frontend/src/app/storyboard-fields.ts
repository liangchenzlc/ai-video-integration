export type Entry = Record<string, unknown>;
export const entries = (value: unknown): Entry[] =>
  Array.isArray(value)
    ? value.filter(
        (x): x is Entry => !!x && typeof x === "object" && !Array.isArray(x),
      )
    : [];
export const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((x): x is string => typeof x === "string")
    : [];
export const value = (input: unknown): string =>
  typeof input === "string" ? input : "";
export const uuid = () => crypto.randomUUID();
export function replaceAt<T>(items: T[], index: number, item: T): T[] {
  return items.map((old, position) => (position === index ? item : old));
}
export function sourceSpan(
  text: string,
  start: number,
  end: number,
  hash: string,
) {
  if (start === end || !hash) return null;
  return {
    sourceHash: hash,
    startCodePoint: Array.from(text.slice(0, start)).length,
    endCodePoint: Array.from(text.slice(0, end)).length,
  };
}
export async function textHash(text: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
