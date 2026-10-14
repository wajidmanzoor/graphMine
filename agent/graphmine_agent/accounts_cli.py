"""Local administrator commands; passwords never enter command arguments."""

import getpass
import json
from dataclasses import replace
from pathlib import Path

from .accounts import Accounts
from .database import Database


def add_accounts_parser(subcommands):
    parser = subcommands.add_parser(
        "accounts", help="create and manage local user accounts"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="the same persistent data root used by the server",
    )
    actions = parser.add_subparsers(dest="account_action", required=True)
    for name in ("create", "reset-password", "disable", "adopt-legacy"):
        action = actions.add_parser(name)
        action.add_argument("username")
    actions.add_parser("list")


def run_accounts(arguments, settings):
    if arguments.data_root:
        settings = replace(settings, data_root=arguments.data_root.resolve())
    accounts = Accounts(settings, Database(settings.database_path))
    action = arguments.account_action
    try:
        if action in {"create", "reset-password"}:
            password = getpass.getpass("Password (12–128 characters): ")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords do not match.")
            if action == "create":
                result = accounts.create_user(arguments.username, password)
            else:
                accounts.reset_password(arguments.username, password)
                result = {
                    "username": arguments.username,
                    "password_reset": True,
                    "sessions_revoked": True,
                }
        elif action == "disable":
            accounts.disable(arguments.username)
            result = {"username": arguments.username, "disabled": True}
        elif action == "adopt-legacy":
            result = {
                "username": arguments.username,
                "sessions_assigned": accounts.adopt_legacy(arguments.username),
            }
        else:
            result = accounts.list_users()
    except (ValueError, EOFError) as error:
        raise SystemExit(str(error)) from None
    print(json.dumps(result, indent=2))
    return 0
