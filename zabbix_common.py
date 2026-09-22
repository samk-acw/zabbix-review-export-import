#!/usr/bin/env python3
"""
Shared Zabbix API client and CLI helpers for zabbix-export.py / zabbix-import.py.
Targets Zabbix 6.0+.
"""
import itertools
import logging
import os
import sys

import requests
from packaging.version import parse as parse_version


class ZabbixAPIException(Exception):
    pass


class _ZabbixAPIObject:
    "Proxy for a single API object namespace, e.g. zabbix.host -> zabbix.host.get(...)"

    def __init__(self, api, object_name):
        self._api = api
        self._object_name = object_name

    def __getattr__(self, method_name):
        def call(*args, **kwargs):
            params = kwargs if kwargs else (args[0] if args else {})
            return self._api.call("{}.{}".format(self._object_name, method_name), params)

        return call


class ZabbixAPI:
    """
    Minimal Zabbix JSON-RPC client.
    Supports dot-chained calls like pyzabbix: zabbix.host.get(...)

    Auth transport is version-gated:
    - Zabbix >= 7.0: token sent as 'Authorization: Bearer <token>' header
      (body 'auth' was dropped in 7.2+)
    - Zabbix < 7.0: token sent as 'auth' field in the JSON-RPC body
      (Authorization header is not honoured pre-7.0)
    """

    def __init__(self, url, verify=False):
        self.url = url.rstrip("/")
        if not self.url.endswith("api_jsonrpc.php"):
            self.url = self.url + "/api_jsonrpc.php"
        self.session = requests.Session()
        self.session.verify = verify
        self.auth = None
        self.api_version = None
        self._id = itertools.count(1)

    def call(self, method, params=None, auth_required=True):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": next(self._id),
        }
        headers = {"Content-Type": "application/json-rpc"}

        if auth_required and self.auth:
            if self.api_version is not None and self.api_version >= parse_version("7.0"):
                headers["Authorization"] = "Bearer {}".format(self.auth)
            else:
                payload["auth"] = self.auth

        resp = self.session.post(self.url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            err = data["error"]
            raise ZabbixAPIException(
                "Error {}: {}, {}".format(
                    err.get("code"), err.get("message"), err.get("data")
                )
            )
        return data["result"]

    def login(self, username, password):
        "Authenticate with username/password, return the session token"
        self.api_version = parse_version(self.apiinfo.version())
        try:
            token = self.call(
                "user.login", {"username": username, "password": password}, auth_required=False
            )
        except ZabbixAPIException:
            # Zabbix < 5.4 used the "user" param name instead of "username"
            token = self.call(
                "user.login", {"user": username, "password": password}, auth_required=False
            )
        self.auth = token
        return token

    def use_token(self, token):
        "Authenticate with a pre-generated API token"
        self.api_version = parse_version(self.apiinfo.version())
        self.auth = token

    def __getattr__(self, object_name):
        return _ZabbixAPIObject(self, object_name)


def get_zabbix_connection(zbx_url, zbx_user=None, zbx_password=None, zbx_token=None):
    "Return an authenticated ZabbixAPI object, using a token if given, else username/password"
    zbx = ZabbixAPI(zbx_url)

    if zbx_token:
        logging.debug("Authenticating to Zabbix API with API token...")
        zbx.use_token(zbx_token)
    else:
        logging.debug("Authenticating to Zabbix API with username/password...")
        zbx.login(zbx_user, zbx_password)

    logging.info("Zabbix API version is: {}".format(zbx.api_version))
    return zbx


def environ_or_required(key):
    "Argparse environment vars helper"
    if os.environ.get(key):
        return {"default": os.environ.get(key)}
    else:
        return {"required": True}


def add_zabbix_connection_args(parser):
    "Add --zabbix-url/--zabbix-username/--zabbix-password/--zabbix-token args to parser"
    parser.add_argument(
        "--zabbix-url",
        action="store",
        help="REQUIRED. May be in ZABBIX_URL env var",
        **environ_or_required("ZABBIX_URL")
    )
    parser.add_argument(
        "--zabbix-username",
        action="store",
        default=os.environ.get("ZABBIX_USERNAME"),
        help="May be in ZABBIX_USERNAME env var. Required unless --zabbix-token is given",
    )
    parser.add_argument(
        "--zabbix-password",
        action="store",
        default=os.environ.get("ZABBIX_PASSWORD"),
        help="May be in ZABBIX_PASSWORD env var. Required unless --zabbix-token is given",
    )
    parser.add_argument(
        "--zabbix-token",
        action="store",
        default=os.environ.get("ZABBIX_TOKEN"),
        help="Zabbix API token. May be in ZABBIX_TOKEN env var. "
        "Takes precedence over username/password if both are given",
    )


def validate_zabbix_connection_args(parser, args):
    "Ensure either a token or a username+password was given"
    if not args.zabbix_token and not (args.zabbix_username and args.zabbix_password):
        parser.error(
            "Either --zabbix-token (or ZABBIX_TOKEN) or both --zabbix-username/--zabbix-password "
            "(or ZABBIX_USERNAME/ZABBIX_PASSWORD) must be provided"
        )


def init_logging(level):
    logger_format_string = "%(asctime)s %(levelname)-8s %(message)s"
    logging.basicConfig(level=level, format=logger_format_string, stream=sys.stdout)
