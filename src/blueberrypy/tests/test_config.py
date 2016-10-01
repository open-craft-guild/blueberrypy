import __builtin__ as builtins
import textwrap
import unittest
import warnings

from functools import partial
from StringIO import StringIO
try:
    from unittest import mock
except ImportError:
    # fallback for old python
    import mock

from jinja2.loaders import DictLoader
from webassets import Environment

from blueberrypy.config import BlueberryPyConfiguration
from blueberrypy.exc import BlueberryPyConfigurationError, BlueberryPyNotConfiguredError


# dummy controllers
import cherrypy


class Root(object):

    def index(self):
        return "hello world!"
    index.exposed = True


class DummyRestController(object):

    def dummy(self, **kwargs):
        return "hello world!"

rest_controller = cherrypy.dispatch.RoutesDispatcher()
rest_controller.connect("dummy", "/dummy", DummyRestController, action="dummy")


def get_dummy_exists(paths):
    from os.path import exists as real_exists
    def proxied_exists(path):
        if path in paths:
            return True
        return real_exists(path)
    return proxied_exists


def get_dummy_open(config):
    class FakeFile(StringIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type=None, exc_value=None, traceback=None):
            return False
    real_open = builtins.open
    def proxied_open(filename, mode='r', buffering=1):
        if filename in config:
            return FakeFile(*config[filename])
        return real_open(filename, mode, buffering)
    return proxied_open


class BlueberryPyConfigurationTest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        self.assertRaisesRegex = getattr(self, "assertRaisesRegex",
                                         # Fallback to Python < 3.2 name:
                                         getattr(self, "assertRaisesRegexp"))
        self.assertRaisesUserWarningRegex = partial(self.assertRaisesRegex,
                                                    UserWarning)
        self.assertRaisesUserWarningRegex.__doc__ = (self.assertRaisesRegex.
                                                     __doc__)
        super(BlueberryPyConfigurationTest, self).__init__(*args, **kwargs)

    def setUp(self):
        self.basic_valid_app_config = {"controllers": {'': {"controller": Root},
                                                       "/api": {"controller": rest_controller,
                                                                '/': {"request.dispatch": rest_controller}}}}

    def test_validate(self):
        with self.assertRaisesRegexp(
            BlueberryPyNotConfiguredError,
            "BlueberryPy application configuration not found."):
                BlueberryPyConfiguration()

    @mock.patch('os.path.exists', get_dummy_exists([
        '/tmp/dev/app.yml', '/tmp/dev/bundles.yml', '/tmp/dev/logging.yml',
    ]))
    @mock.patch('builtins.open', get_dummy_open({
        '/tmp/dev/app.yml': [
            textwrap.dedent("""
            controllers: []
            """),
        ],
        '/tmp/dev/bundles.yml': [
            textwrap.dedent("""
            directory: /tmp
            url: /
            """),
        ],
        '/tmp/dev/logging.yml': [],
    }))
    @mock.patch(
        'blueberrypy.config.BlueberryPyConfiguration.validate', 
        lambda self: None,
    )
    def test_config_file_paths(self):
        config = BlueberryPyConfiguration(config_dir="/tmp")
        config_file_paths = config.config_file_paths
        self.assertEqual(len(config_file_paths), 3)
        self.assertEqual(config_file_paths[0], "/tmp/dev/app.yml")
        self.assertEqual(config_file_paths[1], "/tmp/dev/bundles.yml")
        self.assertEqual(config_file_paths[2], "/tmp/dev/logging.yml")

    def test_use_email(self):
        app_config = self.basic_valid_app_config.copy()
        app_config.update({"email": {}})

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("error")
            with self.assertRaisesUserWarningRegex(
                "BlueberryPy email configuration is empty."):
                    BlueberryPyConfiguration(app_config=app_config)

        app_config.update({"email": {"debug": 1}})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("error")
            with self.assertRaisesUserWarningRegex(
                "Unknown key 'debug' found for \[email\]. "
                "Did you mean 'debuglevel'?"):
                    BlueberryPyConfiguration(app_config=app_config)

        app_config.update({"email": {"host": "localhost",
                                     "port": 1025}})
        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertTrue(config.use_email)

    def test_use_redis(self):
        app_config = self.basic_valid_app_config.copy()
        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertFalse(config.use_redis)

        app_config["controllers"][''].update({"/": {"tools.sessions.storage_type": "redis"}})

        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertTrue(config.use_redis)

    def test_use_sqlalchemy(self):
        app_config = self.basic_valid_app_config.copy()
        app_config.update({"global": {"engine.sqlalchemy.on": True}})

        self.assertRaisesRegexp(BlueberryPyNotConfiguredError,
                                "SQLAlchemy configuration not found.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config)

        app_config.update({"global": {"engine.sqlalchemy.on": True},
                           "sqlalchemy_engine": {"url": "sqlite://"}})

        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertTrue(config.use_sqlalchemy)

        app_config.update({"global": {"engine.sqlalchemy.on": True},
                           "sqlalchemy_engine_Model": {"url": "sqlite://"}})

        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertTrue(config.use_sqlalchemy)

    def test_use_jinja2(self):
        app_config = self.basic_valid_app_config.copy()
        app_config.update({"jinja2": {}})
        self.assertRaisesRegexp(BlueberryPyNotConfiguredError,
                                "Jinja2 configuration not found.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config)

        app_config.update({"jinja2": {"loader": DictLoader({})}})
        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertTrue(config.use_jinja2)

    def test_use_webassets(self):
        app_config = self.basic_valid_app_config.copy()
        app_config.update({"jinja2": {"use_webassets": True,
                                      "loader": DictLoader({})}})
        self.assertRaisesRegexp(BlueberryPyNotConfiguredError,
                                "Webassets configuration not found.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config)

        webassets_env = Environment("/tmp", "/")
        self.assertRaisesRegexp(BlueberryPyNotConfiguredError,
                                "No bundles found in webassets env.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config,
                                webassets_env=webassets_env)

        webassets_env = Environment("/tmp", "/")
        webassets_env.register("js", "dummy.js", "dummy2.js", output="dummy.js")
        config = BlueberryPyConfiguration(app_config=app_config,
                                          webassets_env=webassets_env)
        self.assertTrue(config.use_webassets)

    def test_jinja2_config(self):
        app_config = self.basic_valid_app_config.copy()
        dict_loader = DictLoader({})
        app_config.update({"jinja2": {"loader": dict_loader,
                                      "use_webassets": True}})

        webassets_env = Environment("/tmp", "/")
        webassets_env.register("js", "dummy.js", "dummy2.js", output="dummy.js")
        config = BlueberryPyConfiguration(app_config=app_config,
                                          webassets_env=webassets_env)
        self.assertEqual(config.jinja2_config, {"loader": dict_loader})

    def test_sqlalchemy_config(self):
        app_config = self.basic_valid_app_config.copy()
        app_config.update({"global": {"engine.sqlalchemy.on": True},
                           "sqlalchemy_engine": {"url": "sqlite://"}})

        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertEqual(config.sqlalchemy_config, {"sqlalchemy_engine": {"url": "sqlite://"}})

        app_config = self.basic_valid_app_config.copy()
        app_config.update({"global": {"engine.sqlalchemy.on": True},
                           "sqlalchemy_engine_Model1": {"url": "sqlite://"},
                           "sqlalchemy_engine_Model2": {"url": "sqlite://"}})

        config = BlueberryPyConfiguration(app_config=app_config)
        self.assertEqual(config.sqlalchemy_config, {"sqlalchemy_engine_Model1": {"url": "sqlite://"},
                                                    "sqlalchemy_engine_Model2": {"url": "sqlite://"}})

    def test_controllers_config(self):
        app_config = {"global": {}}
        self.assertRaisesRegexp(BlueberryPyConfigurationError,
                                "You must declare at least one controller\.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config)

        app_config = {"controllers": {}}
        self.assertRaisesRegexp(BlueberryPyConfigurationError,
                                "You must declare at least one controller\.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config)

        app_config = {"controllers": {'api': {'tools.json_in.on': True}}}
        self.assertRaisesRegexp(BlueberryPyConfigurationError,
                                "You must define a controller in the \[controllers\]\[api\] section\.",
                                callable_obj=BlueberryPyConfiguration,
                                app_config=app_config)

        class Root(object):
            def index(self):
                return "hello world!"

        app_config = {"controllers": {"": {"controller": Root}}}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("error")
            with self.assertRaisesUserWarningRegex(
                "Controller '' has no exposed method\."):
                    BlueberryPyConfiguration(app_config=app_config)

        class Root(object):
            def index(self):
                return "hello world!"
            index.exposed = True

        app_config = {"controllers": {"": {"controller": Root}}}
        config = BlueberryPyConfiguration(app_config=app_config)

        rest_controller = cherrypy.dispatch.RoutesDispatcher()

        app_config = {"controllers": {"/api": {"controller": rest_controller}}}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("error")
            with self.assertRaisesUserWarningRegex(
                "Controller '/api' has no connected routes\."):
                    BlueberryPyConfiguration(app_config=app_config)

        class DummyRestController(object):
            def dummy(self, **kwargs):
                return "hello world!"

        rest_controller.connect("dummy", "/dummy", DummyRestController, action="dummy")
        app_config = {"controllers": {"/api": {"controller": rest_controller}}}
        config = BlueberryPyConfiguration(app_config=app_config)

    @mock.patch('os.path.exists', get_dummy_exists([
        '/tmp/dev/app.yml', '/tmp/dev/bundles.yml', '/tmp/dev/logging.yml',
        '/tmp/dev/app.override.yml',
    ]))
    @mock.patch('builtins.open', get_dummy_open({
        '/tmp/dev/app.yml': [
            textwrap.dedent("""
            controllers: []
            value1: value1
            value2: value2
            """),
        ],
        '/tmp/dev/app.override.yml': [
            textwrap.dedent("""
            value1: new value1
            """),
        ],
        '/tmp/dev/bundles.yml': [],
        '/tmp/dev/logging.yml': [],
    }))
    @mock.patch(
        'blueberrypy.config.BlueberryPyConfiguration.validate', 
        lambda self: None,
    )
    def test_config_overrides_file(self):
        config = BlueberryPyConfiguration(config_dir="/tmp")
        self.assertEqual('new value1', config.app_config['value1'])
        self.assertEqual('value2', config.app_config['value2'])
