# Zabbix Review and Export/Import
With Zabbix review and export (backup)/import you can create review mechanism and save/restore zabbix configuration as code (Monitoring as Code)

You can export (backup) all hosts templates and other object with `zabbix-export.py` script.

You can also import (restore) many types of zabbix objects from YAML dump with `zabbix-import.py` script (note that order of import is
**matters**, i.e., you cant add user if there is no mediatype for them, etc...). Already existed objects will be skipped. Object type is
autodetected, but may be pointed manually (it is much faster for single-file import operations)/

- [Requirements](#requirements)
- [Make export and backup](#make-export-and-backup)
- [Restore from YAML dump](#restore-from-yaml-dump)
- [Make review](#make-review)
  - [Notes](#notes)
- [Supported objects](#supported-objects)
- [Known issues](#known-issues)
- [Screenshots](#screenshots)

# Requirements
- Installed [Python >=3.8](https://www.python.org/downloads/)
- A Zabbix server **6.0 through 7.4+**. Older versions are not supported: Zabbix removed the
  Applications API and the Screens API in 5.4 (replaced by item tags and dashboards), so those
  code paths are gone from this tool rather than kept as dead weight.


If you want use [review (or Monitoring as Code](#make-review):
- [GitLab](https://gitlab.com/) - you own instance with configured [GitLab CI](https://docs.gitlab.com/ee/ci/) or cloud account
- `git`


## Authentication
Either an API token, or a username/password pair:
```bash
# API token (Users -> API tokens in the Zabbix UI, or the `token.create` API method)
export ZABBIX_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# or username/password
export ZABBIX_USERNAME="user.name"
export ZABBIX_PASSWORD="secret"
```
Both scripts also accept `--zabbix-token` / `--zabbix-username` / `--zabbix-password` directly.
Against Zabbix 7.0+ the token is sent as an `Authorization: Bearer` header; against 6.x it's sent
in the request body, matching what each server version actually supports.

## Make export and backup
It's simple to start use this script as backup mechanism:
```bash
# git clone THIS_REPO or download and unpack archive

python -mpip install -r requirements.txt

# smoke test :)
python ./zabbix-export.py --help

# backup to current folder, save XML and JSON
python ./zabbix-export.py --zabbix-url https://zabbix.example.com --zabbix-token xxxx

# backup only hosts in YAML format
python ./zabbix-export.py --save-yaml --zabbix-url https://zabbix.example.com --zabbix-token xxxx --only hosts

# backup to custom folder in YAML format
python ./zabbix-export.py --save-yaml --directory /home/username/path/to/zabbix-yaml --zabbix-url https://zabbix.example.com --zabbix-token xxxx
```

### Exporting external scripts
Two distinct Zabbix features reference files in the server's `ExternalScripts` directory (set by
`ExternalScripts=` in `zabbix_server.conf`, default `/usr/lib/zabbix/externalscripts`) rather than
storing the script body in the database:
- **External check** items/item prototypes (`key_` like `check_oracle.sh["-h","{HOST.CONN}"]`) —
  in most setups this is what's actually populating that directory.
- Alerts -> Scripts entries of type "Script" (as opposed to Webhook/SSH/IPMI/Telnet, which are
  fully stored in the database already).

`--only scripts` scans hosts, templates and LLD rules for external-check items, plus the Scripts
table for type-"Script" entries, and copies every referenced file it can find alongside the
Scripts table's JSON dump:
```bash
# --zabbix-server-config defaults to /etc/zabbix/zabbix_server.conf; override with
# --external-scripts-dir if the ExternalScripts path isn't discoverable from there
python ./zabbix-export.py --zabbix-url https://zabbix.example.com --zabbix-token xxxx --only scripts
```
Files land in `<directory>/scripts/files/`. A script whose file can't be found or read is logged
as a warning and skipped — it doesn't fail the rest of the export.

## Restore from YAML dump
Few examples:
```bash
export ZABBIX_URL="https://zabbix.instan.ce"
export ZABBIX_TOKEN="xxxx"

./zabbix-import.py /path/to/file.yaml

./zabbix-import.py --type host /path/fo/repo/hosts/*
```
## Make review
You want to make review (Moniroting as Code). Read more on habr.com: [RU](#), [EN translated](#)
1. Fork this repository to you GitLab account or instance (e.g. `groupname/zabbix-review-export`)
2. Create repository where will be saved XML and YAML (e.g. two repositories `groupname/zabbix-xml` and `groupname/zabbix-yaml`. Do first (init) commit (create empty `README.md`).
3. Create two branches in this repos: `master` and `develop`. In repository `groupname/zabbix-xml` set `develop` as a [default branch](https://docs.gitlab.com/ee/user/project/repository/branches/#default-branch).
4. Specify [Project Variables](https://docs.gitlab.com/ee/ci/variables/#variables) for all variables, specified on top of [.gitlab-ci.yml](./.gitlab-ci.yml)
5. Change jobs in `.gitlab-ci.yml` and leave the ones you need job in `.gitlab-ci.yml` and change to you environment (see commented examples block).
6. Try to run manual job `YAML zabbix`
7. Create merge request `develop=>master` in `zabbix-yaml`. For first time you can merge without review, it's too hard :)
8. Configure [Schedule](https://docs.gitlab.com/ee/user/project/pipelines/schedules.html) (eg. every week)
9. Change some host, template or other [supported objects](#supported-objects) in zabbix, run manual job and create merge request again. Enjoy!

### Notes
Use two repositories for XML+JSON (raw-format) and readable YAML format:
- `XML` + `JSON` will be useful if you want restore some object after remove or a large number of changes.
- `YAML` format is more suitable for people to read and review changes. The script removes all empty values.

Create empty merge request `develop=>master` after merge and receive notifications at changes (schedule or manual jobs run) on your email.

To answer for the question "Who make this changes?" you need use [Zabbix Audit](https://www.zabbix.com/documentation/4.0/manual/web_interface/frontend_sections/reports/audit). It's difficult but possible.

## Supported objects
Use standard [zabbix export functional](https://www.zabbix.com/documentation/current/en/manual/api/reference/configuration/export):
- hosts
- templates
- host groups
- template groups
- maps

Representing objects as JSON using the API:
- mediatypes, images, usergroups, users, proxy, globalmacro, maintenances, actions, usermacro,
  dashboards, scripts (including the referenced external-script files, see above)

## Breaking changes from previous versions of this tool
- Targets Zabbix 6.0+ only; screens and applications are gone (both removed server-side in 5.4).
- Host groups and template groups export to separate `hostgroups/`/`templategroups/` folders
  instead of a combined `groups/` folder, mirroring Zabbix 6.2's own split of the two.
- Standalone value-map export/import is gone; value maps are scoped to a host/template as of
  Zabbix 6.4 and are already embedded in that host's/template's own export.

## Known issues
- [ZBX-15175](https://support.zabbix.com/browse/ZBX-15175): Zabbix export - host's xml does not contain overrides or diff to templates (e.g. item's storage period, trigger.priority, trigger.status=disables\enabled)
- [ZBXNEXT-4862](https://support.zabbix.com/browse/ZBXNEXT-4862): The implementation of functionality in Zabbix. Zabbix configuration as code - save XML in git repository
- Host/item-prototype import carries over item `tags` (the replacement for the old
  `applications` grouping) but doesn't attempt any other reconciliation of tag data.


## Screenshots
YAML change action:
![yaml-change-action.png](./docs/yaml-change-action.png)

YAML change trigger expression:
![yaml-change-trigger-expression.png](./docs/yaml-change-trigger-expression.png)

YAML link template
![yaml-link-template.jpg](./docs/yaml-link-template.jpg)

XML change templates (but we recommend use YAML for review and XML only for backup):
![xml-change-templates.jpg](./docs/xml-change-templates.jpg)
