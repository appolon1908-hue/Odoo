from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestCallEventAPIRetired(HttpCase):
    """/codestra/api/v1/call-events is retired and confirmed unreferenced.

    The active, dispatched contract is
    /codestra/middleware/v1/call-events (call_event_projection.py) --
    see tests/test_call_event_projection_http.py for its coverage. This
    duplicate route is kept registered only to return an explicit 410
    rather than a bare 404, in case anything is still pointed here by
    stale documentation.
    """

    def test_retired_route_returns_gone_regardless_of_payload(self):
        response = self.url_open(
            "/codestra/api/v1/call-events",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 410)

    def test_retired_route_returns_gone_with_no_auth_headers_at_all(self):
        # Even a completely bare request (no signature/timestamp/event-id
        # headers, which the old implementation required first) must hit
        # the deprecation response, not an auth error -- proving the old
        # validation/creation logic is fully gone, not just unreachable.
        response = self.url_open(
            "/codestra/api/v1/call-events",
            data=b"not even json",
        )
        self.assertEqual(response.status_code, 410)
        self.assertIn(b"middleware/v1/call-events", response.content)
