import { $, apiCall, cloneTemplate, formatDate, showMessage, state } from "../core.js";

function courseCard(course) {
  const card = cloneTemplate("template-course-card");
  const field = name => card.querySelector(`[data-field="${name}"]`);
  card.href = `#courses/${encodeURIComponent(course.id)}`;
  field("id").textContent = `MODULE // ${course.id.toUpperCase()}`;
  field("name").textContent = course.name;
  field("status").className = `tag ${course.completed ? "tag-status" : "tag-points"}`;
  field("status").textContent = course.available === false ? "UNAVAILABLE" : course.completed ? "COMPLETED ✓" : `${course.progress.completed}/${course.progress.total} PASSED`;
  field("deadline").textContent = `DEADLINE // ${formatDate(course.deadline)}`;
  const percent = course.progress.total > 0 ? Math.round(course.progress.completed / course.progress.total * 100) : 0;
  field("progress").style.width = `${percent}%`;
  field("score").textContent = `${course.score.earned} / ${course.score.maximum} PTS`;
  return card;
}

export async function loadCoursesView() {
  const container = $("courses-list");
  const version = state.routeVersion;
  const user = state.user;
  const isCurrent = () => version === state.routeVersion && user === state.user;
  showMessage(container, "Loading modules...");
  try {
    const data = await apiCall("/api/v1/courses");
    if (!isCurrent()) return;
    if (data.courses.length === 0) {
      showMessage(container, "No modules available.");
      return;
    }
    container.replaceChildren(...data.courses.map(courseCard));
  } catch (err) {
    if (isCurrent()) showMessage(container, err.message, "alert alert-error");
  }
}
