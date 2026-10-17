// Small, shared rules for teacher-facing results, filters and progress.
export const outcomes = {
  validated: ["Validated", "success"],
  unsuccessful: ["Unsuccessful", "warning"],
  grading: ["Grading", "info"],
  timeout: ["Timed out", "danger"],
  error: ["System error", "danger"],
  none: ["No submission", "muted"],
};

export function outcome(row) {
  if (!row?.status) return "none";
  if (row.status === "running") return "grading";
  if (row.status === "timeout") return "timeout";
  if (row.status === "failed") return "error";
  if (row.status === "completed") return row.is_success ? "validated" : "unsuccessful";
  return "none";
}

export function offsetOf(value) {
  const offset = Number(value);
  return Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
}

export function requestQuery(query, keys, extra = {}) {
  const result = new URLSearchParams();
  for (const key of keys) {
    const value = query.get(key);
    if (value) result.set(key, value);
  }
  for (const [key, value] of Object.entries(extra)) result.set(key, value);
  return result;
}

export function adminHref(tab, query = new URLSearchParams(), changes = {}) {
  const params = new URLSearchParams(query);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === "") params.delete(key);
    else params.set(key, value);
  }
  const suffix = params.toString();
  return `#admin/${tab}${suffix ? "?" + suffix : ""}`;
}

export function progressPercent(validated, total) {
  return total > 0 ? Math.min(100, Math.max(0, Math.round(validated / total * 100))) : 0;
}

export function filteredQuery(current, values) {
  const query = requestQuery(current, ["user_id", "exercise_id", "student"]);
  for (const key of ["course_id", "search", "outcome"]) {
    const value = values[key]?.trim();
    if (value) query.set(key, value);
  }
  return query;
}
