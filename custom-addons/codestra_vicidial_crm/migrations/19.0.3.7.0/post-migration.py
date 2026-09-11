def migrate(cr, version):
    # Every existing agent in this module is already required to have an Odoo
    # user and extension. Populate the new primary campaign only when exactly
    # one campaign is already assigned; never guess between multiple campaigns.
    cr.execute(
        """
        UPDATE codestra_vicidial_agent agent
           SET primary_campaign_id = mapped.campaign_id
          FROM (
                SELECT codestra_vicidial_agent_id AS agent_id,
                       min(codestra_vicidial_campaign_id) AS campaign_id
                  FROM codestra_vicidial_agent_codestra_vicidial_campaign_rel
                 GROUP BY codestra_vicidial_agent_id
                HAVING count(*) = 1
               ) mapped
         WHERE agent.id = mapped.agent_id
           AND agent.primary_campaign_id IS NULL
        """
    )
    # WebRTC is an explicit Super Admin opt-in. Do not infer it from extension
    # presence: the extension is the number; WebRTC is an optional phone device.
