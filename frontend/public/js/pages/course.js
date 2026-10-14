import { $, apiCall, cloneTemplate, formatDate, showMessage, state } from "../core.js";

const difficultyNames = {
  warmup: "WARM-UP // GETTING STARTED", easy: "LEVEL // EASY",
  medium: "LEVEL // MEDIUM", hard: "LEVEL // HARD",
};

function exerciseTile(exercise) {
  const tile = cloneTemplate("template-exercise-tile");
  const field = name => tile.querySelector(`[data-field="${name}"]`);
  tile.classList.toggle("completed", exercise.completed);
  tile.href = `#exercises/${encodeURIComponent(exercise.id)}`;
  field("id").textContent = exercise.id.toUpperCase();
  field("name").textContent = exercise.name;
  field("status").className = `status-badge-${exercise.completed ? "completed" : "pending"}`;
  field("status").textContent = exercise.available === false ? "UNAVAILABLE" : exercise.completed ? "PASSED ✓" : "PENDING";
  return tile;
}

function difficultySection(difficulty, exercises) {
  const section = cloneTemplate("template-difficulty-section");
  section.querySelector(".difficulty-title").textContent = difficultyNames[difficulty] || difficulty.toUpperCase();
  section.querySelector(".exercises-grid").replaceChildren(...exercises.map(exerciseTile));
  return section;
}

export async function loadCourseDetailView(courseId) {
  const titleEl = $("course-title");
  const deadlineEl = $("course-deadline-badge");
  const container = $("course-exercises-container");
  const version = state.routeVersion;
  const user = state.user;
  const isCurrent = () => version === state.routeVersion && user === state.user;
  titleEl.textContent = "";
  deadlineEl.replaceChildren();
  showMessage(container, "Loading module...");
  try {
    const course = await apiCall(`/api/v1/courses/${encodeURIComponent(courseId)}`);
    if (!isCurrent()) return;
    titleEl.textContent = course.name;
    const deadline = document.createElement("span");
    deadline.className = "mono-meta";
    deadline.textContent = `DEADLINE // ${formatDate(course.deadline)}`;
    deadlineEl.replaceChildren(deadline);
    const sections = Object.entries(course.exercises_by_difficulty)
      .filter(([, exercises]) => exercises?.length)
      .map(([difficulty, exercises]) => difficultySection(difficulty, exercises));
    container.replaceChildren(...sections);
  } catch (err) {
    if (isCurrent()) showMessage(container, err.message, "alert alert-error");
  }
}
