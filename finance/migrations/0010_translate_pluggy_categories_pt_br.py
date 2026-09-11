from django.db import migrations


TRANSLATIONS = {
    "Income": "Receitas",
    "Salary": "Salário",
    "Retirement": "Aposentadoria",
    "Entrepreneurial activities": "Atividades empreendedoras",
    "Government aid": "Benefícios governamentais",
    "Non-recurring income": "Receitas não recorrentes",
    "Loans and Financing": "Empréstimos e financiamentos",
    "Late payment and overdraft costs": "Juros de atraso e cheque especial",
    "Interests charged": "Juros cobrados",
    "Loans": "Empréstimos",
    "Financing": "Financiamentos",
    "Real estate financing": "Financiamento imobiliário",
    "Vehicle Financing": "Financiamento de veículo",
    "Student loan": "Financiamento estudantil",
    "Investments": "Investimentos",
    "Automatic investment": "Investimento automático",
    "Fixed income": "Renda fixa",
    "Mutual funds": "Fundos de investimento",
    "Variable income": "Renda variável",
    "Margin": "Margem",
    "Proceeds interests and dividends": "Rendimentos, juros e dividendos",
    "Pension": "Previdência",
    "Same person transfer": "Transferência entre contas da mesma pessoa",
    "Same person transfer - Cash": "Transferência própria - Dinheiro",
    "Same person transfer - PIX": "Transferência própria - PIX",
    "Same person transfer - TED": "Transferência própria - TED",
    "Transfers": "Transferências",
    "Transfer - Bank slip (Boleto)": "Transferência - Boleto",
    "Transfer - Cash": "Transferência - Dinheiro",
    "Transfer - Check": "Transferência - Cheque",
    "Transfer - DOC": "Transferência - DOC",
    "Transfer - Foreign exchange": "Transferência - Câmbio",
    "Transfer - Internal": "Transferência interna",
    "Transfer - PIX": "Transferência - PIX",
    "Transfer - TED": "Transferência - TED",
    "Credit card payment": "Pagamento de cartão de crédito",
    "Third-party transfers": "Transferências para terceiros",
    "Bank slip": "Boleto",
    "Debt card": "Cartão de débito",
    "Debit card": "Cartão de débito",
    "Legal obligations": "Obrigações legais",
    "Blocked balances": "Valores bloqueados",
    "Alimony": "Pensão alimentícia",
    "Services": "Serviços",
    "Telecommunications": "Telecomunicações",
    "Mobile": "Celular",
    "Education": "Educação",
    "Online Courses": "Cursos on-line",
    "University": "Universidade",
    "School": "Escola",
    "Kindergarten": "Educação infantil",
    "Wellness and fitness": "Bem-estar e atividade física",
    "Gyms and fitness centers": "Academias e centros de treinamento",
    "Sports practice": "Prática esportiva",
    "Wellness": "Bem-estar",
    "Tickets": "Ingressos",
    "Stadiums and arenas": "Estádios e arenas",
    "Landmarks and museums": "Pontos turísticos e museus",
    "Cinema, theater and concerts": "Cinema, teatro e shows",
    "Shopping": "Compras",
    "Online shopping": "Compras on-line",
    "Electronics": "Eletrônicos",
    "Pet supplies and vet": "Produtos pet e veterinário",
    "Clothing": "Vestuário",
    "Kids and toys": "Crianças e brinquedos",
    "Bookstore": "Livraria",
    "Sports goods": "Artigos esportivos",
    "Office Supplies": "Material de escritório",
    "Digital services": "Serviços digitais",
    "Gaming": "Jogos",
    "Video streaming": "Streaming de vídeo",
    "Music streaming": "Streaming de música",
    "Groceries": "Supermercado",
    "Food and drinks": "Alimentação e bebidas",
    "Eating out": "Restaurantes e alimentação fora de casa",
    "Food delivery": "Delivery de comida",
    "Travel": "Viagens",
    "Airport and airlines": "Aeroportos e companhias aéreas",
    "Accommodation": "Hospedagem",
    "Mileage programs": "Programas de milhas",
    "Bus tickets": "Passagens de ônibus",
    "Donations": "Doações",
    "Gambling": "Apostas",
    "Lottery": "Loteria",
    "Online bet": "Apostas on-line",
    "Taxes": "Impostos",
    "Income taxes": "Imposto de renda",
    "Taxes on investments": "Impostos sobre investimentos",
    "Tax on financial operations": "IOF / imposto sobre operações financeiras",
    "Bank fees": "Tarifas bancárias",
    "Account fees": "Tarifas de conta",
    "Wire transfer fees and ATM fees": "Tarifas de transferências e saques",
    "Credit card fees": "Tarifas de cartão de crédito",
    "Housing": "Moradia",
    "Rent": "Aluguel",
    "Houseware": "Artigos para casa",
    "Urban land and building tax": "IPTU",
    "Utilities": "Contas residenciais",
    "Water": "Água",
    "Electricity": "Energia elétrica",
    "Gas": "Gás",
    "Healthcare": "Saúde",
    "Dentist": "Dentista",
    "Pharmacy": "Farmácia",
    "Optometry": "Ótica e optometria",
    "Hospital clinics and labs": "Hospitais, clínicas e laboratórios",
    "Transportation": "Transporte",
    "Taxi and ride-hailing": "Táxi e transporte por aplicativo",
    "Public transportation": "Transporte público",
    "Car rental": "Aluguel de veículos",
    "Bicycle": "Bicicleta",
    "Automotive": "Automotivo",
    "Gas stations": "Combustível / postos",
    "Parking": "Estacionamento",
    "Tolls and in-vehicle payment": "Pedágios e pagamentos veiculares",
    "Vehicle ownership taxes and fees": "Impostos e taxas de veículos",
    "Vehicle maintenance": "Manutenção de veículos",
    "Traffic tickets": "Multas de trânsito",
    "Insurance": "Seguros",
    "Life insurance": "Seguro de vida",
    "Home Insurance": "Seguro residencial",
    "Health insurance": "Plano ou seguro de saúde",
    "Vehicle insurance": "Seguro de veículo",
    "Leisure": "Lazer",
    "Other": "Outros",
}


def translate_categories(apps, schema_editor):
    Category = apps.get_model("finance", "Category")
    Transaction = apps.get_model("finance", "Transaction")

    for english_name, portuguese_name in TRANSLATIONS.items():
        old = Category.objects.filter(name__iexact=english_name).order_by("pk").first()
        if old is None or old.name == portuguese_name:
            continue

        target = (
            Category.objects.filter(name__iexact=portuguese_name)
            .exclude(pk=old.pk)
            .order_by("pk")
            .first()
        )
        if target is None:
            old.name = portuguese_name
            old.save(update_fields=["name", "updated_at"])
            continue

        if target.category_type != old.category_type:
            target.category_type = "BOTH"
        if not target.is_active:
            target.is_active = True
        target.save(update_fields=["category_type", "is_active", "updated_at"])

        Transaction.objects.filter(category_id=old.pk).update(category_id=target.pk)
        old.is_active = False
        old.save(update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0009_transaction_source_category"),
    ]

    operations = [
        migrations.RunPython(translate_categories, migrations.RunPython.noop),
    ]
