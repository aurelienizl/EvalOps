/** Escape values interpolated into HTML text or quoted attributes. */
export const escapeHtml = text => String(text ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
})[char]);
