from starlite.plugins.sqlalchemy.compat import SQLALCHEMY_2_INSTALLED

if not SQLALCHEMY_2_INSTALLED:
    collect_ignore_glob = ["*"]
