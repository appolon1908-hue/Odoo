def migrate(cr, version):
    # Preserve existing browser-phone assignments when introducing the explicit
    # optional WebRTC capability. New agents remain opt-in by default.
    cr.execute(
        """
        UPDATE codestra_vicidial_agent
           SET webrtc_enabled = TRUE
         WHERE phone_login IS NOT NULL
           AND btrim(phone_login) <> ''
        """
    )
