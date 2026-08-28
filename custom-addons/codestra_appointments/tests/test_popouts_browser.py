import os
from contextlib import nullcontext
from unittest.mock import patch
from urllib.parse import urlparse

from odoo import Command
from odoo.http import root
from odoo.tests import HttpCase, tagged
from odoo.tools.misc import file_path


def _windows_static_file(url, host=""):
    """Work around Odoo 19 normalizing URL slashes as Windows paths."""
    netloc, path = urlparse(url)[1:3]
    if netloc and netloc != host:
        return None
    parts = path.lstrip("/").split("/", 2)
    if len(parts) != 3 or parts[1] != "static":
        return None
    static_path = root.static_path(parts[0])
    if not static_path:
        return None
    try:
        return file_path(os.path.join(static_path, *parts[2].split("/")))
    except FileNotFoundError:
        return None


@tagged("post_install", "-at_install")
class TestAppointmentPopoutsBrowser(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.user_admin").write({
            "group_ids": [
                Command.link(cls.env.ref("codestra.group_agent").id),
                Command.link(cls.env.ref("codestra_vicidial_crm.group_agent").id),
            ],
        })

    def test_calendar_reminder_and_scheduler_popouts(self):
        code = """
        (async () => {
            const waitFor = async (predicate, label) => {
                const deadline = Date.now() + 15000;
                while (Date.now() < deadline) {
                    const result = predicate();
                    if (result) return result;
                    await new Promise((resolve) => setTimeout(resolve, 100));
                }
                throw new Error(`Timed out waiting for ${label}`);
            };
            const buttons = [
                ["Open appointment calendar pop-out", "Appointment Calendar"],
                ["Open reminder pop-out", "Reminder Center"],
                ["Open callback scheduler pop-out", "Callback Scheduler"],
            ];
            for (const [buttonLabel, dialogLabel] of buttons) {
                const button = await waitFor(
                    () => document.querySelector(`button[aria-label="${buttonLabel}"]`),
                    buttonLabel
                );
                button.click();
                const dialog = await waitFor(
                    () => document.querySelector(`section[role="dialog"][aria-label="${dialogLabel}"]`),
                    dialogLabel
                );
                if (dialog.getBoundingClientRect().width <= 0) {
                    throw new Error(`${dialogLabel} is not visible`);
                }
                const close = dialog.querySelector('button[aria-label="Close scheduling pop-out"]');
                if (!close) throw new Error(`${dialogLabel} has no accessible close control`);
                close.click();
                await waitFor(
                    () => !document.querySelector(`section[role="dialog"][aria-label="${dialogLabel}"]`),
                    `${dialogLabel} close`
                );
            }
            const schedulerButton = document.querySelector(
                'button[aria-label="Open callback scheduler pop-out"]'
            );
            schedulerButton.click();
            await waitFor(
                () => document.querySelector('section[aria-label="Callback Scheduler"]'),
                "keyboard scheduler open"
            );
            schedulerButton.dispatchEvent(new KeyboardEvent("keydown", {
                key: "Escape",
                bubbles: true,
            }));
            await waitFor(
                () => !document.querySelector('section[aria-label="Callback Scheduler"]'),
                "Escape close"
            );
            console.log("test successful");
        })().catch((error) => {
            console.error(error);
            throw error;
        });
        """
        static_path_patch = (
            patch.object(root, "get_static_file", _windows_static_file)
            if os.name == "nt"
            else nullcontext()
        )
        with static_path_patch:
            self.browser_js(
                "/odoo?debug=assets",
                code,
                ready="odoo.isReady === true",
                login="admin",
                timeout=90,
            )
