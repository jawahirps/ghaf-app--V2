export const currency = (value) =>
  new Intl.NumberFormat("en-AE", { style: "currency", currency: "AED", maximumFractionDigits: 0 }).format(
    Number(value || 0)
  );

export const number = (value) => new Intl.NumberFormat("en-US").format(Number(value || 0));

export const percent = (value) => `${Number(value || 0).toFixed(1)}%`;
