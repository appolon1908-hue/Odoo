# Load certification

The k6 scenario targets 50 synthetic VICIdial events per second for five minutes and refuses canonical production or infrastructure hosts. It is not invoked automatically from pull-request CI.

Run only against a sanitized isolated staging deployment with external delivery, callbacks, n8n activation, live call control, and PSTN dialing disabled. Retain request counts, latency histograms, database and worker health, duplicate-side-effect evidence, and restart-recovery evidence.
