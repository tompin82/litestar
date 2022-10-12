from functools import partial
from typing import TYPE_CHECKING, Any, List, Union

from starlite.exceptions import MissingDependencyException, TemplateNotFoundException
from starlite.template.base import TemplateEngineProtocol, TemplateProtocol, url_for

try:
    from mako.exceptions import TemplateLookupException as MakoTemplateNotFound
    from mako.lookup import TemplateLookup

except ImportError as e:
    raise MissingDependencyException("mako is not installed") from e

if TYPE_CHECKING:
    from mako.template import Template as _MakoTemplate
    from pydantic import DirectoryPath


class MakoTemplate(TemplateProtocol):
    template: "_MakoTemplate"

    def __init__(self, template: "_MakoTemplate"):
        super().__init__()
        self.template = template

    def render(self, *args: Any, **kwargs: Any) -> str:
        kwargs["url_for"] = partial(url_for, kwargs)
        return str(self.template.render(*args, **kwargs))


class MakoTemplateEngine(TemplateEngineProtocol[MakoTemplate]):
    def __init__(self, directory: Union["DirectoryPath", List["DirectoryPath"]]) -> None:
        """Mako based TemplateEngine.

        Args:
            directory: Direct path or list of directory paths from which to serve templates.
        """
        super().__init__(directory=directory)
        self.engine = TemplateLookup(directories=directory if isinstance(directory, (list, tuple)) else [directory])

    def get_template(self, template_name: str) -> MakoTemplate:
        """
        Retrieves a template by matching its name (dotted path) with files in the directory or directories provided.
        Args:
            template_name: A dotted path

        Returns:
            MakoTemplate instance

        Raises:
            [TemplateNotFoundException][starlite.exceptions.TemplateNotFoundException]: if no template is found.
        """
        try:
            mako_tpl_object = self.engine.get_template(template_name)
            return MakoTemplate(mako_tpl_object)
        except MakoTemplateNotFound as exc:
            raise TemplateNotFoundException(template_name=template_name) from exc
