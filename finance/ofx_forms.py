from pathlib import Path

from django import forms


MAX_OFX_FILE_SIZE = 10 * 1024 * 1024


class OfxPreviewForm(forms.Form):
    file = forms.FileField(
        label="Arquivo OFX",
        help_text="Selecione um arquivo .ofx ou .qfx de até 10 MB.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".ofx,.qfx",
            }
        ),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]

        extension = Path(uploaded_file.name).suffix.lower()

        if extension not in {".ofx", ".qfx"}:
            raise forms.ValidationError(
                "Selecione um arquivo com extensão .ofx ou .qfx."
            )

        if uploaded_file.size > MAX_OFX_FILE_SIZE:
            raise forms.ValidationError(
                "O arquivo excede o limite de 10 MB."
            )

        header = uploaded_file.read(4096)
        uploaded_file.seek(0)

        header_text = header.decode(
            "ascii",
            errors="ignore",
        ).upper()

        if "OFX" not in header_text:
            raise forms.ValidationError(
                "O conteúdo não parece ser um arquivo OFX válido."
            )

        return uploaded_file
