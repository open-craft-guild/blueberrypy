import logging
from importlib import import_module

import os
import sys
import re
import textwrap

from datetime import datetime
from functools import partial
from code import InteractiveConsole

import cherrypy
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from docopt import docopt
from cherrypy.process import servers
from cherrypy.process.plugins import Daemonizer, DropPrivileges, PIDFile

import blueberrypy
import blueberrypy.shell as shell

from blueberrypy.config import BlueberryPyConfiguration
from blueberrypy.project import create_project
from blueberrypy.template_engine import configure_jinja2
from blueberrypy.exc import BlueberryPyNotConfiguredError


logger = logging.getLogger(__name__)


def get_answer(prompt=None, type=str, default=None, matcher=None, required=False,
               config=None):

    if callable(default):
        default = default(config)

    if isinstance(required, basestring) and not config.get(required):
        return '' if type == str else False

    if type == bool and not matcher:
        matcher = re.compile(r"^[YyNn]+.*$").match

    while True:
        user_input = raw_input(prompt(config) if callable(prompt) else prompt)
        if not user_input and default is not None:
            return default
        if not user_input and not required:
            return user_input
        elif not user_input and required:
            logger.error("A value is required.")
            continue
        elif user_input:
            if matcher and not matcher(user_input):
                if type == str:
                    logger.error(
                        "'{0}' does not match the required format.".format(user_input))
                elif type == bool:
                    logger.error("Please answer Y or N.")
                continue
            else:
                if matcher:
                    group = matcher(user_input).group(0)
                    return group if type == str else group.lower().startswith('y')
                return user_input


def create(**kwargs):
    """
    Create a project skeleton.

    usage: blueberrypy create [options]


    options:
      -h, --help            show this help message and exit
      -p PATH, --path PATH  the path to create the project. default is the current
                            directory
      -d, --dry-run         do not write skeleton. prints out the content instead

    """

    path = None
    if kwargs.get("path"):
        path = os.path.abspath(kwargs.get("path"))
        if not os.path.exists(path):
            os.mkdir(path)
            logger.info("Path not found, a directory '%s' has been created." % path)

    config = {}
    config["path"] = path or os.getcwdu()
    config["current_year"] = datetime.now().year

    valid_package_name = re.compile(r"^[a-z_]+$")
    valid_version_re = re.compile(r"^\d+.\d+(.\d+)*(a|b|c|rc\d+(.\d+)?)?(.post\d+)?(.dev\d+)?$")
    valid_email_re = re.compile(r"^.+@.+$")

    questions = (
        ("project_name", dict(prompt="Project name: ")),

        ("package", dict(prompt=lambda config: "Package name {project_name}: ".format(project_name=re.sub(r"\W+", '_', config.get("project_name").lower()) or "(PEP 8)"),
                         default=lambda config: re.sub(r"\W+", '_', config.get("project_name").lower()) or None,
                         required=True, matcher=valid_package_name.match)),

        ("version", dict(prompt="Version (PEP 386): ", required=True,
                         matcher=valid_version_re.match)),

        ("author", dict(prompt="Author name: ")),

        ("email", dict(prompt="Email: ", matcher=valid_email_re.match)),

        ("use_controller", dict(prompt="Use controllers backed by a templating engine? [Y/n] ",
                                type=bool, default=True)),

        ("use_rest_controller", dict(prompt="Use RESTful controllers? [y/N] ", type=bool,
                                     default=False)),

        ("use_jinja2", dict(prompt="Use Jinja2 templating engine? [Y/n] ", type=bool, default=True,
                            required="use_controller")),

        ("use_webassets", dict(prompt="Use webassets asset management framework? [Y/n] ", type=bool,
                               default=True, required="use_controller")),

        ("use_redis", dict(prompt="Use redis session? [y/N] ", type=bool, default=False)),

        ("use_sqlalchemy", dict(prompt="Use SQLAlchemy ORM? [Y/n] ", type=bool, default=True)),

        ("sqlalchemy_url", dict(prompt="SQLAlchemy database connection URL (sqlite://): ",
                                default="sqlite://",
                                required="use_sqlalchemy"))
    )

    for k, v in questions:
        config[k(config) if callable(k) else k] = get_answer(config=config, **v)

    create_project(config, dry_run=kwargs.get("dry_run"))

    footer = textwrap.dedent("""
    ===========================================================================
    Your project skeleton has been created under {path}.


    Subsystems chosen
    -----------------

    Routes (RESTful controllers): {use_rest_controller}
    Jinja2: {use_jinja2}
    webassets: {use_webassets}
    redis: {use_redis}
    SQLAlchemy: {use_sqlalchemy}


    You can now install your package for development with:

      $ pip install -e .

    You can also install all of the optional C-extension speedups with:

      $ pip install blueberrypy[speedups]

    You should also install the appropriate database driver if you have chosen
    to use SQLAlchemy.


    Note
    ----
    Recent version of `pip` disallows the installation of external and
    unverified packages by default. You can install `cdecimal` with:

      $ pip install --allow-external cdecimal


    For more information, the BlueberryPy documentation is available at
    http://blueberrypy.readthedocs.org.

    Happy coding!
    ===========================================================================
    """.format(**config))

    logger.info(footer)


def bundle(**kwargs):
    """
    Webassets bundle management.

    usage: blueberrypy bundle [options]

    Before you can use this command to bundle up your Web assets, you should
    have created either a project skeleton using the 'create' command or
    provided a configuration directory using the global option -c --config_dir.

    options:
      -h, --help                                show this help message and exit
      -C ENV_VAR_NAME, --env-var ENV_VAR_NAME   add the given config from
                                                environment variable name
                                                [default: BLUEBERRYPY_CONFIG]
      -b, --build                               build the asset bundles
      -w, --watch                               automatically rebuild the
                                                asset bundles upon changes in
                                                the static directory
      -c, --clean                               delete the generated asset bundles

    """

    config = BlueberryPyConfiguration(config_dir=kwargs.get('config_dir'),
                                      env_var_name=kwargs.get('env_var'))

    assets_env = config.webassets_env
    if not assets_env:
        raise BlueberryPyNotConfiguredError("Webassets configuration not found.")

    from webassets.script import CommandLineEnvironment
    assets_cli = CommandLineEnvironment(assets_env, logger)

    if kwargs.get("build"):
        try:
            assets_cli.build()
        except AttributeError:
            assets_cli.rebuild()
    elif kwargs.get("watch"):
        assets_cli.watch()
    elif kwargs.get("clean"):
        assets_cli.clean()


def serve(**kwargs):
    """
    Spawn a new running Cherrypy process

    usage: blubeberry serve [options]

    options:
      -h, --help                                 show this help message and exit
      -b BINDING, --bind BINDING                 the address and port to bind to.
                                                 [default: 127.0.0.1:8080]
      -e ENVIRONMENT, --environment ENVIRONMENT  apply the given config environment
      -C ENV_VAR_NAME, --env-var ENV_VAR_NAME    add the given config from environment variable name
                                                 [default: BLUEBERRYPY_CONFIG]
      -f                                         start a fastcgi server instead of the default HTTP
                                                 server
      -s                                         start a scgi server instead of the default HTTP
                                                 server
      -d, --daemonize                            run the server as a daemon. [default: False]
      -p, --drop-privilege                       drop privilege to separately specified umask, uid
                                                 and gid. [default: False]
      -P PIDFILE, --pidfile PIDFILE              store the process id in the given file
      -u UID, --uid UID                          setuid to uid [default: www]
      -g GID, --gid GID                          setgid to gid [default: www]
      -m UMASK, --umask UMASK                    set umask [default: 022]

    """

    config = BlueberryPyConfiguration(config_dir=kwargs.get('config_dir'),
                                      env_var_name=kwargs.get('env_var'))

    cpengine = cherrypy.engine

    cpenviron = kwargs.get("environment")
    if cpenviron:
        config = BlueberryPyConfiguration(config_dir=kwargs.get('config_dir'),
                                          env_var_name=kwargs.get('env_var'),
                                          environment=cpenviron)
        cherrypy.config.update({"environment": cpenviron})

    if config.use_email and config.email_config:
        from blueberrypy import email
        email.configure(config.email_config)

    if config.use_logging and config.logging_config:
        from blueberrypy.plugins import LoggingPlugin
        cpengine.logging = LoggingPlugin(cpengine, config=config.logging_config)

    if config.use_redis:
        from blueberrypy.session import RedisSession
        cherrypy.lib.sessions.RedisSession = RedisSession

    if config.use_sqlalchemy:
        from blueberrypy.plugins import SQLAlchemyPlugin
        cpengine.sqlalchemy = SQLAlchemyPlugin(cpengine,
                                               config=config.sqlalchemy_config)
        from blueberrypy.tools import SQLAlchemySessionTool
        cherrypy.tools.orm_session = SQLAlchemySessionTool()

    if config.use_jinja2:
        if config.webassets_env:
            configure_jinja2(assets_env=config.webassets_env,
                             **config.jinja2_config)
        else:
            configure_jinja2(**config.jinja2_config)

    # update global config first, so subsequent command line options can
    # override the settings in the config files
    cherrypy.config.update(config.app_config)

    if kwargs.get("bind"):
        address, port = kwargs.get("bind").strip().split(":")
        cherrypy.server.socket_host = address
        cherrypy.server.socket_port = int(port)

    if kwargs.get("daemonize"):
        cherrypy.config.update({'log.screen': False})
        Daemonizer(cpengine).subscribe()

    if kwargs.get("drop_privilege"):
        cherrypy.config.update({'engine.autoreload_on': False})
        DropPrivileges(cpengine, umask=int(kwargs.get("umask")),
                       uid=kwargs.get("uid") or "www",
                       gid=kwargs.get("gid") or "www").subscribe()

    if kwargs.get("pidfile"):
        PIDFile(cpengine, kwargs.get("pidfile")).subscribe()

    fastcgi, scgi = kwargs.get("fastcgi"), kwargs.get("scgi")
    if fastcgi and scgi:
        cherrypy.log.error("You may only specify one of the fastcgi and "
                           "scgi options.", 'ENGINE')
        sys.exit(1)
    elif fastcgi or scgi:
        # Turn off autoreload when using *cgi.
        cherrypy.config.update({'engine.autoreload_on': False})
        # Turn off the default HTTP server (which is subscribed by default).
        cherrypy.server.unsubscribe()

        addr = cherrypy.server.bind_addr
        if fastcgi:
            f = servers.FlupFCGIServer(application=cherrypy.tree,
                                       bindAddress=addr)
        elif scgi:
            f = servers.FlupSCGIServer(application=cherrypy.tree,
                                       bindAddress=addr)
        s = servers.ServerPlugin(cpengine, httpserver=f, bind_addr=addr)
        s.subscribe()

    if hasattr(cpengine, 'signal_handler'):
        cpengine.signal_handler.subscribe()

    # for win32 only
    if hasattr(cpengine, "console_control_handler"):
        cpengine.console_control_handler.subscribe()

    # mount the controllers
    for script_name, section in config.controllers_config.viewitems():
        section = section.copy()
        controller = section.pop("controller")
        if isinstance(controller, cherrypy.dispatch.RoutesDispatcher):
            routes_config = {'/': {"request.dispatch": controller}}
            for path in section.viewkeys():
                if path.strip() == '/':
                    routes_config['/'].update(section['/'])
                else:
                    routes_config[path] = section[path].copy()
            app_config = config.app_config.copy()
            app_config.pop("controllers")
            routes_config.update(app_config)
            cherrypy.tree.mount(None, script_name=script_name,
                                config=routes_config)
        else:
            app_config = config.app_config.copy()
            app_config.pop("controllers")
            controller_config = section.copy()
            controller_config.update(app_config)
            cherrypy.tree.mount(controller(), script_name=script_name,
                                config=controller_config)

    # Add the blueberrypy config files into CP's autoreload monitor
    # Jinja2 templates are monitored by Jinja2 itself and will autoreload if
    # needed
    if config.config_file_paths:
        for path in config.config_file_paths:
            cpengine.autoreload.files.add(path)

    try:
        cpengine.start()
    except:
        sys.exit(1)
    else:
        cpengine.block()


def console(**kwargs):
    """
    An REPL fully configured for experimentation.

    usage:
        blueberrypy console [options]

    options:
        -e ENVIRONMENT, --environment=ENVIRONMENT  apply the given config environment
        -C ENV_VAR_NAME, --env-var ENV_VAR_NAME    add the given config from environment variable name
                                                   [default: BLUEBERRYPY_CONFIG]
        --ipython                                  use IPython shell instead of Python one
        -h, --help                                 show this help message and exit

    """

    banner = """
*****************************************************************************
* If the configuration file you specified contains a [sqlalchemy_engine*]   *
* section, a default SQLAlchemy engine and session should have been created *
* for you automatically already.                                            *
*****************************************************************************
"""
    environment = kwargs.get("environment")
    config_dir = kwargs.get("config_dir")
    environment and cherrypy.config.update({"environment": environment})
    configuration = BlueberryPyConfiguration(
        config_dir=config_dir,
        environment=environment,
        env_var_name=kwargs.get('env_var'),
    )
    use_ipython = kwargs.get("ipython", False)
    package_name = shell.get_package_name(configuration)

    if use_ipython:
        try:
            app_package = import_module(package_name)
        except ImportError as e:
            print(e)
            app_package = None
        repl = TerminalInteractiveShell(
            user_ns=shell.get_user_namespace(configuration),
            user_module=app_package,
            display_completions='multicolumn',  # oldstyle is 'readlinelike'
            mouse_support=True,
            space_for_menu=10,  # reserve N lines for the completion menu
        )
        repl.show_banner(banner)
        repl.mainloop()
    else:
        try:
            import readline
        except ImportError as e:
            print(e)
        else:
            import rlcompleter
        sys.ps1 = "[%s]>>> " % package_name
        sys.ps2 = "[%s]... " % package_name

        ns = shell.get_user_namespace(configuration, include_pkg=True)
        repl = InteractiveConsole(locals=ns)
        repl.prompt = package_name
        repl.interact(banner)


def main():
    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    BlueberryPy lightweight pluggable Web application framework command line interface
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    usage: blueberrypy [options] [COMMAND ARGS...]

    options:
        -h, --help                    show this help message and exit
        --version                     print version information and exit
        -C <dir>, --config-dir=<dir>  path to the configuration directory


    The list of possible commands are:
        help     print this help or a command's if an argument is given
        create   create a project skeleton
        console  blueberrypy REPL for experimentations
        bundle   bundles up web assets (type 'blueberrypy help bundle' for details)
        serve    spawn a new CherryPy server process


    See 'blueberrypy help COMMAND' for more information on a specific command.

    """

    args = docopt(textwrap.dedent(main.__doc__), options_first=True)
    config_dir = args["--config-dir"]
    command = args["COMMAND"]
    command_args = args["ARGS"]

    if args["--version"]:
        logger.info("BlueberryPy version %s" % blueberrypy.__version__)
        sys.exit(0)

    def get_command_parser_and_callback(command):
        doc, callback = None, None
        if command == "create":
            doc, callback = create.__doc__, create
        elif command == "console":
            doc, callback = console.__doc__, console
        elif command == "bundle":
            doc, callback = bundle.__doc__, bundle
        elif command == "serve":
            doc, callback = serve.__doc__, serve
        elif command == "help":
            if command_args and command_args[0] in ["create", "console", "bundle", "serve"]:
                callback = globals()[command_args[0]]
                doc = callback.__doc__
            else:
                doc = main.__doc__
            logger.info(textwrap.dedent(doc))
            sys.exit(0)
        else:
            logger.info(textwrap.dedent(main.__doc__))
            sys.exit(0)

        return partial(docopt, textwrap.dedent(doc)), callback

    subparser, func = get_command_parser_and_callback(command)

    def docopt_parse_results_to_kwargs(dct):
        return dict([(k.replace("--", "").replace("-", "_"), v) for k, v in dct.viewitems()])

    func(config_dir=config_dir, **docopt_parse_results_to_kwargs(
        subparser(argv=[command] + command_args)))
