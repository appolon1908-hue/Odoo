def migrate(cr, version):
    cr.execute("UPDATE codestra_extension_pool SET active = FALSE WHERE code IN ('MOY-6100','MBL-6200','COD-6300','SCP-6400','STU-6500','QA-6900')")
    cr.execute("UPDATE call_center_campaign SET active = FALSE, state = 'draft' WHERE code LIKE '%-R1-STAGING'")
