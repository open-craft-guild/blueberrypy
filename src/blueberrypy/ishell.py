import importlib
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from sqlalchemy.orm.session import sessionmaker


class IShell(TerminalInteractiveShell):

    def __init__(self, blueberrypy_config=None):
        self._bbp_config = blueberrypy_config

        try:
            app_mod = importlib.import_module(self.get_package_name())
        except:
            app_mod = None

        super(IShell, self).__init__(
            user_ns=self.get_user_namespace(),
            user_module=app_mod,
            display_completions='multicolumn',  # oldstyle is 'readlinelike'
            mouse_support=True,
            space_for_menu=10,  # reserve N lines for the completion menu
        )

    def make_sqlalchemy_engine(self, prefix="sqlalchemy_engine"):

        config = self._bbp_config.sqlalchemy_config

        if prefix in config:
            section = config[prefix]
            from sqlalchemy.engine import engine_from_config
            return engine_from_config(section, '')
        else:
            engine_bindings = {}
            for section_name, section in config.viewitems():
                if section_name.startswith(prefix):
                    model_fqn = section_name[len(prefix) + 1:]
                    model_fqn_parts = model_fqn.rsplit('.', 1)
                    model_mod = __import__(model_fqn_parts[0], globals(), locals(), [model_fqn_parts[1]])
                    model = getattr(model_mod, model_fqn_parts[1])
                    engine_bindings[model] = engine_from_config(section)
            return engine_bindings


    def get_package_name(self):
        config = self._bbp_config
        return config.project_metadata and config.project_metadata["package"]

    def get_user_namespace(self):
        ns = {'__name__': 'blueberrypy-ishell'}
        config = self._bbp_config
        if config.use_sqlalchemy:
            engine = self.make_sqlalchemy_engine()
            if isinstance(engine, dict):
                Session = sessionmaker(twophase=True)
                Session.configure(binds=engine)
            else:
                Session = sessionmaker()
                Session.configure(bind=engine)
            model = importlib.import_module(self.get_package_name() + ".model")

            metadata = model.metadata
            metadata.bind = engine

            ns['session'] = session = Session()
            session.bind.echo = True
        return ns
