"""Shared test helper for M1-10: every POST (except /api/frame) must carry expected_revision.

Tests that are not about revisions send the server's current revision through with_revision().
"""
import http.client
import json


def current_revision(port, token):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', '/api/state', headers={'Authorization': 'Bearer ' + token})
        response = connection.getresponse()
        data = response.read()
        return json.loads(data)['revision'] if response.status == 200 else None
    except (OSError, ValueError, UnicodeEncodeError):
        return None
    finally:
        connection.close()


def with_revision(port, token, path, body):
    if isinstance(body, dict) and 'expected_revision' not in body and path != '/api/frame':
        revision = current_revision(port, token)
        if revision is not None:
            body = {**body, 'expected_revision': revision}
    return body


def pending_id(server_module):
    """Id of the current camera proposal (M1-12) after a test set vision.proposal directly."""
    vision = server_module.vision
    with vision.lock:
        vision.publish()
        pending = server_module.app.flow.observe(vision)
    return pending['id'] if pending else None
