"""Exercise the built release under a project prefix before deployment."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

with TemporaryDirectory() as temp:
    (Path(temp) / 'gerard').symlink_to(ROOT / '_site', target_is_directory=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=temp))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            errors = []
            requests = []
            page.on('request', lambda request: requests.append(request.url))
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/gerard/', wait_until='networkidle')
            page.wait_for_function("!document.querySelector('#department-query').disabled")
            assert page.locator('.leaflet-interactive').count() > 500
            assert not any('projection-2026.js' in url or 'hemicycle-layout.js' in url for url in requests)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#department-toggle').click()
            page.locator('#department-query').fill('Ain')
            page.get_by_role('option', name='Ain (01)', exact=True).click()
            page.wait_for_function("document.querySelector('#department-summary').textContent.includes('proposés')")
            assert page.evaluate("selectedDepartment === '01'")
            assert page.evaluate("document.activeElement.id === 'department-toggle'")
            page.locator('#department-toggle').click()
            assert page.get_by_role('option', name='Ain (01)', exact=True).is_visible()
            assert not page.get_by_text('Aucun département trouvé').is_visible()
            page.locator('#department-toggle').click()
            assert page.evaluate("currentLayer.getLayers().some(l => departmentCode(l.feature) !== '01' && l.options.fillColor === '#b9b4a9')")
            page.locator('#round-first').click()
            page.wait_for_function("document.querySelector('#round-first').getAttribute('aria-pressed') === 'true'")
            page.locator('#view-tomorrow').click()
            page.get_by_role('button', name='Explorer cette carte').click()
            page.wait_for_selector('#results:not([hidden])')
            assert page.locator('#results-cue').is_visible()
            assert page.evaluate("selectedDepartment === '01'")
            page.wait_for_timeout(850)
            assert page.evaluate("proposalLayer.getLayers().some(l => departmentCode(l.feature) !== '01' && l.options.fillColor === '#b9b4a9')")
            page.locator('#view-today').click()
            assert page.locator('#results').is_hidden()
            assert page.evaluate("selectedDepartment === '01'")
            page.evaluate("map.fire('click')")
            assert page.evaluate("selectedDepartment === ''")
            page.goto(f'http://127.0.0.1:{server.server_port}/gerard/method.html', wait_until='networkidle')
            assert page.locator('#draft-scope').inner_text()
            assert not errors, errors
            failed = browser.new_page()
            failed.route('**/projection-2026.js*', lambda route: route.abort())
            failed.goto(f'http://127.0.0.1:{server.server_port}/gerard/', wait_until='networkidle')
            failed.wait_for_function("!document.querySelector('#department-query').disabled")
            failed.locator('#view-tomorrow').click()
            failed.get_by_role('button', name='Explorer cette carte').click()
            failed.wait_for_selector('#proposal-error:not([hidden])')
            assert failed.locator('#view-today').get_attribute('aria-pressed') == 'true'
            assert failed.locator('.leaflet-interactive').count() > 500
            browser.close()
    finally:
        server.shutdown()
