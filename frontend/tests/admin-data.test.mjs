import test from "node:test";
import assert from "node:assert/strict";
import { outcome, outcomes, requestQuery, adminHref, offsetOf, progressPercent, filteredQuery } from "../public/js/admin-data.js";

test("a completed unsuccessful submission is distinct from a system error", () => {
  assert.equal(outcome({ status: "completed", is_success: false }), "unsuccessful");
  assert.equal(outcome({ status: "completed", is_success: true }), "validated");
  assert.equal(outcome({ status: "failed", is_success: false }), "error");
  assert.equal(outcome({ status: "running", is_success: false }), "grading");
  assert.equal(outcome({ status: "timeout" }), "timeout");
  assert.equal(outcome(null), "none");
  assert.equal(outcomes.none[0], "No submission");
});

test("only supported filters reach the API; panel state stays in the URL", () => {
  const query = new URLSearchParams({ search: "a+b@example.test", course_id: "examples", student: "123", student_offset: "10", outcome: "unsuccessful" });
  const api = requestQuery(query, ["search", "course_id", "outcome"], { limit: 25, offset: 0 });
  assert.equal(api.get("search"), "a+b@example.test");
  assert.equal(api.has("student"), false);
  assert.equal(api.has("student_offset"), false);
  const url = adminHref("overview", query, { offset: 25 });
  const stored = new URLSearchParams(url.split("?")[1]);
  assert.equal(stored.get("student"), "123");
  assert.equal(stored.get("search"), "a+b@example.test");
  assert.equal(stored.get("offset"), "25");
  assert.equal(query.has("offset"), false);
  assert.equal(adminHref("overview", query, { student: null }).includes("student=123"), false);
});

test("empty courses and malformed pagination cannot produce invalid progress or offsets", () => {
  assert.equal(progressPercent(0, 0), 0);
  assert.equal(progressPercent(1, 8), 13);
  assert.equal(progressPercent(9, 8), 100);
  for (const value of ["-1", "Infinity", "1.5", "bad", "9007199254740992"]) assert.equal(offsetOf(value), 0);
  assert.equal(offsetOf("25"), 25);
});

test("changing filters preserves the selected student and resets both paginations", () => {
  const query = new URLSearchParams({ user_id: "student-1", student: "student-1", offset: 25, student_offset: 10, search: "old", status: "running" });
  const filtered = filteredQuery(query, { search: " new ", course_id: "examples", outcome: "validated" });
  assert.equal(filtered.get("user_id"), "student-1");
  assert.equal(filtered.get("student"), "student-1");
  assert.equal(filtered.get("search"), "new");
  assert.equal(filtered.has("offset"), false);
  assert.equal(filtered.has("student_offset"), false);
  assert.equal(filtered.has("status"), false);
});
