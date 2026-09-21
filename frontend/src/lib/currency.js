export function formatMoneyMinor(value, currency = "INR") {
  const amount = Number(value || 0) / 100;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

export function formatMoney(value, currency = "INR") {
  return formatMoneyMinor(Math.round(Number(value || 0) * 100), currency);
}
