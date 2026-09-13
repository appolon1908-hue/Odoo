import os
import stat
import tempfile
import uuid

from odoo.tests import HttpCase, tagged

from ..controllers.metrics import TOKEN_FILE_PARAM


@tagged("post_install", "-at_install")
class TestCodestraMetrics(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = "synthetic-metrics-token-" + uuid.uuid4().hex
        fd, cls.token_path = tempfile.mkstemp()
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(cls.token)
        os.chmod(cls.token_path, stat.S_IRUSR | stat.S_IWUSR)

        cls.employee = cls.env["hr.employee"].create({"name": "Synthetic Metrics Agent"})
        cls.env["codestra.agent.channel"].create({
            "employee_id": cls.employee.id,
            "channel_type": "email",
            "desired_enabled": True,
        })
        cls.env["codestra.agent.onboarding"].create({
            "employee_id": cls.employee.id,
            "manager_id": cls.env.user.id,
        })

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.token_path)
        super().tearDownClass()

    def _set_token_file_param(self, value):
        params = self.env["ir.config_parameter"].sudo()
        if value is None:
            params.search([("key", "=", TOKEN_FILE_PARAM)]).unlink()
        else:
            params.set_param(TOKEN_FILE_PARAM, value)

    def _get(self, headers=None):
        return self.opener.request(
            "GET", self.base_url() + "/codestra/metrics", headers=headers or {}, timeout=20
        )

    def test_rejects_missing_token_file(self):
        self._set_token_file_param(None)
        response = self._get(headers={"Authorization": "Bearer whatever"})
        self.assertEqual(response.status_code, 503)

    def test_rejects_wrong_token(self):
        self._set_token_file_param(self.token_path)
        response = self._get(headers={"Authorization": "Bearer not-the-token"})
        self.assertEqual(response.status_code, 401)

    def test_rejects_missing_authorization_header(self):
        self._set_token_file_param(self.token_path)
        response = self._get()
        self.assertEqual(response.status_code, 401)

    def test_exposes_prometheus_text_format_with_real_backlog_counts(self):
        self._set_token_file_param(self.token_path)
        response = self._get(headers={"Authorization": "Bearer " + self.token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["Content-Type"])
        body = response.text

        self.assertIn("# HELP codestra_up", body)
        self.assertIn("# TYPE codestra_up gauge", body)
        self.assertIn("codestra_up 1", body)
        self.assertIn("codestra_ready 1", body)

        expected_channel_drift = self.env["codestra.agent.channel"].search_count([
            ("requested_state", "=", "requested"),
            ("provisioned_state", "=", "not_provisioned"),
        ])
        self.assertGreaterEqual(expected_channel_drift, 1)
        self.assertIn(
            f"codestra_agent_channel_drift_backlog {expected_channel_drift}", body
        )

        expected_onboarding_backlog = self.env["codestra.agent.onboarding"].search_count([
            ("state", "in", ("draft", "in_review", "approved", "provisioning", "offboarding"))
        ])
        self.assertGreaterEqual(expected_onboarding_backlog, 1)
        self.assertIn(
            f"codestra_agent_onboarding_backlog {expected_onboarding_backlog}", body
        )

        self.assertIn("codestra_metrics_scrape_duration_seconds", body)

    def test_group_readable_token_file_is_unavailable(self):
        self._set_token_file_param(self.token_path)
        try:
            os.chmod(self.token_path, 0o640)
            response = self._get(headers={"Authorization": "Bearer " + self.token})
            self.assertEqual(response.status_code, 503)
        finally:
            os.chmod(self.token_path, 0o600)
