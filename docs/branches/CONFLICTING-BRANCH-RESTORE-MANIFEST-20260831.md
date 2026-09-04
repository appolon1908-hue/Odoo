# Conflicting-branch restore manifest — 2026-08-31

Recorded against origin/main 7969a09 before any deletion.
Restore any branch with: git push origin <sha>:refs/heads/<branch>

## No associated PR (25)
```
e3e542cdeedc1ae8fa6c19e8e4011ad5b1779250 crm/odoo-campaign-core
f6cbd368885a184ee9a0824877cc45bb25ef15be docs/cc-production-gates
ff1e58dfdfefc6cdbfebfc0949380fd31624fd39 feat/cc-bu-calderon
ff1e58dfdfefc6cdbfebfc0949380fd31624fd39 feat/cc-bu-calderon-farm
1317719d78660e09cafaefb2f4ad448195f0ecfc feat/cc-bu-codestra
834ce411620274809d7bc7944eeb2b21b45464a3 feat/cc-bu-for-the-people
834ce411620274809d7bc7944eeb2b21b45464a3 feat/cc-bu-ftp
54a30a5258c8bf169e8a204b94d37485cd03d708 feat/cc-bu-moneybee
54a30a5258c8bf169e8a204b94d37485cd03d708 feat/cc-bu-moneybee-loans
f5e0117031f6195cde132bc421de10dc69256898 feat/cc-bu-moy
5ea340cb39438ed6ff4ea210eaf8ca94fa3f2d85 feat/cc-bu-rlp
5ea340cb39438ed6ff4ea210eaf8ca94fa3f2d85 feat/cc-bu-rlp-real-estate
b49a947628bb7c8f9fff84ca9bb4f386e8ed69d9 feat/cc-bu-scp
b49a947628bb7c8f9fff84ca9bb4f386e8ed69d9 feat/cc-bu-senior-products
25cca54efa84afe9c13612a59c73ec8190ba802b feat/cc-bu-tradex
41371a23293cc6e28ceb19e0deb7db8de9ba313a feat/cc-controlled-catalogs
9d37054c2ae5829be58221bee4293cedfe6e6827 feature/calendar-popout
6a0f9c571c8cab4fe4ff68dbd579faf78a512f3f feature/click-to-call-popout-dialer
7689d74eb7cd620a181a056255219dc521a05e99 feature/reminder-popout
32bc467daa4f6d57536ffc266017b342622045af feature/scheduler-popout
2eb05cf479f3b4edd162f03197349a76c488d0cd import/server-odoo-20260828
ad5bfbfa747a995bd2142d5cc5ebf5e007fc289e integration/n8n-middleware-automation-contract-v1
31d334571f15ca249bfbcfba157e2c480ffb93ba remediation/pr57-runtime-20260901
720e9e2e46d75b60396833850c0ae888c0fd8dd1 test/cc-cross-campaign-certification
79ba5f2460d0a8c541f9cf9c084cb87ba72ed802 test/popout-suite-integration
```

## Has an associated PR (36) — deleting these closes the PR
```
1676d72e948b259d82ea7425e16636ca2618ee66 architecture/middleware-write-boundary PR#2
9603eb587f491c34655777e2d0b565f311ab6d7a chore/odoo-gitops-bootstrap PR#1
f7ccff9e4a9894939e8fdd06cef10e342ff5169d docs/odoo-contact-center-authority PR#26
144e55c4b3902b7802ec6a1bbec520c05a22679e feat/cc-callback-transfer PR#34
8c394b7106ac999aab8f26b4e73462c251413585 feat/cc-campaign-mail PR#30
58376d7211bae53ed2d0f5c89bc5a968f2148190 feat/cc-campaign-security PR#28
4681d755039ee7f4fec21228bac234a668541de8 feat/cc-compliance-audit PR#37
d7ab1c7ef0b34ec71d1c485e733ba9881d34af1d feat/cc-core-domain PR#27
53e2a2dbf6e3249f82abae4ae5e2df0ec3df8a33 feat/cc-crm-helpdesk-workspaces PR#31
aa32edfaa0c05fb2b3d4803ade3685af6a802384 feat/cc-identity-membership PR#29
c46096ecc9694d5bc2faffbe6b9e0bd7a193c39c feat/cc-recordings-quality PR#35
789998ae32c26f005d63b3d84cb2c32304c8da64 feat/cc-scripts-dispositions PR#33
12775a51209a2eb1c5be7d2a50c1ad635f804398 feat/cc-vicidial-mapping PR#32
a2592e66ab0b3953548b3b55735a852857ed892d feat/cc-wfm-reporting PR#36
e757622c8a4d2b6ab906a74d2786d022ca6eacda feat/codestra-keycloak-contract PR#3
b28b51e9beb39efc9e2f660aacbcabdb38cba160 feat/import-canonical-odoo-modules PR#9
7ab1a670daaa315e2ba8985f861f5c974ba9eb11 feat/marketing-crm-foundation-20260830 PR#51
3b045d08ceb57861a72a83bbe210428fa7aec889 feature/cc-00-mission-foundation PR#8
c80e196d0263ea92a9f16a6008afc1488b0d8558 feature/cc-01-core-reliability PR#10
dde2ca47e2bbc6dc873e1ea5baee6e05bd0ede38 feature/cc-02-vicidial-api PR#11
b05fce60adb6470aa4aca7c662f67621052e424e feature/cc-03-agent-campaign-experience PR#12
6a74b3cc75b6d6934878515da8ed847fd12fede1 feature/cc-04-supervisor-quality-compliance PR#13
d122334ee4da526eff227a03df23a6adcb3e9d4e feature/cc-05-workforce-identity-onboarding PR#14
a89c908f0b0cb0921ae9f8b7e6dec520dc7b8e7a feature/cc-06-omnichannel-client-operations PR#15
cd1c774584614e125c6ab49aacf750452e74267a feature/cc-07-revenue-analytics-portal PR#16
a2558ec9726f222828803142e33f19556608a5ee feature/cc-08-ai-agent-assistant PR#17
1fa2d6d5a52f27d0634a74c4a62593b3bc706e45 feature/intake-lead-upsert-v1 PR#50
a282e555023a9d84880248be99e8554df73c7ab1 fix/canonical-integration-contract-v2-20260830 PR#53
6dc403350da71962af28603c0bdf2e73f7f6821e fix/cc-11-production-readiness PR#25
84f80cbc978bc5941836474c6569f87b1c0031d8 fix/cc-login-layout-website-compat PR#21
b8c51fe622ce841c192529cd3b9a274b313a2ed4 ops/codestra-odoo-upstream-sync-v1-20260830 PR#55
62d19fe6484b76dd23a30918b4fd098b1809bfe2 production/release-certification-v1-20260902 PR#62
10a797d550249da63c99863577b4e6d637aa660d production/signed-release-candidate-v1-20260902 PR#61
954d2a5a19ba79e34521807cd875a67d91bdf733 reconcile/odoo-canonical-source-v1 PR#38
23c50d7c9bd56b1b0dbc7f73cc4d3ab00aa53a81 release/cc-10-staging-certification PR#19
1dde88bfdae58352e061a5f66cb5096b7c7204da test/cc-09-security-load-migrations PR#18
```
