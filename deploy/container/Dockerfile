# syntax=docker/dockerfile:1.7
FROM docker.io/library/odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5

ARG SOURCE_SHA

LABEL org.opencontainers.image.title="Codestra Odoo 19" \
      org.opencontainers.image.description="Codestra Odoo 19 custom-addon production candidate" \
      org.opencontainers.image.source="https://github.com/appolon1908-hue/Odoo" \
      org.opencontainers.image.revision="${SOURCE_SHA}"

USER root

COPY --chown=odoo:odoo custom-addons/ /mnt/extra-addons/

RUN test -n "$SOURCE_SHA" \
    && test -z "$(find /mnt/extra-addons -type l -print -quit)" \
    && test -n "$(find /mnt/extra-addons -mindepth 2 -maxdepth 2 -name __manifest__.py -print -quit)" \
    && find /mnt/extra-addons -type d -exec chmod 0555 {} + \
    && find /mnt/extra-addons -type f -exec chmod 0444 {} +

USER odoo
