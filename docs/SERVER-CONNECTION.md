# Connect a self-hosted Odoo server to this repository

## Safety boundary

This repository currently contains only a non-secret bootstrap. Before importing Codestra business modules, change the repository visibility to **private**.

GitHub becomes the source of truth for custom addon code. The server should normally have read-only repository access and must not push live edits back to GitHub.

Do not place these items in Git:

- PostgreSQL data or dumps;
- Odoo filestore, attachments, sessions, logs, or backups;
- `.env`, database passwords, API tokens, private keys, or live `odoo.conf` secrets;
- Odoo runtime volumes;
- files edited inside a running container.

## Intended flow

```text
feature branch
  -> pull request
  -> CI and review
  -> merge to protected main
  -> deploy exact merged commit SHA to staging
  -> module upgrade and smoke tests
  -> production approval
  -> deploy the same SHA to production
```

A Git rollback does not reverse database changes made by an Odoo module upgrade. A data rollback requires the matching PostgreSQL and filestore recovery point.

## 1. Discover the current Docker layout

Run the included script on the Odoo host before changing any mounts or Compose files:

```bash
sudo bash scripts/discover_odoo_runtime.sh | tee /root/odoo-git-discovery.txt
```

Record these values from its output:

- Compose working directory and configuration file;
- Odoo service name;
- PostgreSQL service name;
- host path currently mounted as the custom addons directory;
- custom addons path inside the Odoo container;
- Odoo version and image;
- database name and data directory.

The discovery script is read-only and intentionally does not print container environment variables or database passwords.

## 2. Import only the existing custom addons

After identifying the host custom-addons path, copy it into a clean working tree. Replace `/actual/custom-addons` with the discovered path:

```bash
export EXISTING_ADDONS=/actual/custom-addons
export WORKTREE=/tmp/codestra-odoo-import

rm -rf "$WORKTREE"
git clone git@github.com:appolon1908-hue/Odoo.git "$WORKTREE"
rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='*.log' \
  "$EXISTING_ADDONS"/ "$WORKTREE/custom-addons"/

cd "$WORKTREE"
python3 scripts/validate_manifests.py
git status --short
```

Review every file before committing. Search for credentials and private keys. Create a feature branch, commit the import, and open a pull request rather than pushing directly to `main`.

## 3. Give the server read-only repository access

Create a dedicated deployment account. Do not add it to the `docker` group because Docker access is effectively root access.

```bash
sudo useradd --system --create-home --shell /bin/bash odoo-deploy 2>/dev/null || true
sudo install -d -m 0700 -o odoo-deploy -g odoo-deploy /home/odoo-deploy/.ssh
sudo -u odoo-deploy -H ssh-keygen \
  -t ed25519 \
  -C "odoo-deploy@$(hostname)" \
  -f /home/odoo-deploy/.ssh/github_odoo_readonly \
  -N ''
sudo cat /home/odoo-deploy/.ssh/github_odoo_readonly.pub
```

In GitHub, open **Settings -> Deploy keys -> Add deploy key** for this repository. Paste the public key and leave **Allow write access** unchecked.

Create an SSH host alias on the server:

```bash
sudo tee /home/odoo-deploy/.ssh/config >/dev/null <<'EOF'
Host github-odoo
  HostName github.com
  User git
  IdentityFile /home/odoo-deploy/.ssh/github_odoo_readonly
  IdentitiesOnly yes
EOF
sudo chown odoo-deploy:odoo-deploy /home/odoo-deploy/.ssh/config
sudo chmod 0600 /home/odoo-deploy/.ssh/config
```

Add GitHub's host key only after comparing its fingerprint with GitHub's official published SSH fingerprints:

```bash
sudo -u odoo-deploy -H ssh-keyscan -t ed25519 github.com \
  | sudo tee /home/odoo-deploy/.ssh/known_hosts >/dev/null
sudo chown odoo-deploy:odoo-deploy /home/odoo-deploy/.ssh/known_hosts
sudo chmod 0600 /home/odoo-deploy/.ssh/known_hosts
ssh-keygen -lf /home/odoo-deploy/.ssh/known_hosts
```

Verify repository access:

```bash
sudo -u odoo-deploy -H git ls-remote \
  git@github-odoo:appolon1908-hue/Odoo.git HEAD
```

## 4. Create the immutable server checkout

```bash
sudo install -d -m 0750 -o odoo-deploy -g odoo-deploy /srv/codestra-odoo
sudo -u odoo-deploy -H git clone \
  git@github-odoo:appolon1908-hue/Odoo.git \
  /srv/codestra-odoo/repository
```

The deployment operation should fetch `main`, validate that the requested SHA is an ancestor of `origin/main`, and check out that exact SHA in detached-head mode. It must refuse dirty working trees and concurrent deployments.

## 5. Mount the Git checkout into Odoo

Use the actual custom-addons destination reported by discovery. A common Docker mapping is:

```yaml
services:
  odoo:
    volumes:
      - /srv/codestra-odoo/repository/custom-addons:/mnt/extra-addons:ro
```

Keep the current Odoo core addon directories in `addons_path` and include the custom path. Do not replace the persistent `/var/lib/odoo` data volume with the Git checkout.

After changing the bind mount, recreate Odoo in staging first and confirm that the module list loads correctly.

## 6. Upgrade a reviewed module safely

For staging, use the exact merged SHA and upgrade only the affected modules. Replace placeholders with discovered values:

```bash
cd /srv/codestra-odoo/repository
sudo -u odoo-deploy -H git fetch --prune origin main
sudo -u odoo-deploy -H git checkout --detach <MERGED_SHA>

cd <COMPOSE_WORKING_DIRECTORY>
docker compose stop <ODOO_SERVICE>
docker compose run --rm --no-deps <ODOO_SERVICE> \
  odoo -d <STAGING_DATABASE> \
  -u <module_name_or_comma_separated_modules> \
  --stop-after-init --no-http
docker compose up -d <ODOO_SERVICE>
```

Before production, capture and verify a matching PostgreSQL dump and filestore archive, confirm rollback, run staging tests, and obtain explicit approval. Deploy the identical accepted SHA; do not rebuild or edit code on the server.

## 7. Add GitHub Actions deployment only after server validation

Use a GitHub-hosted runner that connects to a restricted `odoo-deploy` account over SSH and invokes one root-owned, allowlisted deployment command. Do not install a general-purpose self-hosted Actions runner on the production Odoo host.

Store connection material as GitHub **environment secrets**, separated between staging and production:

- `ODOO_DEPLOY_HOST`
- `ODOO_DEPLOY_PORT`
- `ODOO_DEPLOY_USER`
- `ODOO_DEPLOY_SSH_KEY`
- `ODOO_DEPLOY_HOST_KEY`

Do not store the Odoo database password in the workflow. Keep database and backup credentials in a root-readable server configuration used by the restricted deployment script.

Production deployment must be manual, protected by required reviewers, limited to the protected branch, and deploy the exact commit already accepted in staging.
