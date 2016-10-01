import collections
import difflib
import inspect
import logging
import os.path
import warnings
import os
import importlib

import cherrypy

from yaml import load
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

json = None
for pkg in ['ujson', 'yajl', 'simplejson', 'cjson', 'json']:
    try:
        json = importlib.import_module(pkg)
    except:
        pass
    else:
        break

from blueberrypy.email import Mailer
from blueberrypy.exc import (BlueberryPyNotConfiguredError,
                             BlueberryPyConfigurationError)


logger = logging.getLogger(__name__)


class BlueberryPyConfiguration(object):

    def __init__(self, config_dir=None, app_config=None, logging_config=None,
                 webassets_env=None, environment=None,
                 env_var_name='BLUEBERRYPY_CONFIG'):
        """Loads BlueberryPy configuration from `config_dir` if supplied.

        If `app_config` or `logging_config` or `webassets_env` are given, they
        will be used instead of the configuration files found from `config_dir`.

        If `environment` is given, it must be an existing CherryPy environment.
        If `environment` is `production`, and `config_dir` is given, the `prod`
        subdirectory will be searched for configuration files, otherwise the
        `dev` subdirectory` will be searched.

        If `env_var_name` is given, it must be an existing environment
        variable, it will override values from YAML config.

        Upon initialization of this configuration object, all the configuration
        will be validated for sanity and either BlueberryPyConfigurationError or
        BlueberryPyNotConfiguredError will be thrown if insane. For less severe
        configuration insanity cases, a warning will be emitted instead.

        :arg config_dir: a path, str
        :arg app_config: a CherryPy config, dict
        :arg logging_config: a logging config, dict
        :arg webassets_env: a webassets environment, webassets.Environment
        :arg environment: a CherryPy configuration environment, str
        :arg env_var_name: an environment variable name for configuration, str
        """

        ENV_CONFIG = self.__class__._load_env_var(env_var_name)

        CWD = os.getcwdu() if getattr(os, "getcwdu", None) else os.getcwd()

        if ENV_CONFIG.get('global') and ENV_CONFIG['global'].get('CWD') and \
                os.path.isdir(
                    os.path.join(ENV_CONFIG['global']['CWD'], 'src')):
            CWD = ENV_CONFIG['global']['CWD']

        if config_dir is None:
            self.config_dir = config_dir = os.path.join(CWD, "config")
        else:
            self.config_dir = config_dir = os.path.abspath(config_dir)

        if environment == "production":
            self.config_dir = config_dir = os.path.join(config_dir, "prod")
        elif environment == "test_suite" and os.path.exists(os.path.join(config_dir, "test")):
            self.config_dir = config_dir = os.path.join(config_dir, "test")
        else:
            self.config_dir = config_dir = os.path.join(config_dir, "dev")

        config_file_paths = {}
        app_yml_path = os.path.join(config_dir, "app.yml")
        logging_yml_path = os.path.join(config_dir, "logging.yml")
        bundles_yml_path = os.path.join(config_dir, "bundles.yml")

        # A local-only config, which overrides the app.yml values
        app_override_yml_path = os.path.join(config_dir, "app.override.yml")

        if os.path.exists(app_yml_path):
            config_file_paths["app_yml"] = app_yml_path

        if os.path.exists(logging_yml_path):
            config_file_paths["logging_yml"] = logging_yml_path

        if os.path.exists(bundles_yml_path):
            config_file_paths["bundles_yml"] = bundles_yml_path

        if os.path.exists(app_override_yml_path):
            config_file_paths["app_override_yml"] = app_override_yml_path

        self._config_file_paths = config_file_paths

        if "app_yml" in config_file_paths and not app_config:
            with open(config_file_paths["app_yml"]) as app_yml:
                self._app_config = load(app_yml, Loader)

            # If the overrides file exists, override the app config values
            # with ones from app.override.yml
            if "app_override_yml" in config_file_paths:
                app_override_config = {}
                with open(config_file_paths["app_override_yml"]) as app_override_yml:
                    app_override_config = load(app_override_yml, Loader)

                self._app_config = self.__class__.merge_dicts(
                    self._app_config, 
                    app_override_config
                )

        if "logging_yml" in config_file_paths and not logging_config:
            with open(config_file_paths["logging_yml"]) as logging_yml:
                self._logging_config = load(logging_yml, Loader)

        if "bundles_yml" in config_file_paths and not webassets_env:
            from webassets.loaders import YAMLLoader
            self._webassets_env = YAMLLoader(config_file_paths["bundles_yml"]).load_environment()

        if app_config:
            self._app_config = dict(app_config)

        try:
            # Merge JSON from environment variable
            self._app_config = self.__class__.merge_dicts(self._app_config, ENV_CONFIG)
        except AttributeError:
            if ENV_CONFIG:  # not an empty dict
                self._app_config = ENV_CONFIG
            # Don't re-raise exception, self.validate() will do this later

        if logging_config:
            self._logging_config = dict(logging_config)

        if webassets_env is not None:
            self._webassets_env = webassets_env

        self.validate()  # Checks that all attributes are pre-populated

        # Convert relative paths to absolute where needed
        # self.validate() will fail if there's no app_config['controllers']
        for _ in self._app_config['controllers']:
            section = self._app_config['controllers'][_]
            for r in section:
                if isinstance(section[r], dict):
                    for __ in ['tools.staticdir.root',
                               'tools.staticfile.root']:
                        pth = section[r].get(__)
                        if pth is not None and not pth.startswith('/'):
                            self._app_config['controllers'][_][r][__] = \
                                os.path.join(CWD, pth)

        if environment == "backlash":
            self.setup_backlash_environment()

    @property
    def config_file_paths(self):
        if self._config_file_paths:
            sorted_kv_pairs = tuple(((k, self._config_file_paths[k])
                                     for k in sorted(self._config_file_paths.viewkeys())))
            paths = collections.namedtuple("config_file_paths", [e[0] for e in sorted_kv_pairs])
            return paths(*[e[1] for e in sorted_kv_pairs])

    @property
    def project_metadata(self):
        return self.app_config["project_metadata"]

    @property
    def use_logging(self):
        return self.app_config.get("global", {}).get("engine.logging.on", False)

    @property
    def use_redis(self):
        if self.controllers_config:
            for _, controller_config in self.controllers_config.viewitems():
                controller_config = controller_config.copy()
                controller_config.pop("controller")
                for path_config in controller_config.viewvalues():
                    if path_config.get("tools.sessions.storage_type") == "redis":
                        return True
        return False

    @property
    def use_sqlalchemy(self):
        return self.app_config.get("global", {}).get("engine.sqlalchemy.on", False)

    @property
    def use_jinja2(self):
        return "jinja2" in self.app_config

    @property
    def use_webassets(self):
        return self.use_jinja2 and self.app_config["jinja2"].get("use_webassets", False)

    @property
    def use_email(self):
        return "email" in self.app_config

    @property
    def controllers_config(self):
        return self.app_config.get("controllers")

    @property
    def app_config(self):
        return self._app_config

    @property
    def logging_config(self):
        return getattr(self, "_logging_config", None)

    @property
    def webassets_env(self):
        return getattr(self, "_webassets_env", None)

    @property
    def jinja2_config(self):
        if self.use_jinja2:
            conf = self.app_config["jinja2"].copy()
            conf.pop("use_webassets", None)
            return conf

    @property
    def sqlalchemy_config(self):
        if self.use_sqlalchemy:
            if "sqlalchemy_engine" in self.app_config:
                saconf = self.app_config["sqlalchemy_engine"].copy()
                return {"sqlalchemy_engine": saconf}
            else:
                return dict([(k, v) for k, v in self.app_config.viewitems()
                             if k.startswith("sqlalchemy_engine")])

    @property
    def email_config(self):
        return self.app_config.get("email")

    def setup_backlash_environment(self):
        """
        Returns a new copy of this configuration object configured to run under
        the backlash defbugger environment and ensure it is created for
        cherrypy's config object.
        """

        try:
            from backlash import DebuggedApplication
        except ImportError:
            warnings.warn("backlash not installed")
            return

        cherrypy._cpconfig.environments["backlash"] = {
            "log.wsgi": True,
            "request.throw_errors": True,
            "log.screen": False,
            "engine.autoreload_on": False
        }

        def remove_error_options(section):
            section.pop("request.handler_error", None)
            section.pop("request.error_response", None)
            section.pop("tools.err_redirect.on", None)
            section.pop("tools.log_headers.on", None)
            section.pop("tools.log_tracebacks.on", None)

            for k in section.copy().viewkeys():
                if k.startswith("error_page.") or \
                        k.startswith("request.error_page."):
                    section.pop(k)

        for section_name, section in self.app_config.viewitems():
            if section_name.startswith("/") or section_name == "global":
                remove_error_options(section)

        wsgi_pipeline = []
        if "/" in self.app_config:
            wsgi_pipeline = self.app_config["/"].get("wsgi.pipeline", [])
        else:
            self.app_config["/"] = {}

        wsgi_pipeline.insert(0, ("backlash", DebuggedApplication))

        self.app_config["/"]["wsgi.pipeline"] = wsgi_pipeline

    def validate(self):
        # no need to check for cp config, which will be checked on startup

        if not hasattr(self, "_app_config") or not self.app_config:
            raise BlueberryPyNotConfiguredError("BlueberryPy application configuration not found.")

        if self.use_sqlalchemy and not self.sqlalchemy_config:
            raise BlueberryPyNotConfiguredError("SQLAlchemy configuration not found.")

        if self.use_webassets:
            if self.webassets_env is None:
                raise BlueberryPyNotConfiguredError("Webassets configuration not found.")
            elif len(self.webassets_env) == 0:
                raise BlueberryPyNotConfiguredError("No bundles found in webassets env.")

        if self.use_jinja2 and not self.jinja2_config:
            raise BlueberryPyNotConfiguredError("Jinja2 configuration not found.")

        if self.use_logging and not self.logging_config:
            warnings.warn("BlueberryPy application-specific logging "
                          "configuration not found. Continuing without "
                          "BlueberryPy's logging plugin.")

        if self.use_email:
            if not self.email_config:
                warnings.warn("BlueberryPy email configuration is empty.")
            else:
                mailer_ctor_argspec = inspect.getargspec(Mailer.__init__)
                argnames = frozenset(mailer_ctor_argspec.args[1:])
                for key in self.email_config.viewkeys():
                    if key not in argnames:
                        closest_match = difflib.get_close_matches(key, argnames, 1)
                        closest_match = ((closest_match and " Did you mean %r?" % closest_match[0])
                                         or "")
                        warnings.warn(("Unknown key %r found for [email]." % key) + closest_match)

        if not self.controllers_config:
            raise BlueberryPyConfigurationError("You must declare at least one controller.")
        else:
            for script_name, section in self.controllers_config.viewitems():
                controller = section.get("controller")
                if controller is None:
                    raise BlueberryPyConfigurationError("You must define a controller in the "
                                                        "[controllers][%s] section." % script_name)
                elif isinstance(controller, cherrypy.dispatch.RoutesDispatcher):
                    if not controller.controllers:
                        warnings.warn("Controller %r has no connected routes." % script_name)
                else:
                    for member_name, member_obj in inspect.getmembers(controller):
                        if member_name == "exposed" and member_obj:
                            break
                        elif (hasattr(member_obj, "exposed") and
                              member_obj.exposed is True):
                            break
                    else:
                        warnings.warn("Controller %r has no exposed method." % script_name)

    @classmethod
    def _load_env_var(cls, env_var_name):
        env_conf = {}
        try:
            env_conf = json.loads(os.getenv(env_var_name),
                                  object_hook=cls._callable_json_loader)
        except ValueError:
            # Don't use simplejson.JSONDecodeError, since it only exists in
            # simplejson implementation and is a subclass of ValueError
            # See: https://github.com/Yelp/mrjob/issues/544
            logger.error('${} is not a valid JSON string!'
                         .format(env_var_name))
        except TypeError:
            logger.error('${} environment variable is not set!'
                         .format(env_var_name))
        except:
            logger.exception('Could not parse ${} environment variable for an '
                             'unknown reason!'.format(env_var_name))
        return env_conf

    @staticmethod
    def get_callable_from_str(s):
        python_module, python_name = s.rsplit('.', 1)
        return getattr(importlib.import_module(python_module), python_name)

    @classmethod
    def _callable_json_loader(cls, obj):
        if isinstance(obj, str):
            if obj.startswith('!!python/name:'):
                cllbl = cls.get_callable_from_str(obj.split(':', 1)[-1])
                return cllbl if callable(cllbl) else obj

        if isinstance(obj, dict):
            keys = tuple(filter(lambda _: _.startswith('!!python/object:'),
                                obj.keys()))
            for k in keys:
                cllbl = cls.get_callable_from_str(k.split(':', 1)[-1])
                return cllbl(**obj[k]) if callable(cllbl) else obj

        return obj

    @classmethod
    def merge_dicts(cls, base, overrides):
        '''Recursive helper for merging of two dicts'''
        for k in overrides.keys():
            if k in base:
                if isinstance(base[k], dict) and isinstance(overrides[k], dict):
                    base[k] = cls.merge_dicts(base[k], overrides[k])
                elif isinstance(overrides[k], list) and \
                        not isinstance(base[k], list):
                    base[k] = [base[k]] + overrides[k]
                elif isinstance(base[k], list) and \
                        not isinstance(overrides[k], list):
                    base[k] = base[k] + [overrides[k]]
                elif not isinstance(base[k], dict):
                    base[k] = overrides[k]
                else:
                    base[k].update(overrides[k])
            else:
                base[k] = overrides[k]
        return base
