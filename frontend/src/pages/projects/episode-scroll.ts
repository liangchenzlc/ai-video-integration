export function activeStepIndex(
  tops: readonly number[],
  probeY: number,
  atBottom: boolean,
): number {
  if (!tops.length) return 0;
  if (atBottom) return tops.length - 1;
  let index = 0;
  tops.forEach((top, candidate) => {
    if (top <= probeY) index = candidate;
  });
  return index;
}
