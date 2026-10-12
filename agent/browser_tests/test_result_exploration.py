"""Browser checks use authored outputs; they do not evaluate a native solver."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from graphmine_agent.analysis import (
    apply_narrative,
    prepare_analysis,
    validate_narrative,
)
from graphmine_agent.answers import answer_interpretation, build_answer
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    GroundedNarrative,
    GroundedStatement,
    ResultRecord,
    VegaLiteDraft,
    VisualizationSpec,
)
from graphmine_agent.reporting import render_report
from graphmine_agent.visualization import answer_visualizations

pytest.importorskip("selenium")
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


@pytest.fixture
def browser():
    root = Path("/snap/firefox/current/usr/lib/firefox")
    firefox = (
        str(root / "firefox")
        if (root / "firefox").is_file()
        else shutil.which("firefox")
    )
    geckodriver = (
        str(root / "geckodriver")
        if (root / "geckodriver").is_file()
        else shutil.which("geckodriver")
    )
    if not firefox or not geckodriver:
        pytest.skip("Firefox and geckodriver are required for the browser gate")
    options = Options()
    options.add_argument("-headless")
    options.binary_location = firefox
    driver = webdriver.Firefox(
        options=options, service=Service(executable_path=geckodriver)
    )
    driver.set_window_size(1440, 1000)
    try:
        yield driver
    finally:
        driver.quit()


def answer_for(graph, operation, output):
    return build_answer(
        graph,
        ExecutionPlan(
            session_id="fixture",
            graph_id="fixture",
            operation_id=operation,
            problem_id="presentation_fixture",
            application_intent=ApplicationIntent(
                objective="Explore the computed answer"
            ),
        ),
        {"output": output},
        source_hash="authored-browser-fixture",
    )


def open_report(browser, tmp_path, answer, views=None):
    result = ResultRecord(
        job_id="fixture",
        session_id="fixture",
        operation_id=answer["operation_id"],
        payload={"provenance": {"authored_browser_fixture": True}},
        summary={},
        answer=answer,
        interpretation=answer_interpretation(
            answer, views or answer_visualizations(answer)
        ),
    )
    path = tmp_path / "answer.html"
    path.write_text(render_report(result))
    browser.get(path.as_uri())
    WebDriverWait(browser, 30).until(
        lambda driver: driver.find_elements(By.CLASS_NAME, "table-entity")
    )


def card(browser, name):
    return browser.find_element(By.CSS_SELECTOR, f'.viz-card[data-view-id="{name}"]')


def network_selection(browser, name):
    return browser.execute_script(
        "return arguments[0].querySelector('.answer-network').graphmineNetwork.nodes(':selected').map(node => node.id())",
        card(browser, name),
    )


def test_custom_composed_charts_explanations_linking_and_offline_export(
    browser, tmp_path
):
    graph = {
        "graph": {"id": "custom-chart", "directed": False},
        "vertices": [
            {
                "id": index,
                "label": label,
                "type": "employee",
                "attributes": {"department": department},
            }
            for index, label, department in [
                (0, "Ari", "Design"),
                (1, "Bo", "Design"),
                (2, "Cam", "Support"),
            ]
        ],
        "edges": [
            {"id": "ab", "source": 0, "target": 1},
            {"id": "bc", "source": 1, "target": 2},
        ],
    }
    answer = prepare_analysis(
        answer_for(
            graph, "maximal-cliques", {"cliques": [[0, 1], [1, 2]], "complete": True}
        )
    )
    fid = answer["facts"][0]["id"]
    overview = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "hconcat": [
            {
                "width": 220,
                "height": 180,
                "data": {"name": "groups"},
                "mark": "bar",
                "encoding": {
                    "x": {"field": "group", "type": "nominal"},
                    "y": {
                        "field": "size",
                        "type": "quantitative",
                        "scale": {"zero": True},
                    },
                },
            },
            {
                "width": 180,
                "height": 180,
                "data": {"name": "overlap"},
                "mark": "rect",
                "encoding": {
                    "x": {"field": "group_a", "type": "nominal"},
                    "y": {"field": "group_b", "type": "nominal"},
                    "color": {"field": "shared", "type": "quantitative"},
                },
            },
        ],
    }
    people = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"name": "members"},
        "width": 400,
        "height": 150,
        "mark": {"type": "point", "filled": True, "size": 150},
        "encoding": {
            "x": {"field": "attribute_department", "type": "nominal"},
            "y": {"field": "label", "type": "nominal"},
            "tooltip": [{"field": "label"}, {"field": "attribute_department"}],
        },
    }
    draft = GroundedNarrative(
        fact_ids=[fid],
        summary=GroundedStatement(
            text="Read the returned groups together with their membership overlap.",
            fact_ids=[fid],
        ),
        findings=[
            GroundedStatement(
                text="The membership comparison describes the returned groups; it does not measure employee performance.",
                fact_ids=[fid],
            )
        ],
        charts=[
            VegaLiteDraft(
                title="Groups and shared membership",
                description="Sizes and shared membership among returned groups, including self-overlap on the diagonal.",
                spec_json=json.dumps(overview),
                fact_ids=[fid],
            ),
            VegaLiteDraft(
                title="People by recorded department",
                description="Select a person to inspect their returned memberships and connections.",
                spec_json=json.dumps(people),
                fact_ids=[fid],
            ),
        ],
    )
    defaults = answer_visualizations(answer)
    views = validate_narrative(draft, answer, defaults, {"maximal-cliques"}) + defaults
    interpretation = apply_narrative(
        answer_interpretation(answer, views), draft, answer
    )
    result = ResultRecord(
        job_id="fixture",
        session_id="fixture",
        operation_id="maximal-cliques",
        payload={"provenance": {"authored_browser_fixture": True}},
        summary={},
        answer=answer,
        interpretation=interpretation,
    )
    report = tmp_path / "rich-analysis.html"
    report.write_text(render_report(result))
    browser.get(report.as_uri())
    WebDriverWait(browser, 30).until(
        lambda driver: (
            len(driver.find_elements(By.CSS_SELECTOR, ".vega-chart svg.marks")) == 2
            or driver.find_elements(By.CSS_SELECTOR, "[data-render-error]")
        )
    )
    errors = browser.find_elements(By.CSS_SELECTOR, "[data-render-error]")
    assert not errors, [node.get_attribute("data-render-error") for node in errors]
    assert (
        "employee performance"
        in browser.find_element(By.CLASS_NAME, "analysis-explanation").text
    )
    assert "Computed findings" in browser.find_element(By.ID, "interpretation").text
    points = card(browser, "custom_1").find_elements(
        By.CSS_SELECTOR, ".mark-symbol.role-mark path"
    )
    assert len(points) == 3
    points[0].click()
    WebDriverWait(browser, 5).until(
        lambda driver: len(network_selection(driver, "network")) == 1
    )
    keys = browser.execute_script(
        "return arguments[0].querySelector('.vega-chart').graphmineVega.signal('graphmine_selection')",
        card(browser, "custom_1"),
    )
    assert len(keys) == 1
    browser.execute_script(
        "arguments[0].click()",
        card(browser, "custom_1").find_element(By.CSS_SELECTOR, "button.text-button"),
    )
    WebDriverWait(browser, 5).until(
        lambda driver: not network_selection(driver, "network")
    )
    svg = browser.execute_async_script(
        "const done=arguments[arguments.length-1]; arguments[0].querySelector('.vega-chart').graphmineVega.toSVG().then(done);",
        card(browser, "custom_1"),
    )
    assert "<svg" in svg and "Ari" in svg and "Design" in svg
    assert (
        card(browser, "custom_0").find_element(By.CLASS_NAME, "viz-kind").text.lower()
        == "custom chart"
    )
    assert card(browser, "custom_0").rect["width"] > (
        browser.find_element(By.ID, "visualizations").rect["width"] * 0.9
    )
    browser.set_window_size(390, 844)
    chart = card(browser, "custom_0").find_element(By.CLASS_NAME, "vega-chart")
    WebDriverWait(browser, 5).until(
        lambda _: (
            card(browser, "custom_0")
            .find_element(By.CLASS_NAME, "chart-scroll-hint")
            .is_displayed()
        )
    )
    # Wide composed charts retain their authored text size instead of shrinking
    # the entire SVG to a narrow phone viewport. The chart itself can scroll.
    assert browser.execute_script(
        "const svg=arguments[0].querySelector('svg.marks'); return Math.abs(svg.getBoundingClientRect().width - svg.width.baseVal.value) < 1;",
        chart,
    )
    browser.execute_script("arguments[0].focus()", chart)
    chart.send_keys(Keys.ARROW_RIGHT)
    WebDriverWait(browser, 5).until(
        lambda _: browser.execute_script("return arguments[0].scrollLeft > 0", chart)
    )
    browser.save_screenshot(str(tmp_path / "rich-analysis-mobile.png"))
    assert browser.execute_script(
        "return document.documentElement.scrollWidth <= window.innerWidth + 1"
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_search_and_pagination_reach_rows_outside_both_preview_caps(
    browser, tmp_path, legacy
):
    graph = {
        "graph": {"id": "large", "directed": False},
        "vertices": [
            {
                "id": f"employee-{i:04}",
                "label": f"Employee {i:04}",
                "type": "employee",
                "attributes": {"department": "Support" if i >= 1000 else "Design"},
            }
            for i in range(1205)
        ],
        "edges": [],
    }
    answer = answer_for(
        graph,
        "maximal-cliques",
        {"cliques": [[f"employee-{i:04}"] for i in range(1205)], "complete": True},
    )
    assert len(answer["tables"]["members"]) == 1000
    assert len(answer["network"]["nodes"]) == 500
    views = answer_visualizations(answer)
    next(view for view in views if view.id == "groups").filters = [
        {"field": "Department", "operator": "eq", "value": "Support"}
    ]
    if legacy:
        answer["tables"].pop("columns")
        for group in answer["groups"]:
            group.pop("member_keys")
        for view in views:
            view.encodings.pop("answer_ref", None)
            view.encodings.pop("table", None)
    open_report(browser, tmp_path, answer, views)
    wait = WebDriverWait(browser, 20)
    members, groups = card(browser, "members"), card(browser, "groups")
    assert len(members.find_elements(By.CSS_SELECTOR, "tbody tr")) == 50
    assert "highest 20 of 1205 entries" in card(browser, "group_sizes").text
    assert (
        "1205 available rows"
        in members.find_element(By.CLASS_NAME, "table-status").text
    )
    wait.until(
        lambda _: (
            "205 matches across 1205 available rows"
            in groups.find_element(By.CLASS_NAME, "table-status").text
        )
    )
    assert "Employee 1000" in groups.text
    members.find_element(By.CLASS_NAME, "last-page").click()
    assert len(members.find_elements(By.CSS_SELECTOR, "tbody tr")) == 5
    assert "Employee 1204" in members.text
    search = members.find_element(By.CLASS_NAME, "viz-filter")
    search.send_keys("Employee 1204")
    wait.until(
        lambda _: (
            "1 matches across 1205"
            in members.find_element(By.CLASS_NAME, "table-status").text
        )
    )
    members.find_element(By.CLASS_NAME, "table-entity").send_keys(Keys.ENTER)
    assert network_selection(browser, "network") == []
    assert "1 outside this preview" in card(browser, "network").text
    assert (
        "Employee 1204"
        in card(browser, "network").find_element(By.CLASS_NAME, "entity-details").text
    )
    assert (
        members.find_element(By.CLASS_NAME, "table-entity").get_attribute(
            "aria-pressed"
        )
        == "true"
    )
    assert browser.execute_script(
        "return document.activeElement.classList.contains('table-entity')"
    )
    search.clear()
    search.send_keys("not present anywhere")
    wait.until(
        lambda _: (
            "No matching rows"
            in members.find_element(By.CLASS_NAME, "table-status").text
        )
    )
    assert not members.find_element(By.CLASS_NAME, "next-page").is_enabled()
    assert not browser.execute_script(
        "return performance.getEntriesByType('resource').some(item => item.name.startsWith('http'))"
    )


def test_linked_views_preserve_typed_ids_and_analysis_scope(browser, tmp_path):
    large_id = 2**53
    graph = {
        "graph": {"id": "typed", "directed": False},
        "vertices": [
            {"id": identifier, "label": label}
            for identifier, label in [
                (1, "Alpha"),
                ("1", "Beta"),
                (2, "Gamma"),
                (large_id, "Large A"),
                (large_id + 1, "Large B"),
            ]
        ],
        "edges": [
            {"id": 0, "source": 1, "target": "1"},
            {"id": 1, "source": "1", "target": 2},
            {"id": 2, "source": large_id, "target": large_id + 1},
        ],
    }
    groups = answer_for(
        graph,
        "maximal-cliques",
        {"cliques": [[1, "1"], ["1", 2], [large_id, large_id + 1]], "complete": False},
    )
    ranking = answer_for(
        {**graph, "graph": {"id": "typed", "directed": True}},
        "betweenness-centrality",
        {
            "score_by_vertex": [
                {"vertex": 1, "score": 0},
                {"vertex": "1", "score": 1},
                {"vertex": 2, "score": 0},
                {"vertex": large_id, "score": 0},
                {"vertex": large_id + 1, "score": 0},
            ],
            "complete": True,
        },
    )
    answer = {
        **ranking,
        "steps": {"a": groups, "b": ranking},
        "facts": [
            {**fact, "id": f"{prefix}_{fact['id']}"}
            for prefix, step in [("a", groups), ("b", ranking)]
            for fact in step["facts"]
        ],
    }
    open_report(browser, tmp_path, answer)
    contexts = browser.find_elements(By.CLASS_NAME, "answer-step")
    assert (
        "Partial result" in contexts[0].text
        and "Complete result" not in contexts[0].text
    )
    assert (
        "Complete result" in contexts[1].text
        and "Partial result" not in contexts[1].text
    )
    card(browser, "a_group_sizes").find_element(By.CLASS_NAME, "bar-row").send_keys(
        Keys.ENTER
    )
    assert set(network_selection(browser, "a_network")) == {"1", '"1"'}
    assert network_selection(browser, "b_network") == []
    members = card(browser, "a_members")
    next(
        button
        for button in members.find_elements(By.CLASS_NAME, "table-entity")
        if button.text == "Beta"
    ).send_keys(Keys.ENTER)
    assert network_selection(browser, "a_network") == ['"1"']
    group_table = card(browser, "a_groups")
    assert str(large_id) in group_table.text and str(large_id + 1) in group_table.text
    next(
        button
        for button in group_table.find_elements(By.CLASS_NAME, "table-entity")
        if button.text == "Large B"
    ).send_keys(Keys.ENTER)
    assert network_selection(browser, "a_network") == [str(large_id + 1)]
    card(browser, "a_group_sizes").find_elements(By.CLASS_NAME, "bar-row")[2].send_keys(
        Keys.ENTER
    )
    assert set(network_selection(browser, "a_network")) == {
        str(large_id),
        str(large_id + 1),
    }
    next(
        button
        for button in members.find_elements(By.CLASS_NAME, "table-entity")
        if button.text == "Beta"
    ).send_keys(Keys.ENTER)
    assert [
        button.text
        for button in members.find_elements(
            By.CSS_SELECTOR, '.table-entity[aria-pressed="true"]'
        )
    ] == ["Beta"]
    controls = card(browser, "a_network")
    search = controls.find_element(By.CLASS_NAME, "network-search")
    search.send_keys("Alpha")
    assert network_selection(browser, "a_network") == ["1"]
    controls.find_element(By.CLASS_NAME, "focus-selection").send_keys(Keys.ENTER)
    card(browser, "b_ranking").find_element(By.CLASS_NAME, "bar-row").send_keys(
        Keys.ENTER
    )
    assert network_selection(browser, "b_network") == ['"1"']
    assert network_selection(browser, "a_network") == ["1"]
    assert (
        browser.execute_script(
            "return arguments[0].querySelector('.answer-network').graphmineNetwork.edges()[0].style('target-arrow-shape')",
            card(browser, "b_network"),
        )
        == "triangle"
    )
    assert (
        browser.execute_script(
            "return arguments[0].querySelector('.answer-network').graphmineNetwork.edges()[0].style('target-arrow-shape')",
            controls,
        )
        == "none"
    )
    controls.find_element(By.CLASS_NAME, "reset-network").send_keys(Keys.ENTER)
    assert network_selection(browser, "a_network") == []
    controls.find_element(By.CSS_SELECTOR, ".network-accessible summary").click()
    controls.find_element(By.CLASS_NAME, "network-entity").send_keys(Keys.ENTER)
    assert len(network_selection(browser, "a_network")) == 1
    browser.set_window_size(390, 844)
    wait = WebDriverWait(browser, 20)
    visible_network = "const cy = arguments[0].querySelector('.answer-network').graphmineNetwork; return cy.nodes().filter(n => !!n.data('original')).every(n => { const p = n.renderedPosition(); return p.x >= 0 && p.x <= cy.width() && p.y >= 0 && p.y <= cy.height(); });"
    wait.until(lambda _: browser.execute_script(visible_network, controls))
    assert browser.execute_script(
        "return document.documentElement.scrollWidth <= window.innerWidth + 1"
    )
    if directory := os.environ.get("GRAPHMINE_BROWSER_ARTIFACT_DIR"):
        artifacts = Path(directory)
        artifacts.mkdir(parents=True, exist_ok=True)
        browser.execute_script(
            "arguments[0].scrollIntoView()", card(browser, "a_group_sizes")
        )
        browser.execute_async_script(
            "const done = arguments[0]; requestAnimationFrame(() => requestAnimationFrame(done));"
        )
        browser.save_screenshot(str(artifacts / "linked-mobile-chart.png"))
        browser.set_window_size(1440, 1000)
        wait.until(lambda _: browser.execute_script(visible_network, controls))
        browser.execute_script("arguments[0].scrollIntoView()", controls)
        browser.execute_async_script(
            "const done = arguments[0]; requestAnimationFrame(() => requestAnimationFrame(done));"
        )
        browser.save_screenshot(str(artifacts / "linked-network.png"))

    # Older snapshots can lack the canonical membership keys needed to recover
    # integers beyond JavaScript's precision. Keep their known names visible,
    # but do not display rounded IDs or link a different entity accidentally.
    for step in answer["steps"].values():
        step["tables"].pop("columns")
        for group in step["groups"]:
            group.pop("member_keys")
    open_report(browser, tmp_path, answer)
    legacy_groups = card(browser, "a_groups")
    assert "cannot be linked reliably" in legacy_groups.text
    assert "Large B" in legacy_groups.text
    assert "Unavailable in this older preview" in legacy_groups.text
    assert not legacy_groups.find_elements(By.CLASS_NAME, "table-entity")
    legacy_members = card(browser, "a_members")
    assert str(large_id + 1) in legacy_members.text
    next(
        button
        for button in legacy_members.find_elements(By.CLASS_NAME, "table-entity")
        if button.text == "Large B"
    ).send_keys(Keys.ENTER)
    assert network_selection(browser, "a_network") == [str(large_id + 1)]


def test_charts_preserve_sign_and_count_histograms_before_display_limits(
    browser, tmp_path
):
    graph = {
        "graph": {"id": "chart", "directed": False},
        "vertices": [{"id": 0}],
        "edges": [],
    }
    answer = answer_for(graph, "maximal-cliques", {"cliques": [[0]], "complete": True})
    answer["histogram_samples"] = [{"threshold": i % 2} for i in range(1205)]
    answer["signed_samples"] = [
        {"name": name, "value": value}
        for name, value in [("Gain", 2), ("Loss", -3), ("Unavailable", None)]
    ]
    answer["timeline_samples"] = [
        {
            "id": i,
            "sequence": i // 3 + 1,
            "order": i % 3 + 1,
            "timestamp": i,
            "source_label": f"Source {i}",
            "target_label": "Target",
        }
        for i in range(1002)
    ]
    views = answer_visualizations(answer) + [
        VisualizationSpec(
            id="histogram",
            type="histogram",
            title="Authored histogram fixture",
            data_ref="answer.histogram_samples",
            encodings={"value": "threshold"},
            limit=1000,
        ),
        VisualizationSpec(
            id="signed",
            type="bar",
            title="Authored signed-value fixture",
            data_ref="answer.signed_samples",
            encodings={"category": "name", "value": "value"},
        ),
        VisualizationSpec(
            id="timeline",
            type="timeline",
            title="Authored timeline fixture",
            data_ref="answer.timeline_samples",
            limit=1000,
        ),
    ]
    open_report(browser, tmp_path, answer, views)
    assert [
        node.text
        for node in card(browser, "histogram").find_elements(By.CLASS_NAME, "bar-value")
    ] == ["603", "602"]
    signed = card(browser, "signed")
    assert [node.text for node in signed.find_elements(By.CLASS_NAME, "bar-value")] == [
        "2",
        "-3",
    ]
    assert "Unavailable" not in signed.text
    assert (
        browser.execute_script(
            "return arguments[0].querySelector('.bar-zero').style.left", signed
        )
        == "60%"
    )
    assert (
        browser.execute_script(
            "return arguments[0].querySelector('.bar-fill.negative').style.left", signed
        )
        == "0%"
    )
    timeline = card(browser, "timeline")
    assert "8 of 334 available sequences" in timeline.text
    assert len(timeline.find_elements(By.CLASS_NAME, "matched-event")) == 24
    timeline.find_element(By.CSS_SELECTOR, ".timeline-values summary").click()
    timeline.find_element(By.CLASS_NAME, "viz-filter").send_keys("Source 1001")
    WebDriverWait(browser, 20).until(
        lambda _: (
            "1 matches across 1002 available rows"
            in timeline.find_element(By.CLASS_NAME, "table-status").text
        )
    )
    assert "Source 1001" in timeline.find_element(By.CLASS_NAME, "data-table").text
    if directory := os.environ.get("GRAPHMINE_BROWSER_ARTIFACT_DIR"):
        browser.execute_script("arguments[0].scrollIntoView()", timeline)
        browser.save_screenshot(str(Path(directory) / "timeline-values.png"))
    browser.set_window_size(390, 844)
    assert browser.execute_script(
        "return document.documentElement.scrollWidth <= window.innerWidth + 1"
    )
