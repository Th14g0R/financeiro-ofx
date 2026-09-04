from pathlib import Path

from django import forms

from finance.models import Account


MAX_STATEMENT_FILE_SIZE = 20 * 1024 * 1024


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean

        if not data:
            if self.required:
                return single_file_clean(data, initial)
            return []

        if isinstance(data, (list, tuple)):
            return [
                single_file_clean(item, initial)
                for item in data
            ]

        return [single_file_clean(data, initial)]


def validate_statement_files(files):
    allowed_extensions = {
        ".ofx",
        ".qfx",
        ".pdf",
        ".csv",
    }

    for uploaded_file in files:
        extension = Path(
            uploaded_file.name
        ).suffix.lower()

        if extension not in allowed_extensions:
            raise forms.ValidationError(
                f'"{uploaded_file.name}" não possui formato suportado. '
                "Use .ofx, .qfx, .pdf ou .csv."
            )

        if uploaded_file.size > MAX_STATEMENT_FILE_SIZE:
            raise forms.ValidationError(
                f'"{uploaded_file.name}" excede 20 MB.'
            )

        header = uploaded_file.read(4096)
        uploaded_file.seek(0)

        if extension in {".ofx", ".qfx"}:
            header_text = header.decode(
                "ascii",
                errors="ignore",
            ).upper()

            if "OFX" not in header_text:
                raise forms.ValidationError(
                    f'"{uploaded_file.name}" não parece conter OFX válido.'
                )

        elif extension == ".pdf":
            if not header.startswith(b"%PDF-"):
                raise forms.ValidationError(
                    f'"{uploaded_file.name}" não parece ser um PDF válido.'
                )

        elif extension == ".csv":
            if not header.strip():
                raise forms.ValidationError(
                    f'"{uploaded_file.name}" está vazio.'
                )

    return files


class MultipleOfxUploadForm(forms.Form):
    files = MultipleFileField(
        label="Arquivos de extrato",
        help_text=(
            "Selecione OFX/QFX. Também são aceitos PDF de extrato "
            "Mercado Pago e CSV de relatório Mercado Pago. "
            "Limite: 20 MB por arquivo."
        ),
        widget=MultipleFileInput(
            attrs={
                "class": "form-control",
                "accept": ".ofx,.qfx,.pdf,.csv",
            }
        ),
    )

    def clean_files(self):
        return validate_statement_files(
            self.cleaned_data["files"]
        )


class ImportReprocessForm(forms.Form):
    files = MultipleFileField(
        label="Substituir por novos arquivos",
        required=False,
        help_text=(
            "Opcional. Se não selecionar arquivos, o lote será "
            "reprocessado usando os arquivos já armazenados. "
            "Se selecionar, eles substituirão os arquivos atuais."
        ),
        widget=MultipleFileInput(
            attrs={
                "class": "form-control",
                "accept": ".ofx,.qfx,.pdf,.csv",
            }
        ),
    )
    confirm_reprocess = forms.BooleanField(
        label=(
            "Confirmo que quero desfazer os efeitos atuais deste lote "
            "e processá-lo novamente."
        ),
        required=True,
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )

    def clean_files(self):
        return validate_statement_files(
            self.cleaned_data.get("files", [])
        )


class StatementAccountForm(forms.Form):
    account = forms.ModelChoiceField(
        label="Conta",
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = (
            Account.objects.select_related("bank")
            .filter(is_active=True)
            .order_by("bank__name", "nickname")
        )


class CreateAccountFromOfxForm(forms.Form):
    bank_name = forms.CharField(
        label="Nome do banco",
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )
    bank_code = forms.CharField(
        label="Código COMPE",
        max_length=3,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "3",
            }
        ),
    )
    bank_ofx_id = forms.CharField(
        label="BANKID do OFX",
        max_length=32,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )
    nickname = forms.CharField(
        label="Apelido da conta",
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )
    branch = forms.CharField(
        label="Agência",
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )
    number = forms.CharField(
        label="Conta",
        max_length=40,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )
    account_type = forms.ChoiceField(
        label="Tipo",
        choices=Account.AccountType.choices,
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )
    currency = forms.CharField(
        label="Moeda",
        max_length=3,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "3",
            }
        ),
    )
    commit_after_create = forms.BooleanField(
        label=(
            "Depois de cadastrar e vincular, gravar automaticamente "
            "as movimentações se não houver outra pendência."
        ),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )

    def clean_bank_code(self):
        value = self.cleaned_data["bank_code"].strip()

        if value and not value.isdigit():
            raise forms.ValidationError(
                "O código COMPE deve conter somente números."
            )

        return value.zfill(3) if value else ""

    def clean_currency(self):
        value = self.cleaned_data["currency"].strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise forms.ValidationError(
                "Informe uma moeda de 3 letras, como BRL."
            )

        return value
