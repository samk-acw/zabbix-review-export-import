#!/usr/bin/env python3
import argparse
import json
import logging
import os
import re
import shutil
import xml.dom.minidom
from collections import OrderedDict

import anymarkup
import urllib3
import yaml

from zabbix_common import (
    add_zabbix_connection_args,
    get_zabbix_connection,
    init_logging,
    validate_zabbix_connection_args,
)

urllib3.disable_warnings()


def remove_none(obj):
    """
    Remove None value from any object
    As is from https://stackoverflow.com/a/20558778/6753144
    :param obj:
    :return:
    """
    if isinstance(obj, (list, tuple, set)):
        return type(obj)(remove_none(x) for x in obj if x is not None)
    elif isinstance(obj, dict):
        return type(obj)(
            (remove_none(k), remove_none(v))
            for k, v in obj.items()
            if k is not None and v is not None
        )
    else:
        return obj


def order_data(data):
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = order_data(value)
        return OrderedDict(sorted(data.items()))
    elif isinstance(data, list):
        data.sort(key=lambda x: str(x))
        return [order_data(x) for x in data]
    else:
        return data


def dumps_json(object, data, directory, key="name", save_yaml=False, drop_keys=[]):
    """
    Create JSON or yaml file in folder
    """
    subfolder = os.path.join(directory, object.lower())
    if not os.path.exists(subfolder):
        os.makedirs(subfolder)

    data = order_data(data)

    for item in data:
        if isinstance(key, tuple):
            logging.debug("Processing {}...".format(item[key[0]]))
        else:
            logging.debug("Processing {}...".format(item[key]))
        if drop_keys:
            for drop_key in drop_keys:
                if drop_key in item:
                    item.pop(drop_key, None)
        txt = json.dumps(item, indent=4)

        # Remove bad characters from name
        if isinstance(key, tuple):
            name = "_".join(map(lambda x: item[x], key))
        else:
            name = item[key]
        name = re.sub(r'[\\/:"*?<>|]+', " ", name)
        filename = "{}/{}.{}".format(subfolder, name, "yaml" if save_yaml else "json")
        filename = os.path.abspath(filename)

        logging.debug("Write to file '{}'".format(filename))

        if save_yaml:
            txt = convert_to_yaml_without_none(txt)

        with open(filename, mode="w", encoding="utf-8", newline="\n") as file:
            file.write(txt)


def convert_to_yaml_without_none(txt):
    """
    Convert any object to OrderDict without None value
    """

    def represent_dict_order(obj, data):
        return obj.represent_mapping("tag:yaml.org,2002:map", data.items())

    raw = anymarkup.parse(txt)
    raw = remove_none(raw)

    yaml.add_representer(OrderedDict, represent_dict_order)
    txt = yaml.dump(
        raw,
        default_flow_style=False,
        width=10000,
        allow_unicode=True,
        explicit_start=True,
        explicit_end=True,
    )
    return txt


def dump_xml(object, txt, name, directory, save_yaml=False):
    """
    Create XML or YAML in folder
    """
    folder = os.path.join(directory, object.lower())
    if not os.path.exists(folder):
        os.makedirs(folder)

    # Remove bad characters from name
    name = re.sub(r'[\\/:"*?<>|]+', " ", name)
    filename = "{}/{}.{}".format(folder, name, "yaml" if save_yaml else "xml")
    filename = os.path.abspath(filename)

    # Remove bad lines from content
    # date
    txt = re.sub(r"<date>.*<\/date>", "", txt)
    # zabbix.version
    # txt = re.sub(r'<version>.*<\/version>', '', txt)

    # ppretty xml
    xml_ = xml.dom.minidom.parseString(
        txt
    )  # or xml.dom.minidom.parseString(xml_string)
    txt = xml_.toprettyxml(indent="  ", encoding="UTF-8")
    txt = txt.decode()

    # replace xml quot to normal readable "
    txt = txt.replace("&quot;", '"')

    if save_yaml:
        txt = convert_to_yaml_without_none(txt)

    logging.debug("Write to file '{}'".format(filename))
    with open(filename, mode="w", encoding="utf-8", newline="\n") as file:
        file.write(txt)


DEFAULT_EXTERNAL_SCRIPTS_DIR = "/usr/lib/zabbix/externalscripts"


def get_external_scripts_dir(server_config, override=None):
    """
    Resolve the ExternalScripts directory: explicit override wins, else parse
    'ExternalScripts=' out of the Zabbix server config file, else fall back to
    the Zabbix-packaged default.
    """
    if override:
        logging.debug("Using explicit external scripts dir: {}".format(override))
        return override

    if server_config and os.path.isfile(server_config):
        try:
            with open(server_config, "r", encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^\s*ExternalScripts\s*=\s*(.+?)\s*$", line)
                    if m:
                        logging.debug(
                            "Using ExternalScripts dir from '{}': {}".format(
                                server_config, m.group(1)
                            )
                        )
                        return m.group(1)
        except OSError as e:
            logging.warning("Could not read '{}': {}".format(server_config, e))

    logging.debug(
        "Using default external scripts dir: {}".format(DEFAULT_EXTERNAL_SCRIPTS_DIR)
    )
    return DEFAULT_EXTERNAL_SCRIPTS_DIR


def main(
    zabbix_,
    save_yaml,
    directory,
    only="all",
    server_config=None,
    external_scripts_dir_override=None,
):
    # XML
    # Standart zabbix xml export via API
    def export(zabbix_api, options_key, itemid, name, folder=None):
        """
        Export one type: hosts, templates, host/template groups, maps, ...
        https://www.zabbix.com/documentation/current/en/manual/api/reference/configuration/export
        """
        folder = folder or options_key
        logging.info("Export {}".format(folder))
        items = zabbix_api.get()
        for item in items:
            logging.debug("Processing {}...".format(item[name]))
            try:
                txt = zabbix_.configuration.export(
                    format="xml", options={options_key: [item[itemid]]}
                )
                dump_xml(
                    object=folder,
                    txt=txt,
                    name=item[name],
                    save_yaml=save_yaml,
                    directory=directory,
                )
            except Exception as e:
                logging.error(
                    "Exception during export of template: {}".format(item[name])
                )
                logging.error(e)

    api_version = zabbix_.api_version
    logging.debug("Source Zabbix server version: {}".format(api_version))

    if yaml:
        logging.info("Convert all format to yaml")

    logging.info("Start export XML part...")
    if only in ("all", "hostgroups"):
        export(zabbix_.hostgroup, "host_groups", "groupid", "name", folder="hostgroups")
    if only in ("all", "templategroups"):
        export(
            zabbix_.templategroup,
            "template_groups",
            "groupid",
            "name",
            folder="templategroups",
        )
    if only in ("all", "hosts"):
        export(zabbix_.host, "hosts", "hostid", "name")
    if only in ("all", "templates"):
        export(zabbix_.template, "templates", "templateid", "name")
    if only in ("all", "maps"):
        export(zabbix_.map, "maps", "sysmapid", "name")

    # JSON
    # not support `export` method
    # Read more in https://www.zabbix.com/documentation/4.0/manual/api/reference/configuration/export
    logging.info("Start export JSON part...")

    if only in (
        "all",
        "mediatypes",
        "users",
        "actions",
        "dashboards",
        "usermacro",
    ):
        logging.info("Processing mediatypes...")
        mediatypes = zabbix_.mediatype.get()
        mediatypeid2mediatype = {
            "0": "__ALL__"
        }  # key: mediatypeid, value: mediatype name
        for mt in mediatypes:
            mediatypeid2mediatype[mt["mediatypeid"]] = mt["name"]

        if only in ("all", "mediatypes"):
            dumps_json(
                object="mediatypes",
                data=mediatypes,
                key="name",
                save_yaml=save_yaml,
                directory=directory,
                drop_keys=["mediatypeid"],
            )

    if only in ("all", "images"):
        logging.info("Processing images...")
        images = zabbix_.image.get()
        dumps_json(
            object="images",
            data=images,
            save_yaml=save_yaml,
            directory=directory,
            drop_keys=["imageid"],
        )

    if only in ("all", "usergroups", "actions", "dashboards", "usermacro"):
        logging.info("Processing usergroups...")
        usergroups = zabbix_.usergroup.get(
            selectHostGroupRights="extend", selectTemplateGroupRights="extend"
        )
        usergroupid2usergroup = {}  # key: usergroupid, value: usergroup name
        for ug in usergroups:
            usergroupid2usergroup[ug["usrgrpid"]] = ug["name"]

        # existing host/template groups
        result = zabbix_.hostgroup.get(output=["groupid", "name"])
        groupid2group = {}  # key: groupid, value: group name
        for group in result:
            groupid2group[group["groupid"]] = group["name"]
        result = zabbix_.templategroup.get(output=["groupid", "name"])
        tgroupid2tgroup = {}  # key: groupid, value: group name
        for group in result:
            tgroupid2tgroup[group["groupid"]] = group["name"]

        # resolve hostgroupids/templategroupids:
        for usergroup in usergroups:
            usergroup["hostgroup_rights"] = [
                {"id": groupid2group[r["id"]], "permission": r["permission"]}
                for r in usergroup["hostgroup_rights"]
            ]
            usergroup["templategroup_rights"] = [
                {"id": tgroupid2tgroup[r["id"]], "permission": r["permission"]}
                for r in usergroup["templategroup_rights"]
            ]

        if only in ("all", "usergroups"):
            dumps_json(
                object="usergroups",
                data=usergroups,
                save_yaml=save_yaml,
                directory=directory,
                drop_keys=["usrgrpid"],
            )

    if only in ("all", "users", "actions", "dashboards", "usermacro"):
        logging.info("Processing users...")
        users = zabbix_.user.get(selectMedias="extend", selectUsrgrps="extend")
        userid2user = {}  # key: userid, value: username
        for u in users:
            userid2user[u["userid"]] = u["username"]
            for ug in u["usrgrps"]:
                ug.pop("usrgrpid", None)
            for m in u["medias"]:
                m.pop("mediaid", None)
                m.pop("userid", None)
                m["mediatypeid"] = mediatypeid2mediatype[
                    m["mediatypeid"]
                ]  # resolve mediatype

        if only in ("all", "users"):
            dumps_json(
                object="users",
                data=users,
                key="username",
                save_yaml=save_yaml,
                directory=directory,
                drop_keys=["userid", "attempt_clock", "attempt_failed", "attempt_ip"],
            )

    if only in ("all", "proxy"):
        logging.info("Processing proxy...")
        proxys = zabbix_.proxy.get()
        # Zabbix 7.0 renamed the proxy "host" field to "name"
        proxy_name_key = "name" if (proxys and "name" in proxys[0]) else "host"
        dumps_json(
            object="proxy",
            data=proxys,
            key=proxy_name_key,
            save_yaml=save_yaml,
            directory=directory,
            drop_keys=["lastaccess", "last_access", "proxyid"],
        )

    if only in ("all", "globalmacro"):
        logging.info("Processing global macros...")
        global_macros = zabbix_.usermacro.get(globalmacro="true")
        dumps_json(
            object="globalmacro",
            data=global_macros,
            key="macro",
            save_yaml=save_yaml,
            directory=directory,
            drop_keys=["globalmacroid"],
        )

    # logging.info("Processing services...")
    # services = zabbix_.service.get(selectParent=['name'], selectTimes='extend')
    # dumps_json(object='services', data=services, key=('name', 'serviceid'), save_yaml=save_yaml, directory=directory, drop_keys=["status"])

    if only in ("all", "maintenances"):
        logging.info("Processing maintenances...")
        maintenances = zabbix_.maintenance.get(
            selectGroups=["name"], selectHosts=["name"], selectTimeperiods="extend"
        )
        # sort hosts in maintenances by hostname to provide stable order:
        for m in maintenances:
            m["hosts"] = sorted(
                m["hosts"], key=lambda i: i["name"]
            )  # sort to stabilize dumps
            m["groups"] = sorted(
                m["groups"], key=lambda i: i["name"]
            )  # sort to stabilize dumps
            for h in m["hosts"]:
                h.pop("hostid", None)
            for g in m["groups"]:
                g.pop("groupid", None)
            for tp in m["timeperiods"]:
                tp.pop("timeperiodid", None)
            m["hostids"] = m.pop("hosts")  # rename for easy import
            m["groupids"] = m.pop("groups")  # rename for easy import
        dumps_json(
            object="maintenances",
            data=maintenances,
            save_yaml=save_yaml,
            directory=directory,
            drop_keys=["maintenanceid"],
        )

    if only in ("all", "dashboards"):
        logging.info("Processing dashboard lookup tables...")

        graphid2graph = {}  # key: graphid, value: "hostname,graphname"
        graphs = zabbix_.graph.get(
            output=["graphid", "name"], selectHosts=["name"], templated=False
        )
        for g in graphs:
            if g["hosts"]:  # graph not in template
                graphid2graph[g["graphid"]] = "{},{}".format(
                    g["hosts"][0]["name"], g["name"]
                )

        itemid2item = {}  # key: itemid, value: "hostname, key_"
        items = zabbix_.item.get(
            output=["key_", "itemid"], selectHosts=["name"], webitems=True
        )
        for i in items:
            if i["hosts"]:  # item not in template
                itemid2item[i["itemid"]] = "{},{}".format(
                    i["hosts"][0]["name"], i["key_"]
                )

        itemid2proto = {}  # key: itemid, value: "hostname, key_"
        itemprototypes = zabbix_.itemprototype.get(
            output=["key_", "itemid"], selectHosts=["name"]
        )
        for i in itemprototypes:
            if i["hosts"]:
                itemid2proto[i["itemid"]] = "{},{}".format(
                    i["hosts"][0]["name"], i["key_"]
                )

        graphid2proto = {}  # key: graphid, value: "hostname, graphname"
        graphprototypes = zabbix_.graphprototype.get(
            output=["graphid", "name"], selectHosts=["name"]
        )
        for gp in graphprototypes:
            if gp["hosts"]:
                graphid2proto[gp["graphid"]] = "{},{}".format(
                    gp["hosts"][0]["name"], gp["name"]
                )

    if only in ("all", "actions", "usermacro"):
        logging.info("Processing action...")
        actions = zabbix_.action.get(
            selectOperations="extend",
            selectFilter="extend",
            selectRecoveryOperations="extend",
            selectUpdateOperations="extend",
        )
        # existing templates
        result = zabbix_.template.get(output=["host", "templateid"])
        templateid2template = {}  # key: templateid, value: template name
        for template in result:
            templateid2template[template["templateid"]] = template["host"]
        # existing hosts
        result = zabbix_.host.get(output=["name", "hostid"])
        hostid2host = {}  # key: hostid, value: host name
        for host in result:
            hostid2host[host["hostid"]] = host["name"]
        # existing triggers
        result = zabbix_.trigger.get(
            output=["description", "triggerid"], selectHosts=["name"]
        )
        triggerid2trigger = (
            {}
        )  # key: triggerid, value: {description: trigger description, host: host name}
        for trigger in result:
            triggerid2trigger[trigger["triggerid"]] = {
                "description": trigger["description"],
                "host": trigger["hosts"][0]["name"] if trigger["hosts"] else "",
            }

        # resolve templateids/groupids/mediatypeids/userids/usergroupids:
        for action in actions:
            action["filter"]["conditions"] = sorted(
                action["filter"]["conditions"], key=lambda i: i["formulaid"]
            )  # sort to stabilize dumps
            action["filter"]["formula"] = action["filter"]["eval_formula"]
            action["filter"].pop("eval_formula", None)
            for action_type in (
                "operations",
                "update_operations",
                "recovery_operations",
            ):
                for op in action[action_type]:
                    op.pop("actionid", None)
                    op.pop("operationid", None)
                    if "optemplate" in op:
                        for aa in op["optemplate"]:
                            aa["templateid"] = templateid2template[aa["templateid"]]
                            aa.pop("operationid", None)
                    if "opgroup" in op:
                        for aa in op["opgroup"]:
                            aa["groupid"] = groupid2group[aa["groupid"]]
                            aa.pop("operationid", None)
                    if "opmessage" in op:
                        op["opmessage"]["mediatypeid"] = mediatypeid2mediatype[
                            op["opmessage"]["mediatypeid"]
                        ]
                        op["opmessage"].pop("operationid", None)
                    if "opmessage_grp" in op:
                        for aa in op["opmessage_grp"]:
                            aa["usrgrpid"] = usergroupid2usergroup[aa["usrgrpid"]]
                            aa.pop("operationid", None)
                    if "opmessage_usr" in op:
                        for aa in op["opmessage_usr"]:
                            aa["userid"] = userid2user[aa["userid"]]
                            aa.pop("operationid", None)
                    if "opcommand" in op:
                        op["opcommand"].pop("operationid", None)
                    if "opcommand_hst" in op:
                        for aa in op["opcommand_hst"]:
                            if str(aa["hostid"]) != "0":  # '0' means current host
                                aa["hostid"] = hostid2host[aa["hostid"]]
                            aa.pop("operationid", None)
                            aa.pop("opcommand_hstid", None)
                    if "opcommand_grp" in op:
                        for aa in op["opcommand_grp"]:
                            aa["groupid"] = groupid2group[aa["groupid"]]
                            aa.pop("operationid", None)
                            aa.pop("opcommand_grpid", None)
                    if "opconditions" in op:
                        for aa in op["opconditions"]:
                            aa.pop("operationid", None)
                            aa.pop("opconditionid", None)
            for condition in action["filter"]["conditions"]:
                if condition["conditiontype"] == "0":  # hostgroup
                    condition["value"] = groupid2group[condition["value"]]
                if condition["conditiontype"] == "1":  # host
                    condition["value"] = hostid2host[condition["value"]]
                if condition["conditiontype"] == "13":  # template
                    condition["value"] = templateid2template[condition["value"]]
                if condition["conditiontype"] == "2":  # trigger
                    condition["value2"] = triggerid2trigger[condition["value"]]["host"]
                    condition["value"] = triggerid2trigger[condition["value"]][
                        "description"
                    ]

        if only in ("all", "actions"):
            dumps_json(
                object="actions",
                data=actions,
                save_yaml=save_yaml,
                directory=directory,
                drop_keys=["actionid"],
            )

    if only in ("all", "usermacro"):
        logging.info("Processing user macros...")
        # usermacro.get() also returns host-prototype macros, which live in a
        # separate ID namespace from hosts/templates and aren't exported here.
        user_macros = []
        for umacro in zabbix_.usermacro.get():
            if umacro["hostid"] in hostid2host:
                umacro["hostid"] = hostid2host[umacro["hostid"]]
            elif umacro["hostid"] in templateid2template:
                umacro["hostid"] = templateid2template[umacro["hostid"]]
            else:
                logging.warning(
                    "Skipping usermacro '{}' on unresolvable hostid {} "
                    "(likely a host prototype macro, not exported)".format(
                        umacro["macro"], umacro["hostid"]
                    )
                )
                continue
            user_macros.append(umacro)
        dumps_json(
            object="usermacro",
            data=user_macros,
            key=("macro", "hostid"),
            save_yaml=save_yaml,
            directory=directory,
            drop_keys=["hostmacroid"],
        )

    if only in ("all", "dashboards"):
        logging.info("Processing dashboards...")
        dashboards = zabbix_.dashboard.get(
            selectPages="extend", selectUsers="extend", selectUserGroups="extend"
        )
        for d in dashboards:
            d["userid"] = userid2user[d["userid"]]
            for u in d["users"]:
                u["userid"] = userid2user[u["userid"]]
            for ug in d["userGroups"]:
                ug["usrgrpid"] = usergroupid2usergroup[ug["usrgrpid"]]
            for page in d["pages"]:
                page.pop("dashboard_pageid", None)
                for w in page["widgets"]:
                    w.pop("widgetid", None)
                    w["fields"] = sorted(
                        w["fields"], key=lambda i: i["name"]
                    )  # sort to stabilize dumps
                    for f in w["fields"]:
                        if f["type"] == "4":  # item
                            f["value"] = itemid2item[f["value"]]
                        elif f["type"] == "5":  # item prototype
                            f["value"] = itemid2proto[f["value"]]
                        elif f["type"] == "6":  # graph
                            f["value"] = graphid2graph[f["value"]]
                        elif f["type"] == "7":  # graph prototype
                            f["value"] = graphid2proto[f["value"]]

        dumps_json(
            object="dashboards",
            data=dashboards,
            directory=directory,
            save_yaml=save_yaml,
            drop_keys=["dashboardid"],
        )

    if only in ("all", "scripts"):
        logging.info("Processing scripts...")
        # "External check" items/item prototypes/discovery rules (type 10) have a well-defined
        # key_ format of "scriptname[params]", referencing a file in Zabbix's ExternalScripts
        # directory. Alerts > Scripts entries of type "Script" are NOT a reliable source of a
        # copyable filename here: their "command" field can be an absolute path, embed
        # macros/params, or be a full shell command line (e.g. "ping -c 3 {HOST.CONN}; case $?
        # in ...") rather than a bare filename in ExternalScripts, so they're excluded from the
        # file copy below (the scripts JSON dump further down still captures their definitions
        # as-is).
        EXTERNAL_CHECK_TYPE = "10"
        script_names = set()

        for i in zabbix_.item.get(
            output=["key_"], filter={"type": EXTERNAL_CHECK_TYPE}
        ):
            script_names.add(i["key_"].split("[", 1)[0])
        for i in zabbix_.itemprototype.get(
            output=["key_"], filter={"type": EXTERNAL_CHECK_TYPE}
        ):
            script_names.add(i["key_"].split("[", 1)[0])
        for i in zabbix_.discoveryrule.get(
            output=["key_"], filter={"type": EXTERNAL_CHECK_TYPE}
        ):
            script_names.add(i["key_"].split("[", 1)[0])
        for i in zabbix_.discoveryruleprototype.get(
            output=["key_"], filter={"type": EXTERNAL_CHECK_TYPE}
        ):
            script_names.add(i["key_"].split("[", 1)[0])

        scripts = zabbix_.script.get(output="extend")

        external_scripts_dir = get_external_scripts_dir(
            server_config, external_scripts_dir_override
        )
        dst_dir = os.path.join(directory, "scripts", "files")
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)
        for name in sorted(script_names):
            src = os.path.join(external_scripts_dir, name)
            dst = os.path.join(dst_dir, os.path.basename(name))
            try:
                shutil.copyfile(src, dst)
            except OSError as e:
                logging.warning(
                    "Could not copy external script file '{}': {}".format(src, e)
                )

        dumps_json(
            object="scripts",
            data=scripts,
            save_yaml=save_yaml,
            directory=directory,
            drop_keys=["scriptid"],
        )


def parse_args():
    parser = argparse.ArgumentParser()

    add_zabbix_connection_args(parser)

    parser.add_argument(
        "--directory",
        action="store",
        default="./",
        help="Directory where exported files will be saved",
    )

    parser.add_argument(
        "--save-yaml",
        action="store_true",
        help="All file's formats will be converted to YAML format",
    )

    parser.add_argument("--debug", action="store_true", help="Show debug output")

    parser.add_argument(
        "--zabbix-server-config",
        action="store",
        default="/etc/zabbix/zabbix_server.conf",
        help="Path to zabbix_server.conf, used to resolve the ExternalScripts directory "
        "for 'scripts' export. Default: %(default)s",
    )
    parser.add_argument(
        "--external-scripts-dir",
        action="store",
        default=None,
        help="Explicit path to the ExternalScripts directory, overrides "
        "--zabbix-server-config detection",
    )

    parser.add_argument(
        "--only",
        choices=[
            "all",
            "hosts",
            "hostgroups",
            "templategroups",
            "templates",
            "maps",
            "mediatypes",
            "images",
            "usergroups",
            "users",
            "proxy",
            "globalmacro",
            "maintenances",
            "actions",
            "usermacro",
            "dashboards",
            "scripts",
        ],
        default="all",
        help="Only object type that will be exported, default is %(default)s",
    )

    args = parser.parse_args()
    validate_zabbix_connection_args(parser, args)
    return args


if __name__ == "__main__":
    args = parse_args()
    level = logging.INFO
    if args.debug:
        level = logging.DEBUG
    init_logging(level=level)

    zabbix_ = get_zabbix_connection(
        args.zabbix_url, args.zabbix_username, args.zabbix_password, args.zabbix_token
    )

    logging.info("All files will be save in {}".format(os.path.abspath(args.directory)))
    main(
        zabbix_=zabbix_,
        save_yaml=args.save_yaml,
        directory=args.directory,
        only=args.only,
        server_config=args.zabbix_server_config,
        external_scripts_dir_override=args.external_scripts_dir,
    )
