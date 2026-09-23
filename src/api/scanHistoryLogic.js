function normalizeScan(row) {
  const rawValue = row.estimated_value;
  const value = rawValue == null || String(rawValue).trim() === ""
    ? null : Number(rawValue);
  return {
    id: row.id,
    coin: row.coin_name?.trim() || [row.year, row.country, row.denomination].filter(v => v != null && v !== "").join(" ") || "Unidentified coin",
    time: row.scanned_at || row.created_at || null,
    value: Number.isFinite(value) ? value : null,
  };
}

function groupScansByCoin(scans) {
  const groups = new Map();
  for (const scan of scans) {
    const group = groups.get(scan.coin) || { count: 0, totalValue: 0, valuedCount: 0 };
    group.count += 1;
    if (scan.value !== null && Number.isFinite(scan.value)) {
      group.totalValue += scan.value;
      group.valuedCount += 1;
    }
    groups.set(scan.coin, group);
  }
  return [...groups.entries()].sort((a, b) => b[1].count - a[1].count);
}

function formatScanValue(value) {
  return value === null ? "Value unavailable" : "~$" + value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

module.exports = { normalizeScan, groupScansByCoin, formatScanValue };
