"""Rendered readability, keyboard isolation, and reflow across workspace pages."""

from pathlib import Path
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

from test_workspace_loading import CAPABILITIES, loading_browser, loading_server, wait_for  # noqa: F401
from test_workspace_data_layout import data_page, open_page, click  # noqa: F401
from test_workspace_shell import open_chat
from test_workspace_conversation_graph import saved_network, open_saved
from test_projects_and_connectors import collaboration_browser, login  # noqa: F401


@pytest.fixture
def zoom_browser():
    root = Path("/snap/firefox/current/usr/lib/firefox")
    if not (root / "firefox").is_file() or not (root / "geckodriver").is_file():
        pytest.skip("Firefox and geckodriver are required for the browser gate")
    options = Options()
    options.add_argument("-headless")
    # Set real browser page zoom through Firefox chrome, not CSS transforms.
    options.enable_bidi = True
    options.binary_location = str(root / "firefox")
    browser = webdriver.Firefox(options=options, service=Service(executable_path=str(root / "geckodriver"), service_args=["--allow-system-access"]))
    try:
        yield browser
    finally:
        browser.quit()


TEXT_AUDIT = """
const rgba = value => value.match(/[\\d.]+/g).map(Number);
const blend = (front, back) => front.slice(0, 3).map((v, i) => v * (front[3] ?? 1) + back[i] * (1 - (front[3] ?? 1)));
const luminance = color => color.slice(0, 3).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
const issues = [];
for (const element of document.querySelectorAll('body *')) {
  if (!(element instanceof HTMLElement) || element.closest('script,style,option,[aria-hidden="true"],[inert],.visually-hidden,.sr-only') || !element.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})) continue;
  const text = [...element.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join('').trim();
  if (!text || element.closest(':disabled')) continue;
  const style = getComputedStyle(element), parents = [];
  for (let parent = element; parent; parent = parent.parentElement) parents.unshift(parent);
  if (parents.some(p => Number(getComputedStyle(p).opacity) !== 1)) continue;
  const background = parents.reduce((color, p) => blend(rgba(getComputedStyle(p).backgroundColor), color), [255,255,255]);
  const foreground = blend(rgba(style.color), background), light = [luminance(foreground), luminance(background)].sort((a,b) => a-b);
  const contrast = (light[1] + .05) / (light[0] + .05), size = parseFloat(style.fontSize);
  const large = size >= 24 || size >= 18.6667 && parseInt(style.fontWeight) >= 700;
  if (size < 14 || contrast < (large ? 3 : 4.5)) issues.push({element:element.id || element.className, text:text.slice(0,60), size, contrast});
}
return issues;
"""


def assert_readable(browser):
    assert browser.execute_script(TEXT_AUDIT) == []


def assert_no_horizontal_overflow(browser):
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("width", [320, 1440])
def test_home_and_conversation_text_contrast_and_control_targets(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    server.responses[0].release.set()
    browser.get(server.url)
    wait_for(browser, "document.querySelector('.domain-card') && !GraphMineWorkspace.state.busy")
    assert_readable(browser)
    assert_no_horizontal_overflow(browser)
    open_chat(browser, server)
    assert_readable(browser)
    assert_no_horizontal_overflow(browser)
    sizes = browser.execute_script("return [...document.querySelectorAll('.workspace-nav a, .chat-heading-actions button, .composer-actions button')].filter(e => e.checkVisibility()).map(e => ({id:e.id || e.textContent, width:e.getBoundingClientRect().width, height:e.getBoundingClientRect().height}))")
    minimum = 44 if width == 320 else 40
    assert all(item["width"] >= minimum and item["height"] >= minimum for item in sizes), sizes
    browser.save_screenshot(f"/tmp/graphmine-accessibility-chat-{width}.png")


@pytest.mark.parametrize("width", [320, 1440])
def test_data_page_labels_controls_and_preview_contrast(loading_browser, loading_server, data_page, width):
    browser = loading_browser
    open_page(browser, loading_server, width)
    assert_readable(browser)
    if width == 320:
        click(browser, "data-step-query")
    assert_readable(browser)
    editor = browser.find_element(By.ID, "cypher-editor")
    editor.click()
    assert browser.execute_script("return parseFloat(getComputedStyle(arguments[0]).fontSize)", editor) >= (16 if width == 320 else 14)
    click(browser, "preview-cypher")
    wait_for(browser, "document.getElementById('database-preview-count').textContent.includes('2 nodes')")
    assert_readable(browser)
    assert_no_horizontal_overflow(browser)
    browser.save_screenshot(f"/tmp/graphmine-accessibility-data-{width}.png")


def test_modal_drawers_isolate_background_and_restore_keyboard_focus(loading_browser, loading_server):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 390, "height": 844})
    open_chat(browser, loading_server)
    trigger = browser.find_element(By.ID, "toggle-tools")
    trigger.send_keys(Keys.ENTER)
    assert browser.execute_script("return document.getElementById('chat-content').inert && document.getElementById('app-sidebar').inert && !document.getElementById('data-sidebar').closest('[inert]')")
    browser.execute_script("document.getElementById('question').focus()")
    assert browser.execute_script("return document.getElementById('data-sidebar').contains(document.activeElement)")
    assert_readable(browser)
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert browser.switch_to.active_element == trigger
    assert browser.execute_script("return !document.querySelector('[inert]')")
    browser.find_element(By.ID, "toggle-sidebar").send_keys(Keys.ENTER)
    browser.switch_to.active_element.send_keys(Keys.SHIFT, Keys.TAB)
    assert browser.execute_script("return document.getElementById('app-sidebar').contains(document.activeElement)")
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert browser.switch_to.active_element.get_attribute("id") == "toggle-sidebar"
    assert browser.execute_script("return !document.querySelector('[inert]')")


def test_data_tabs_and_editor_have_visible_keyboard_focus(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server, 320)
    browser.execute_script("document.querySelector('.skip-link').focus()")
    browser.switch_to.active_element.send_keys(Keys.ENTER)
    assert browser.switch_to.active_element.get_attribute("id") == "data-workspace-view"
    browser.execute_script("document.getElementById('data-step-connection').focus()")
    browser.switch_to.active_element.send_keys(Keys.ARROW_RIGHT)
    assert browser.switch_to.active_element.get_attribute("id") == "data-step-query"
    browser.switch_to.active_element.send_keys(Keys.TAB)
    assert browser.switch_to.active_element.get_attribute("id") == "data-query-pane"
    # Walk the actual tab order to the editor without a mouse or a script focus.
    for _ in range(20):
        if browser.switch_to.active_element.get_attribute("id") == "cypher-editor":
            break
        browser.switch_to.active_element.send_keys(Keys.TAB)
    assert browser.switch_to.active_element.get_attribute("id") == "cypher-editor"
    assert browser.execute_script("return getComputedStyle(document.activeElement).outlineStyle !== 'none' && parseFloat(getComputedStyle(document.activeElement).outlineWidth) >= 2")
    browser.switch_to.active_element.send_keys(" // keyboard draft")
    assert not data_page.queries


def test_real_browser_zoom_keeps_query_drafts_and_chat_usable(zoom_browser, loading_server, data_page):
    browser, server = zoom_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 1280, "height": 1024})
    browser.get(server.url + "/#data/query")
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")
    editor = browser.find_element(By.ID, "cypher-editor")
    editor.send_keys(" // retained while zooming")
    for zoom in [2, 4]:
        with browser.context(browser.CONTEXT_CHROME):
            browser.execute_script("ZoomManager.zoom = arguments[0]", zoom)
        wait_for(browser, f"innerWidth <= {1280 / zoom} + 1")
        assert_no_horizontal_overflow(browser)
        assert browser.execute_script("return document.getElementById('database-workspace').dataset.step") == "query"
        assert editor.get_attribute("value").endswith("// retained while zooming")
        assert_readable(browser)
    click(browser, "preview-cypher")
    wait_for(browser, "document.getElementById('run-cypher-chat')?.disabled === false")
    click(browser, "run-cypher-chat")
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat' && !GraphMineWorkspace.state.busy")
    question = browser.find_element(By.ID, "question")
    question.send_keys("I can still ask about my graph")
    assert_no_horizontal_overflow(browser)
    assert question.get_attribute("value") == "I can still ask about my graph"
    assert len(data_page.queries) == 1
    question.clear(); question.send_keys("/")
    assert browser.execute_script("return getComputedStyle(document.getElementById('command-menu')).position === 'static'")
    question.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
    assert question.get_attribute("value") == "/feedback "
    assert browser.execute_script("const r=document.getElementById('question').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight")
    browser.save_screenshot("/tmp/graphmine-accessibility-zoom-400.png")


def test_reduced_motion_and_forced_colors_keep_controls_distinct(zoom_browser, loading_server):
    browser = zoom_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 390, "height": 844})
    with browser.context(browser.CONTEXT_CHROME):
        browser.execute_script("Services.prefs.setIntPref('ui.prefersReducedMotion', 1); Services.prefs.setIntPref('browser.display.document_color_use', 2);")
    open_chat(browser, loading_server)
    wait_for(browser, "matchMedia('(prefers-reduced-motion: reduce)').matches && matchMedia('(forced-colors: active)').matches")
    assert browser.execute_script("return getComputedStyle(document.getElementById('conversation-scroll')).scrollBehavior === 'auto' && getComputedStyle(document.getElementById('plan-question')).transitionDuration === '0s'")
    assert browser.execute_script("const s = getComputedStyle(document.querySelector('[data-mode=normal]')); return s.borderStyle === 'solid' && parseFloat(s.borderWidth) >= 2")
    browser.execute_script("document.getElementById('composer-data').focus()")
    browser.switch_to.active_element.send_keys(Keys.TAB)
    assert browser.execute_script("const s = getComputedStyle(document.activeElement); return s.outlineStyle === 'solid' && parseFloat(s.outlineWidth) >= 2 && s.outlineColor !== s.backgroundColor")
    assert_no_horizontal_overflow(browser)


def test_resizing_modal_drawer_restores_background_and_existing_inert_state(loading_browser, loading_server):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 390, "height": 844})
    open_chat(browser, loading_server)
    browser.execute_script("document.getElementById('domain-view').inert = true")
    click(browser, "toggle-tools")
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 1440, "height": 900})
    wait_for(browser, "!document.getElementById('chat-content').inert")
    assert browser.find_element(By.ID, "data-sidebar").get_attribute("aria-modal") is None
    browser.find_element(By.ID, "question").send_keys("The desktop conversation is available")
    click(browser, "toggle-tools")
    assert browser.execute_script("return document.getElementById('domain-view').inert && document.querySelectorAll('[inert]').length === 1")


def test_location_points_select_results_with_enter_and_space(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    profile = {"kind": "locations", "title": "Estimated locations"}
    capabilities = deepcopy(CAPABILITIES)
    capabilities["operations"].append({"id": "graph-geolocation", "title": "Locations", "input_kind": "graph", "execution": {"cpu": True, "gpu": False}, "parameters": {}, "visualization": profile})
    server.workflows[0]["validation"]["plan"]["steps"][0]["operation"] = "graph-geolocation"
    result = server.results["saved-analysis"]["steps"]["core"]["result"]
    result.update(operation="graph-geolocation", ports={"locations": {"type": "coordinates", "complete": True, "value": [
        {"vertex": 1, "location": {"longitude": -70, "latitude": 40}},
        {"vertex": "1", "location": {"longitude": -60, "latitude": 50}},
    ]}})
    selections = []

    def route(handler, method):
        path = urlsplit(handler.path).path
        if method == "GET" and path == "/api/analytics/capabilities":
            handler.respond(capabilities)
            return True
        if method == "GET" and path.endswith("/view"):
            query = parse_qs(urlsplit(handler.path).query)
            index = int(query["index"][0]) if "index" in query else None
            selections.append(index)
            handler.respond({**server.graph, "graph_available": True, "enrichable": False, "index": index, "context": False,
                             "step": "core", "port": "locations", "item_count": 2, "selected_vertices": [] if index is None else [1 if index == 0 else "1"],
                             "selected_edges": [], "profile": profile, "complete": True, "note": "Recorded locations"})
            return True
        return False

    server.route_handler = route
    open_saved(browser, server, "results")
    wait_for(browser, "document.querySelectorAll('#result-building-block circle[role=button]').length === 2")
    assert browser.find_element(By.CSS_SELECTOR, "#result-building-block svg").get_attribute("role") == "group"
    for index, key in [(0, Keys.ENTER), (1, Keys.SPACE)]:
        point = browser.find_elements(By.CSS_SELECTOR, "#result-building-block circle")[index]
        assert "longitude" in point.get_attribute("aria-label")
        browser.execute_script("arguments[0].focus()", point)
        point.send_keys(key)
        wait_for(browser, f"GraphMineWorkspace.state.resultView?.index === {index} && document.activeElement.dataset.locationIndex === '{index}'")
        assert selections[-1] == index


def test_authenticated_settings_keep_readable_text_and_small_screen_navigation(collaboration_browser):
    browser, base, sid, *_ = collaboration_browser
    wait = login(browser, base, path=f"/#workspace/{sid}/chat")
    wait.until(lambda d: d.execute_script("return GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy"))
    assert_readable(browser)
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 320, "height": 760})
    assert browser.execute_script("return innerWidth") == 320
    assert_no_horizontal_overflow(browser)
    account = browser.find_element(By.ID, "account-settings-button")
    assert account.get_attribute("aria-label") == "Account settings for alice"
    assert browser.find_element(By.ID, "data-page-link").is_displayed()
    account.send_keys(Keys.ENTER)
    wait.until(lambda d: d.find_element(By.ID, "account-quota").text)
    assert_readable(browser)
    usage = browser.find_element(By.ID, "account-tab-usage")
    usage.send_keys(Keys.ARROW_RIGHT)
    assert browser.switch_to.active_element.get_attribute("id") == "account-tab-profile"
    assert_readable(browser)
    assert browser.execute_script("const e=document.querySelector('.account-settings-content'); return e.scrollWidth <= e.clientWidth")
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert browser.switch_to.active_element == account
    assert_no_horizontal_overflow(browser)


@pytest.mark.parametrize("page", ["chat", "data", "results"])
def test_small_zoom_equivalent_viewport_reflows_without_losing_actions(loading_browser, loading_server, data_page, page):
    browser, server = loading_browser, loading_server
    # 1280x1024 at 400% page zoom yields this CSS viewport. Browser zoom itself
    # is checked separately; this case also covers a short mobile viewport.
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 320, "height": 256})
    if page == "data":
        browser.get(server.url + "/#data/query")
        wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")
        click(browser, "preview-cypher")
        wait_for(browser, "document.getElementById('run-cypher-chat')?.disabled === false")
        target = browser.find_element(By.ID, "run-cypher-chat")
    elif page == "results":
        saved_network(server)
        open_saved(browser, server, "results")
        target = browser.find_element(By.ID, "back-to-chat")
    else:
        open_chat(browser, server)
        target = browser.find_element(By.ID, "question")
        target.send_keys("A question at high zoom")
    assert_readable(browser)
    assert_no_horizontal_overflow(browser)
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", target)
    assert browser.execute_script("const r=arguments[0].getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight + 1", target)
    assert target.is_displayed() and target.is_enabled()

