"""Off-host visual/browser checks of public source with unauthenticated fixtures.

Loopback HTTP is a disposable static preview, NOT production transport or an
authentication/TLS proof. No production URL, credential, identity or model is
used. Screenshots and receipts are CI artifacts, not deployed/PWA acceptance.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Thread


ROOT = Path(__file__).resolve().parents[1]


class PublicPreview(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/pwa/api/session':
            raw = json.dumps({'protocol': 'jarvis.interface.v1', 'authenticated': False}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('X-PRIME-Protocol', 'jarvis.interface.v1')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)
            return
        if not self.path.startswith('/pwa/') or '..' in self.path:
            self.send_error(404)
            return
        self.path = self.path[len('/pwa'):]
        super().do_GET()

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()


def main():
    from playwright.sync_api import sync_playwright
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    preview = ThreadingHTTPServer(('127.0.0.1', 0), partial(PublicPreview, directory=str(ROOT / 'clients/pwa')))
    thread = Thread(target=preview.serve_forever, daemon=True)
    thread.start()
    observations = []
    status = 'FAIL'
    try:
        with sync_playwright() as playwright:
            for engine_name in ('chromium', 'webkit'):
                browser = getattr(playwright, engine_name).launch()
                try:
                    for width, height in ((390, 844), (1440, 1000)):
                        context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{preview.server_port}/pwa/', wait_until='networkidle')
                        page.locator('#objective').wait_for(state='visible')
                        metrics = page.evaluate('''() => {
                            const box = document.querySelector('#objective').getBoundingClientRect();
                            const send = document.querySelector('#submit-button').getBoundingClientRect();
                            return {overflow: document.documentElement.scrollWidth > innerWidth,
                                    composer: {width: box.width, height: box.height},
                                    send: {width: send.width, height: send.height},
                                    background: getComputedStyle(document.body).backgroundColor};
                        }''')
                        page.locator('#objective').fill('A private local draft retained through a simulated network failure')
                        context.set_offline(True)
                        page.wait_for_timeout(150)
                        retained = page.locator('#objective').input_value().startswith('A private local draft')
                        screenshot = f'{engine_name}-{width}-workspace-offline.png'
                        page.screenshot(path=str(output / screenshot), full_page=True)
                        observations.append({'engine': engine_name, 'viewport': [width, height],
                                             'metrics': metrics, 'javascript_errors': len(errors),
                                             'draft_retained_offline': retained, 'screenshot': screenshot})
                        # Preserve the visible failure and measurements before checking them.
                        assert not metrics['overflow'], f'{engine_name}/{width}: horizontal overflow'
                        assert metrics['composer']['width'] > 200 and metrics['composer']['height'] < height / 2
                        assert metrics['send']['height'] >= 44 and metrics['send']['width'] >= 44
                        assert metrics['background'] not in ('rgba(0, 0, 0, 0)', 'rgb(255, 255, 255)'), 'CSP blocked design styles'
                        assert retained, f'{engine_name}/{width}: offline draft lost'
                        assert not errors, f'{engine_name}/{width}: JavaScript exception'
                        context.close()
                finally:
                    browser.close()
        assert len(observations) == 4 and all(o['javascript_errors'] == 0 for o in observations)
        status = 'PASS'
    finally:
        preview.shutdown()
        preview.server_close()
        receipt = {'status': status, 'scope': 'OFF_HOST_UNAUTHENTICATED_STATIC_BROWSER_FIXTURES',
                   'production_tls': 'NOT_TESTED', 'live_authentication': 'NOT_TESTED',
                   'physical_iphone': 'NOT_TESTED', 'observations': observations}
        (output / 'BROWSER-RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
