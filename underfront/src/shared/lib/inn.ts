/** Checksum only; a registry match never proves access or legal ownership. */
export function validInn(value: string): boolean {
  if (!/^(?:\d{10}|\d{12})$/.test(value) || /^0+$/.test(value)) return false;
  const check = (weights: number[]) => weights.reduce((sum, weight, i) => sum + weight * Number(value[i]), 0) % 11 % 10;
  return value.length === 10
    ? check([2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(value[9])
    : check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(value[10]) && check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(value[11]);
}
