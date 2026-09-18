"""``ign`` Typer entry point.

Every subcommand group registers here with ``app.add_typer(...)``. The
pyproject.toml ``[project.scripts]`` block exports ``ign`` bound to
``ignition_gen_sdk.cli:app``.
"""
import typer

from .cmd_alarm_journal import alarm_journal_app
from .cmd_api import api_cmd
from .cmd_builtins import builtins_app
from .cmd_component import component_app
from .cmd_db_conn import db_conn_app
from .cmd_diff import diff_cmd
from .cmd_driver import driver_app
from .cmd_icons import icons_app
from .cmd_logs import logs_cmd
from .cmd_openapi import openapi_app
from .cmd_page import page_app
from .cmd_provider import provider_app
from .cmd_session_props import session_props_app
from .cmd_style_class import style_class_app
from .cmd_stylesheet import stylesheet_app
from .cmd_alarm_pipeline import alarm_pipeline_app
from .cmd_named_query import named_query_app
from .cmd_script import script_app
from .cmd_tag import tag_app
from .cmd_theme import theme_app
from .cmd_tools import tools_app
from .cmd_view import view_app

app = typer.Typer(
    name="ign",
    help="Ignition 8.3 agent SDK: author tags, views and project resources; call the gateway API.",
    no_args_is_help=True,
)

app.add_typer(tag_app, name="tag", help="Tag operations: build, push.")
app.add_typer(view_app, name="view", help="Perspective view operations: build, write.")
app.add_typer(script_app, name="script", help="Project library script operations: write.")
app.add_typer(page_app, name="page", help="Perspective page-config: mount + list pages.")
app.add_typer(session_props_app, name="session-props", help="Perspective session-props: declare custom session properties.")
app.add_typer(named_query_app, name="named-query", help="Named query operations: write, list.")
app.add_typer(style_class_app, name="style-class", help="Perspective style classes: write, list + delete.")
app.add_typer(stylesheet_app, name="stylesheet", help="Perspective project stylesheet: upsert/show ign CSS blocks.")
app.add_typer(theme_app, name="theme", help="Perspective themes: list, write, copy-base + delete.")
app.add_typer(provider_app, name="provider", help="Tag provider CRUD.")
app.add_typer(db_conn_app, name="db-conn", help="Database connection CRUD.")
app.add_typer(alarm_journal_app, name="alarm-journal", help="Alarm journal profile CRUD.")
app.add_typer(alarm_pipeline_app, name="alarm-pipeline", help="Alarm pipelines: show + surgical text replace.")
app.add_typer(driver_app, name="driver", help="Database driver introspection: list, describe.")
app.add_typer(component_app, name="component", help="Component palette: list.")
app.add_typer(openapi_app, name="openapi", help="Gateway OpenAPI spec: fetch, gen, docs.")
app.add_typer(tools_app, name="tools", help="Project tools in .ign_tools/: list, run.")
app.add_typer(builtins_app, name="builtins", help="8.3 function catalog: refresh, audit.")
app.add_typer(icons_app, name="icons", help="Perspective icon sprites: list.")
app.command("api", help="Generic Ignition HTTP API call (curl-like).")(api_cmd)
app.command("diff")(diff_cmd)
app.command("logs", help="Query the gateway log (runtime debugging; read-only).")(logs_cmd)


if __name__ == "__main__":
    app()
