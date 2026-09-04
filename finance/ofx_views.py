from dataclasses import dataclass

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.edit import FormView

from services.ofx import OfxBrParser
from services.ofx import OfxParseError
from services.ofx.account_matcher import OfxAccountMatch
from services.ofx.account_matcher import match_statement
from services.ofx.models import ParsedStatement

from .ofx_forms import OfxPreviewForm


@dataclass(frozen=True, slots=True)
class StatementPreview:
    statement: ParsedStatement
    match: OfxAccountMatch


class OfxPreviewView(LoginRequiredMixin, FormView):
    template_name = "finance/ofx_preview.html"
    form_class = OfxPreviewForm

    def form_valid(self, form):
        uploaded_file = form.cleaned_data["file"]

        parser = OfxBrParser()

        try:
            parsed_file = parser.parse_bytes(
                uploaded_file.read()
            )
        except OfxParseError as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)

        statement_previews = tuple(
            StatementPreview(
                statement=statement,
                match=match_statement(statement),
            )
            for statement in parsed_file.statements
        )

        context = self.get_context_data(
            form=form,
            parsed_file=parsed_file,
            statement_previews=statement_previews,
            uploaded_filename=uploaded_file.name,
        )

        return self.render_to_response(context)
