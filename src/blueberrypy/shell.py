import atexit
import importlib

from blueberrypy.config import BlueberryPyConfiguration


def get_user_namespace(config, include_pkg=False):
    if not isinstance(config, BlueberryPyConfiguration):
        raise TypeError(
            'Expected config to be {expected_type}, '
            'but got {actual_type}'
            .format(
                expected_type=BlueberryPyConfiguration,
                actual_type=type(config),
            )
        )

    ns = {'__name__': 'blueberrypy-shell'}

    pkg_name = get_package_name(config)

    if include_pkg:
        app_module = importlib.import_module(pkg_name)
        if hasattr(app_module, '__all__'):
            for name in app_module.__all__:
                ns[name] = getattr(app_module, name)
        else:
            for name, obj in vars(app_module).viewitems():
                if not name.startswith("_"):
                    ns[name] = obj

    ns['cherrypy'] = importlib.import_module("cherrypy")
    ns['blueberrypy'] = importlib.import_module("blueberrypy")

    if config.use_sqlalchemy:
        from sqlalchemy.orm.session import sessionmaker
        engine = _make_sa_engine(config)
        if isinstance(engine, dict):
            Session = sessionmaker(twophase=True)
            Session.configure(binds=engine)
        else:
            Session = sessionmaker()
            Session.configure(bind=engine)
        model = importlib.import_module(pkg_name + ".model")
        model.metadata.bind = engine
        ns['session'] = session = Session()
        session.bind.echo = True
        atexit.register(session.close)

    return ns


def get_package_name(config):
    return (
        config.project_metadata["package"]
        if config.project_metadata else None
    )


def _make_sa_engine(config):
    from sqlalchemy.engine import engine_from_config
    sa_prefix = 'sqlalchemy_engine'
    sa_config = config.sqlalchemy_config

    if sa_prefix in sa_config:
        section = sa_config[sa_prefix]
        return engine_from_config(section, '')
    else:
        engine_bindings = {}
        for section_name, section in sa_config.viewitems():
            if section_name.startswith(sa_prefix):
                model_definition = section_name[len(sa_prefix) + 1:]
                pkg_name, obj_name = model_definition.rsplit('.', 1)
                package = __import__(pkg_name, globals(), locals(), [obj_name])
                model = getattr(package, obj_name)
                engine_bindings[model] = engine_from_config(section)
        return engine_bindings

