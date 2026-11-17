"""Conversation updates retain unrelated nodes, focus and disclosures."""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By

from test_workspace_conversation_graph import enable_admin_working_notes, event, open_saved, saved_network
from test_workspace_loading import SESSION, loading_browser, loading_server, wait_for


def test_event_index_deduplicates_and_merges_out_of_order_history(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server); open_saved(browser, server)
    actual = browser.execute_script("""
      const index=GraphMineEventIndex();
      const make=(sequence,turn_id,type='workflow.chat',extra={})=>({sequence,type,payload:{turn_id,role:'user',...extra}});
      index.reset([make(100,'new'),make(101,'new','workflow.answer',{workflow_id:'w',revision:1,message:'latest'})]);
      index.add([make(1,'old'),make(2,'old','workflow.reasoning'),make(100,'new'),make(50,'new','workflow.answer',{workflow_id:'w',revision:1,message:'older'})]);
      return {all:index.all().map(e=>e.sequence),old:index.turn('old').map(e=>e.sequence),version:index.version('new'),
        chats:index.chats().map(e=>e.sequence),answer:index.answer({id:'w',revision:1}).message,unknown:index.turn('missing').length};
    """)
    assert actual == {"all": [1, 2, 50, 100, 101], "old": [1, 2], "version": 3, "chats": [1, 100], "answer": "latest", "unknown": 0}


def test_new_reasoning_preserves_other_turn_dom_focus_and_expanded_details(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    for turn in ("first", "second"):
        event(server, "chat", turn, role="user", message=f"Question {turn}")
        event(server, "reasoning", turn, stage="planning", text=f"Reasoning {turn}")
        event(server, "chat", turn, role="assistant", message=f"Answer {turn}", view={"workflow_id": "saved-analysis"})
    open_saved(browser, server)
    enable_admin_working_notes(browser)
    browser.execute_script("""
      window.originalUser=document.querySelector('#messages .user[data-turn="first"]');
      window.originalAnswer=document.querySelector('#messages .assistant[data-turn="first"]');
      window.originalActivity=document.querySelector('#activity-list [data-turn="first"]');
      window.originalSecond=document.querySelector('#messages .assistant[data-turn="second"]');
      for (const details of originalAnswer.querySelectorAll('details')) details.open=true;
      document.querySelector('#messages [data-view="first"]').focus();
      window.originalFocus=document.activeElement;
    """)
    event(server, "reasoning.delta", "second", stage="planning", text="Additional live detail")
    browser.execute_script("window.dispatchEvent(new Event('online'))")
    wait_for(browser, "GraphMineWorkspace.state.events.length===7 && document.querySelector('#activity-list [data-turn=\"second\"] [data-live]')")
    assert browser.execute_script("""return originalUser===document.querySelector('#messages .user[data-turn="first"]')
      && originalAnswer===document.querySelector('#messages .assistant[data-turn="first"]')
      && originalActivity===document.querySelector('#activity-list [data-turn="first"]')
      && originalSecond===document.querySelector('#messages .assistant[data-turn="second"]')
      && document.activeElement===originalFocus
      && [...originalAnswer.querySelectorAll('details')].every(d=>d.open)""")
    assert len(browser.find_elements(By.CSS_SELECTOR, "#messages .chat-message[data-turn]")) == 4


@pytest.fixture
def paged_history(loading_server):
    server = loading_server
    saved_network(server)
    for number in range(1, 9):
        for role in ("user", "assistant"):
            event(server, "chat", f"turn-{number}", role=role, message=f"{role} question {number}. " + "A longer saved paragraph for reading. " * 20)
            server.events[-1]["created_at"] = f"2026-01-01T00:00:{len(server.events):02d}Z"
    old = deepcopy(server.workflows[0]); old.update(id="old-manual", planning_turn_id=None, created_at="2025-12-01T00:00:00Z")
    server.workflows.insert(0, old); server.results[old["id"]] = deepcopy(server.results["saved-analysis"])
    server.history_calls, server.tail_calls = [], []
    server.history_error = False; server.history_hook = None
    def route(handler, method):
        path, query = urlsplit(handler.path).path, parse_qs(urlsplit(handler.path).query)
        if method != "GET":
            return False
        if path.endswith("/workspace"):
            handler.respond({"session": SESSION, "files": server.files, "messages": [], "events": server.events[10:16],
                "timeline": {"event_cursor": 16, "has_more": True, "next_cursor": "older", "turn_numbers": {f"turn-{i}": i for i in range(6, 9)}, "manual_workflow_ids": []}})
            return True
        if path.endswith("/conversation-page"):
            server.history_calls.append(query)
            if server.history_hook and server.history_hook(handler):
                return True
            if server.history_error:
                handler.respond({"error": {"message": "History unavailable"}}, 503)
            else:
                handler.respond({"messages": [], "events": server.events[:12], "has_more": False, "next_cursor": None,
                    "event_cursor": 99999, "turn_numbers": {f"turn-{i}": i for i in range(1, 7)}, "manual_workflow_ids": ["old-manual"]})
            return True
        if path.endswith("/events"):
            server.tail_calls.append(query)
            after = int(query.get("after", [0])[0])
            rows = [row for row in server.events if row["sequence"] > after]
            # A small controlled batch also proves backlog drains immediately.
            handler.respond({"events": rows[:2], "last_sequence": rows[min(2, len(rows))-1]["sequence"] if rows else after,
                             "has_more": len(rows) > 2, "turn_numbers": {row["payload"]["turn_id"]: (row["sequence"] + 1)//2 for row in rows[:2]}})
            return True
        return False
    server.route_handler = route
    return server


@pytest.mark.parametrize("width", [1440, 320])
def test_history_pages_preserve_reading_position_numbers_and_new_message_cursor(loading_browser, paged_history, width):
    browser, server = loading_browser, paged_history
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    open_saved(browser, server)
    assert len(browser.find_elements(By.CSS_SELECTOR, "#messages [data-turn]")) == 6
    assert not browser.find_elements(By.CSS_SELECTOR, '[data-render-key="workflow:old-manual"]')
    assert browser.find_element(By.CSS_SELECTOR, '#activity-list [data-turn="turn-6"] h3').get_attribute("textContent") == "Question 6"
    browser.execute_script("""
      const scroll=document.getElementById('conversation-scroll'); scroll.style.scrollBehavior='auto'; scroll.scrollTop=0;
      window.reading=document.querySelector('#messages .user[data-turn="turn-6"]');
      window.readingTop=reading.getBoundingClientRect().top;
    """)
    browser.find_element(By.ID, "load-older-messages").click()
    wait_for(browser, "document.querySelectorAll('#messages .chat-message[data-turn]').length===16 && document.getElementById('load-older-messages').hidden")
    assert browser.execute_script("return reading===document.querySelector('#messages .user[data-turn=\"turn-6\"]') && Math.abs(reading.getBoundingClientRect().top-readingTop)<3")
    assert browser.execute_script("return document.activeElement===reading")
    assert browser.execute_script("return GraphMineWorkspace.state.eventCursor") == 16
    assert browser.find_elements(By.CSS_SELECTOR, '[data-render-key="workflow:old-manual"]')
    assert server.history_calls[0] == {"limit": ["30"], "before": ["older"]}
    for number in (9, 10):
        for role in ("user", "assistant"):
            event(server, "chat", f"turn-{number}", role=role, message=f"New {role} message {number}")
            server.events[-1]["created_at"] = f"2026-01-01T00:00:{len(server.events):02d}Z"
    browser.execute_script("window.dispatchEvent(new Event('online'))")
    wait_for(browser, "GraphMineWorkspace.state.eventCursor===20 && !document.getElementById('show-latest-messages').hidden")
    assert browser.execute_script("return Math.abs(reading.getBoundingClientRect().top-readingTop)<100")
    browser.find_element(By.ID, "show-latest-messages").click()
    wait_for(browser, "document.getElementById('show-latest-messages').hidden")
    assert browser.execute_script("return document.activeElement===document.getElementById('messages').lastElementChild")
    assert browser.execute_script("const s=document.getElementById('conversation-scroll').getBoundingClientRect(), m=document.querySelector('#messages').lastElementChild.getBoundingClientRect(); return m.bottom<=s.bottom+20 && m.bottom>s.top")
    assert browser.execute_script("return document.documentElement.scrollWidth<=innerWidth+1")


def test_older_history_retry_and_delayed_response_after_navigation(loading_browser, paged_history):
    browser, server = loading_browser, paged_history
    open_saved(browser, server)
    server.history_error = True
    browser.execute_script("document.getElementById('load-older-messages').click()")
    wait_for(browser, "document.getElementById('load-older-messages').textContent==='Retry older messages'")
    assert len(browser.find_elements(By.CSS_SELECTOR, "#messages .chat-message[data-turn]")) == 6
    browser.execute_script("""
      const original=window.fetch;
      window.fetch=(path,options)=>String(path).includes('/conversation-page?') ? new Promise(resolve=>{window.releaseHistory=()=>resolve(new Response(JSON.stringify({messages:[{id:'stale',role:'user',message:'Stale history'}],events:[],has_more:false}),{status:200}));}) : original(path,options);
      document.getElementById('load-older-messages').click();
    """)
    wait_for(browser, "Boolean(window.releaseHistory)")
    browser.execute_script("location.hash='#'")
    wait_for(browser, "GraphMineWorkspace.state.session===null")
    browser.execute_script("releaseHistory()")
    wait_for(browser, "document.getElementById('conversation-history').hidden")
    assert "Stale history" not in browser.find_element(By.ID, "messages").get_attribute("textContent")


def test_graph_refresh_retains_instance_positions_viewport_and_event_handlers(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    server.graph["edges"][0]["timestamp"] = 10
    server.graph["edges"][1]["timestamp"] = 20
    open_saved(browser, server, "results")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length===6")
    browser.execute_script("""
      window.originalCy=GraphMineWorkspace.state.cy;
      originalCy.nodes().forEach((n,i)=>n.position({x:40+i*70,y:80+i*35}));
      originalCy.zoom(1.25); originalCy.pan({x:51,y:67});
      window.originalViewport=JSON.stringify({zoom:originalCy.zoom(),pan:originalCy.pan(),positions:originalCy.nodes().map(n=>n.position())});
      window.originalHandlers=originalCy._private.emitter.listeners.length;
      for(let i=0;i<5;i++) document.getElementById('flow-direction').dispatchEvent(new Event('change'));
    """)
    state = browser.execute_script("""return {same:originalCy===GraphMineWorkspace.state.cy, alive:!originalCy.destroyed(),
      before:originalViewport,after:JSON.stringify({zoom:originalCy.zoom(),pan:originalCy.pan(),positions:originalCy.nodes().map(n=>n.position())}),
      handlersBefore:originalHandlers,handlersAfter:originalCy._private.emitter.listeners.length}""")
    assert state["same"] and state["alive"], state
    assert state["before"] == state["after"], state
    assert state["handlersBefore"] == state["handlersAfter"], state
    browser.find_element(By.ID, "back-to-chat").click()
    wait_for(browser, "GraphMineWorkspace.state.view==='chat'")
    browser.find_element(By.ID, "results-page-link").click()
    wait_for(browser, "GraphMineWorkspace.state.view==='results' && Boolean(GraphMineWorkspace.state.cy)")
    assert browser.execute_script("return originalCy===GraphMineWorkspace.state.cy")
    browser.execute_script("const low=document.getElementById('time-start'); low.value='1'; low.dispatchEvent(new Event('input'))")
    assert browser.execute_script("return originalCy.edges().some(e=>e.style('display')==='none')")
    browser.execute_script("""
      const s=GraphMineWorkspace.state;
      s.graphBase={...s.graphBase,vertices:s.graphBase.vertices.map(v=>({...v,label:'Updated '+v.id})),
        edges:s.graphBase.edges.map(({timestamp,...edge})=>edge)};
      document.getElementById('flow-direction').dispatchEvent(new Event('change'));
    """)
    assert browser.execute_script("return originalCy===GraphMineWorkspace.state.cy && originalCy.nodes().every(n=>n.data('label').startsWith('Updated '))")
    assert browser.execute_script("return originalCy.edges().every(e=>e.style('display')!=='none') && document.getElementById('time-controls').hidden")
    browser.execute_script("""
      const s=GraphMineWorkspace.state;
      s.graphBase={...s.graphBase,vertices:[...s.graphBase.vertices,{id:'new',label:'New node'}]};
      document.getElementById('flow-direction').dispatchEvent(new Event('change'));
    """)
    assert browser.execute_script("return originalCy!==GraphMineWorkspace.state.cy && originalCy.destroyed() && GraphMineWorkspace.state.cy.nodes().length===7")


def test_event_poll_cursor_keeps_exact_large_sequence_numbers(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    base = 9007199254740992
    for role in ("user", "assistant"):
        event(server, "chat", "large-first", role=role, message=role)
        server.events[-1]["sequence"] = base + len(server.events) - 1
    def route(handler, method):
        path, query = urlsplit(handler.path).path, parse_qs(urlsplit(handler.path).query)
        if path.endswith("/workspace"):
            handler.respond({"session": SESSION, "files": server.files, "messages": [], "events": server.events[:2],
                "timeline": {"event_cursor": base + 1, "has_more": False, "next_cursor": None, "turn_numbers": {"large-first": 1}, "manual_workflow_ids": []}})
            return True
        if path.endswith("/events"):
            after = int(query["after"][0]); rows = [row for row in server.events if row["sequence"] > after]
            handler.respond({"events": rows, "has_more": False, "last_sequence": rows[-1]["sequence"] if rows else after})
            return True
        return False
    server.route_handler = route
    open_saved(browser, server)
    assert browser.execute_script("return String(GraphMineWorkspace.state.eventCursor)") == str(base + 1)
    for role in ("user", "assistant"):
        event(server, "chat", "large-next", role=role, message=role)
        server.events[-1]["sequence"] = base + len(server.events) - 1
    browser.execute_script("window.dispatchEvent(new Event('online'))")
    wait_for(browser, f"String(GraphMineWorkspace.state.eventCursor)==='{base + 3}'")
    assert browser.execute_script("return GraphMineWorkspace.state.events.map(e=>String(e.sequence))") == [str(base+i) for i in range(4)]
