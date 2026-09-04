from django import forms
from django.db.models import Q

from .models import Account
from .models import Bank
from .models import Category
from .models import Counterparty
from .models import CounterpartyAlias
from .models import Transaction


class BootstrapModelForm(forms.ModelForm):
    def apply_bootstrap_classes(self):
        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"


class BankForm(BootstrapModelForm):
    class Meta:
        model = Bank
        fields = [
            "name",
            "code",
            "ofx_bank_id",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "Ex.: Nubank"}
            ),
            "code": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: 260",
                    "inputmode": "numeric",
                    "maxlength": "3",
                }
            ),
            "ofx_bank_id": forms.TextInput(
                attrs={"placeholder": "Ex.: 260"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_code(self):
        code = self.cleaned_data["code"].strip()

        if not code:
            return ""

        if not code.isdigit():
            raise forms.ValidationError(
                "Informe somente números no código COMPE."
            )

        return code.zfill(3)

    def clean_ofx_bank_id(self):
        return self.cleaned_data["ofx_bank_id"].strip()


class AccountForm(BootstrapModelForm):
    class Meta:
        model = Account
        fields = [
            "bank",
            "nickname",
            "branch",
            "number",
            "digit",
            "account_type",
            "currency",
            "ofx_account_id",
            "is_own_account",
            "is_active",
        ]
        widgets = {
            "nickname": forms.TextInput(
                attrs={"placeholder": "Ex.: Principal"}
            ),
            "branch": forms.TextInput(
                attrs={"placeholder": "Ex.: 0001"}
            ),
            "number": forms.TextInput(
                attrs={"placeholder": "Número da conta"}
            ),
            "digit": forms.TextInput(
                attrs={"placeholder": "Dígito"}
            ),
            "currency": forms.TextInput(
                attrs={
                    "placeholder": "BRL",
                    "maxlength": "3",
                }
            ),
            "ofx_account_id": forms.TextInput(
                attrs={"placeholder": "ACCTID encontrado no OFX"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_bank_id = getattr(self.instance, "bank_id", None)

        active_banks = Q(is_active=True)
        if current_bank_id:
            active_banks |= Q(pk=current_bank_id)

        self.fields["bank"].queryset = (
            Bank.objects.filter(active_banks)
            .order_by("name")
            .distinct()
        )

        self.apply_bootstrap_classes()

    def clean_nickname(self):
        return " ".join(self.cleaned_data["nickname"].split())

    def clean_branch(self):
        return self.cleaned_data["branch"].strip()

    def clean_number(self):
        return self.cleaned_data["number"].strip()

    def clean_digit(self):
        return self.cleaned_data["digit"].strip()

    def clean_currency(self):
        currency = self.cleaned_data["currency"].strip().upper()

        if len(currency) != 3 or not currency.isalpha():
            raise forms.ValidationError(
                "Informe uma moeda ISO de 3 letras, como BRL."
            )

        return currency

    def clean_ofx_account_id(self):
        return self.cleaned_data["ofx_account_id"].strip()


class TransactionForm(BootstrapModelForm):
    class Meta:
        model = Transaction
        fields = [
            "account",
            "posted_at",
            "competence_date",
            "amount",
            "direction",
            "transaction_type",
            "raw_description",
            "document",
            "reference",
            "counterparty",
            "category",
            "notes",
        ]
        widgets = {
            "posted_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
            "competence_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "amount": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0.01",
                    "placeholder": "0,00",
                }
            ),
            "raw_description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Descrição original do movimento",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Observações opcionais",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_account_id = getattr(self.instance, "account_id", None)
        active_accounts = Q(is_active=True)

        if current_account_id:
            active_accounts |= Q(pk=current_account_id)

        self.fields["account"].queryset = (
            Account.objects.select_related("bank")
            .filter(active_accounts)
            .order_by("bank__name", "nickname")
            .distinct()
        )

        current_category_id = getattr(self.instance, "category_id", None)
        active_categories = Q(is_active=True)

        if current_category_id:
            active_categories |= Q(pk=current_category_id)

        self.fields["category"].queryset = (
            Category.objects.filter(active_categories)
            .order_by("name")
            .distinct()
        )

        current_counterparty_id = getattr(
            self.instance,
            "counterparty_id",
            None,
        )
        active_counterparties = Q(is_active=True)

        if current_counterparty_id:
            active_counterparties |= Q(
                pk=current_counterparty_id
            )

        self.fields["counterparty"].queryset = (
            Counterparty.objects.filter(
                active_counterparties
            )
            .order_by("display_name", "id")
            .distinct()
        )

        self.fields["posted_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]
        self.fields["competence_date"].input_formats = ["%Y-%m-%d"]

        self.apply_bootstrap_classes()



class CounterpartyAliasForm(BootstrapModelForm):
    class Meta:
        model = CounterpartyAlias
        fields = [
            "alias",
            "alias_type",
        ]
        widgets = {
            "alias": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: João Silva, JOAO S, chave/identificador",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()



class CounterpartyMergeSelectionForm(forms.Form):
    counterparties = forms.ModelMultipleChoiceField(
        label="Contrapartes",
        queryset=Counterparty.objects.none(),
        required=True,
    )

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )
        self.fields[
            "counterparties"
        ].queryset = (
            Counterparty.objects.filter(
                is_active=True
            )
            .order_by(
                "display_name",
                "id",
            )
        )

    def clean_counterparties(self):
        counterparties = (
            self.cleaned_data[
                "counterparties"
            ]
        )
        count = counterparties.count()

        if count < 2:
            raise forms.ValidationError(
                (
                    "Selecione pelo menos dois nomes "
                    "para unificar."
                )
            )

        if count > 50:
            raise forms.ValidationError(
                (
                    "Selecione no máximo 50 nomes "
                    "por unificação."
                )
            )

        return counterparties


class CounterpartyMergeConfirmForm(
    CounterpartyMergeSelectionForm
):
    target = forms.ModelChoiceField(
        label="Registro principal",
        queryset=Counterparty.objects.none(),
        required=True,
    )
    final_display_name = forms.CharField(
        label="Nome final",
        max_length=200,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
            }
        ),
    )
    confirm_merge = forms.BooleanField(
        label=(
            "Confirmo que os registros selecionados "
            "representam a mesma pessoa/empresa."
        ),
        required=True,
    )
    confirm_strong_conflicts = forms.BooleanField(
        label=(
            "Mesmo com os conflitos de identidade acima, "
            "confirmo que são a mesma contraparte."
        ),
        required=False,
    )

    def __init__(
        self,
        *args,
        selected_ids=None,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        if selected_ids:
            parsed_ids = []

            for value in selected_ids:
                try:
                    parsed_ids.append(
                        int(value)
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

            selected_ids = parsed_ids

            queryset = (
                Counterparty.objects.filter(
                    is_active=True,
                    pk__in=selected_ids,
                )
                .order_by(
                    "display_name",
                    "id",
                )
            )

            self.fields[
                "counterparties"
            ].queryset = queryset
            self.fields[
                "target"
            ].queryset = queryset

    def clean(self):
        cleaned = super().clean()

        counterparties = cleaned.get(
            "counterparties"
        )
        target = cleaned.get(
            "target"
        )

        if (
            counterparties is not None
            and target is not None
            and not counterparties.filter(
                pk=target.pk
            ).exists()
        ):
            self.add_error(
                "target",
                (
                    "O registro principal precisa "
                    "estar entre os selecionados."
                ),
            )

        return cleaned
