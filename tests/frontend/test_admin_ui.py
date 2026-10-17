"""Real Chromium checks through the frontend's same-origin API proxy."""

import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

import pytest

from tests.backend.test_admin import admin_class as admin_class
from tests.tools.database import quote

playwright = pytest.importorskip(
    "playwright.sync_api", reason="Install Playwright and Chromium for UI checks"
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def classroom_browser(deployment, admin_class, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), API_UPSTREAM=deployment.url)
    with (tmp_path / "frontend.log").open("w") as output:
        server = subprocess.Popen(
            ["node", "frontend/server.mjs"],
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    urllib.request.urlopen(url, timeout=1).close()
                    break
                except OSError:
                    assert time.monotonic() < deadline, "Frontend did not start"
                    time.sleep(0.1)
            with playwright.sync_playwright() as engine:
                browser = engine.chromium.launch()
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                cookie, value = admin_class["teacher"].api.cookie.split("=", 1)
                context.add_cookies(
                    [
                        {
                            "name": cookie,
                            "value": value,
                            "url": url,
                            "httpOnly": True,
                            "sameSite": "Strict",
                        }
                    ]
                )
                context.add_init_script("window.__teacherXss = false;")
                page = context.new_page()
                page.set_default_timeout(10000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                yield page, url, admin_class
                page.screenshot(path=str(tmp_path / "teacher-last.png"), full_page=True)
                assert not errors, errors
                context.close()
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)


def apply_class_filter(page, people):
    page.get_by_label("Course", exact=True).select_option("examples")
    page.get_by_label("Find a student").fill(people["prefix"])
    page.get_by_role("button", name="Apply filters", exact=True).click()


def test_teacher_can_find_students_inspect_reports_and_keep_context(classroom_browser, tmp_path):
    page, url, people = classroom_browser
    expect = playwright.expect
    page.goto(url + "/#admin")
    expect(page.get_by_role("heading", name="Classroom overview")).to_be_visible()
    # Course choices arrive after the initial shell.
    expect(page.locator('#admin-course option[value="examples"]')).to_have_count(1)
    apply_class_filter(page, people)
    active = page.get_by_role("button", name=people["active"].email, exact=True)
    inactive = page.get_by_role("button", name=people["inactive"].email, exact=True)
    expect(active).to_be_visible()
    expect(inactive).to_be_visible()
    expect(active.locator("xpath=ancestor::tr").locator("progress")).to_have_attribute("value", "1")
    expect(active.locator("xpath=ancestor::tr").locator("progress")).to_have_attribute("max", "8")
    expect(
        inactive.locator("xpath=ancestor::tr").get_by_text("No submission", exact=True)
    ).to_be_visible()
    active.click()
    panel = page.locator("#admin-student-panel")
    expect(panel.get_by_role("heading", name=people["active"].email, exact=True)).to_be_visible()
    expect(
        panel.get_by_text("A validation is kept even if a later attempt is unsuccessful.")
    ).to_be_visible()
    panel.get_by_role("button", name="View report").first.click()
    report = page.get_by_role("dialog")
    expect(report.get_by_text("Unsuccessful", exact=True)).to_be_visible()
    expect(report.get_by_text(people["diagnostic"], exact=True)).to_be_visible()
    expect(report.get_by_text("Expected Hello C", exact=True)).to_be_visible()
    expect(report.locator("img")).to_have_count(0)
    assert page.evaluate("window.__teacherXss") is False
    expect(report.get_by_role("link", name="Download submitted workspace")).to_have_count(0)
    page.get_by_role("button", name="Close evaluation report").click()
    search = page.get_by_label("Find a student")
    search.fill("draft email search")
    page.evaluate("window.studentRow = document.querySelector('#admin-panel tbody tr')")
    page.wait_for_timeout(11000)  # Exercise the real background refresh loop.
    expect(search).to_have_value("draft email search")
    assert page.evaluate("window.studentRow === document.querySelector('#admin-panel tbody tr')")
    expect(panel.get_by_role("heading", name=people["active"].email, exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(active).to_be_focused()
    search.fill(people["prefix"])
    page.screenshot(path=str(tmp_path / "teacher-overview.png"), full_page=True)
    page.get_by_role("link", name="Submissions", exact=True).click()
    page.get_by_label("Result", exact=True).select_option("unsuccessful")
    page.get_by_role("button", name="Apply filters", exact=True).click()
    expect(page.locator("#admin-panel tbody tr")).to_have_count(1)
    expect(page.locator("#admin-panel").get_by_text("Unsuccessful", exact=True)).to_be_visible()
    page.get_by_label("Result", exact=True).select_option("error")
    page.get_by_role("button", name="Apply filters", exact=True).click()
    expect(page.locator("#admin-panel tbody tr")).to_have_count(1)
    expect(page.locator("#admin-panel").get_by_text("System error", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("link", name="Class overview", exact=True).click()
    expect(page.get_by_role("button", name=people["inactive"].email, exact=True)).to_be_visible()
    page.get_by_role("button", name=people["inactive"].email, exact=True).click()
    expect(panel.get_by_role("heading", name=people["inactive"].email, exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path / "teacher-mobile-student.png"))
    page.get_by_role("button", name="Close student details").click()
    expect(panel).to_be_hidden()


def test_closed_student_panel_ignores_a_late_request_error(classroom_browser):
    page, url, people = classroom_browser
    page.goto(url + "/#admin/overview")
    playwright.expect(page.locator('#admin-course option[value="examples"]')).to_have_count(1)
    apply_class_filter(page, people)
    pending = []

    def delay_student_lookup(route):
        if "user_id=" in route.request.url:
            pending.append(route)
        else:
            route.continue_()

    page.route("**/api/v1/admin/students?*", delay_student_lookup)
    page.get_by_role("button", name=people["active"].email, exact=True).click()
    panel = page.locator("#admin-student-panel")
    playwright.expect(panel.get_by_role("heading", name="Loading student…")).to_be_visible()
    page.get_by_role("button", name="Close student details").click()
    playwright.expect(panel).to_be_hidden()
    assert len(pending) == 1
    pending[0].fulfill(status=503, json={"detail": "Late student lookup failure"})
    page.wait_for_timeout(250)  # Let the completed request reach its error handler.
    playwright.expect(page.get_by_text("Late student lookup failure", exact=False)).to_have_count(0)
    playwright.expect(page.locator("#admin-error")).to_be_hidden()


def test_teacher_can_stop_a_workspace(classroom_browser, deployment):
    page, url, people = classroom_browser
    # Remove the synthetic queued submission before starting a real workspace.
    deployment.db.execute(f"DELETE FROM evaluations WHERE id={quote(people['records']['grading'])}")
    people["active"].start("hello-c")
    page.goto(url + "/#admin/environments")
    playwright.expect(page.locator('#admin-course option[value="examples"]')).to_have_count(1)
    apply_class_filter(page, people)
    playwright.expect(
        page.locator("#admin-panel").get_by_text("Workspace running", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Stop workspace", exact=True).click()
    people["active"].wait_environment("stopped")
    page.get_by_role("button", name="Refresh", exact=True).click()
    playwright.expect(
        page.get_by_text("There are no active workspaces matching these filters.")
    ).to_be_visible()


def test_student_cannot_open_teacher_pages(classroom_browser):
    page, url, people = classroom_browser
    page.context.clear_cookies()
    name, value = people["inactive"].api.cookie.split("=", 1)
    page.context.add_cookies(
        [{"name": name, "value": value, "url": url, "httpOnly": True, "sameSite": "Strict"}]
    )
    page.goto(url + "/#admin")
    playwright.expect(page.locator("#nav-admin")).to_be_hidden()
    playwright.expect(page.get_by_role("heading", name="DevOps Modules")).to_be_visible()
    playwright.expect(page.locator("#admin-panel")).to_have_count(0)
