from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE_URL = 'http://127.0.0.1:8000'


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {'Accept': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


def main() -> int:
    try:
        health = _request('GET', '/health')
        print('HEALTH:')
        print(json.dumps(health, ensure_ascii=False, indent=2))

        session = _request('POST', '/sessions')
        session_id = session['session_id']
        print('\nNEW SESSION:')
        print(json.dumps(session, ensure_ascii=False, indent=2))

        chat = _request(
            'POST',
            '/chat',
            {
                'session_id': session_id,
                'message': '你是谁？请用一句话介绍自己。',
                'reasoning_mode': False,
                'debug_events': False,
            },
        )
        print('\nCHAT RESPONSE:')
        print(json.dumps(chat, ensure_ascii=False, indent=2))

        history = _request('GET', f'/sessions/{session_id}')
        print('\nSESSION SNAPSHOT:')
        print(json.dumps(history, ensure_ascii=False, indent=2))
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        print(f'HTTP {exc.code}: {body}', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'REQUEST FAILED: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
