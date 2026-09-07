# Financeiro OFX — Etapa 10.7.1


## Etapa 10.7.1 — Correção do teste de bloqueio de login

A Etapa 10.7 alterou corretamente a mensagem exibida quando o rate limit de
login é acionado, passando de uma mensagem genérica de credenciais inválidas
para uma mensagem explícita de bloqueio temporário.

Um teste antigo ainda esperava o texto anterior:

```text
Usuário ou senha inválidos
```

mas a resposta HTTP 429 passou corretamente a renderizar:

```text
Muitas tentativas de acesso
```

O teste foi atualizado para validar o comportamento novo. Não há migration nem
alteração de banco nesta revisão.



## Etapa 10.7 — Recuperação de acesso e e-mail de recuperação

A autenticação foi revisada após um cenário em que uma senha correta podia
continuar sendo recusada.

Foram encontrados dois pontos importantes no fluxo anterior:

1. o username armazenado podia ser `thiago` e o login digitado como `Thiago`;
2. após o limite de falhas, o bloqueio temporário era aplicado, mas o template
   substituía a mensagem específica por `Usuário ou senha inválidos`.

A partir desta etapa:

- o login resolve o username de forma case-insensitive antes de autenticar;
- o rate limiter continua ativo;
- quando houver bloqueio temporário, a tela informa que é necessário aguardar;
- o Gerenciador ganhou `Usuários / recuperação`;
- a tela local permite verificar se uma senha confere com o hash existente;
- é possível redefinir a senha sem PowerShell;
- uma redefinição local limpa os bloqueios temporários para permitir teste
  imediato;
- a conta pode armazenar um e-mail de recuperação;
- o usuário autenticado pode alterar o próprio e-mail em `Minha conta`,
  confirmando a senha atual;
- o login possui `Esqueci minha senha`;
- a redefinição por e-mail usa o fluxo nativo de tokens de uso único do Django.

### Recuperação local pelo Gerenciador

Use:

```text
Gerenciar-Financeiro-OFX.bat
→ Usuários / recuperação
```

A tela mostra o username exatamente como está no banco e permite:

```text
Verificar senha
Cadastrar/alterar e-mail de recuperação
Redefinir senha
Configurar SMTP
Enviar e-mail de teste
```

A senha é validada com `User.check_password()` e redefinida com
`User.set_password()`. Nunca é possível recuperar a senha original em texto
claro, porque o Django armazena hash, não a senha reversível.

### Perfil do usuário

O nome do usuário no canto superior da aplicação passou a abrir:

```text
Minha conta
```

Nessa página o e-mail de recuperação pode ser alterado. A senha atual é
obrigatória para alterar o endereço, reduzindo o risco de uma sessão aberta
ser usada para trocar silenciosamente o destino da recuperação.

### SMTP

A recuperação por e-mail fica desativada até a configuração ser validada.
No Gerenciador, em `Usuários / recuperação → Configurar SMTP`, podem ser
informados:

```text
Servidor SMTP
Porta
Usuário SMTP
Senha / App Password
E-mail remetente
TLS/STARTTLS ou SSL direto
```

As configurações ficam no `.env` local, que permanece fora do GitHub.
Depois de salvar, o servidor é reiniciado quando necessário.

Variáveis adicionadas:

```text
PASSWORD_RECOVERY_EMAIL_ENABLED=False
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_TIMEOUT_SECONDS=15
DEFAULT_FROM_EMAIL=
PASSWORD_RESET_TIMEOUT_SECONDS=3600
```

O token de redefinição expira em 1 hora por padrão nesta aplicação.

Por segurança, solicitação e confirmação de recuperação só são aceitas em
localhost ou quando o Django reconhece uma conexão HTTPS. O modo LAN em HTTP
não permite redefinição de senha por link.

## Etapa 10.6 — Inicialização automática sem abrir o Gerenciador

A opção `Instalar / Atualizar` agora recria e testa a inicialização automática do servidor.
Depois da instalação, o Financeiro OFX sobe sozinho quando o usuário entra no Windows; não é necessário abrir o Gerenciador manualmente.

A implementação continua usando o Agendador de Tarefas do Windows com gatilho `ONLOGON`, executando diretamente:

```text
.venv\Scripts\pythonw.exe windows_manager.py --start
```

O antigo `windows/start_hidden.vbs` foi removido. O agendamento é criado com 10 segundos de atraso para permitir que o perfil do usuário e a rede terminem de inicializar.

Esse modo foi mantido de propósito em vez de transformar o aplicativo em um serviço `LocalSystem`: o projeto usa Python e `.venv` instalados no perfil do usuário, e executar o servidor web como `SYSTEM` aumentaria desnecessariamente os privilégios do processo. O resultado prático desejado é mantido: após reiniciar e entrar no Windows, o site fica disponível automaticamente.

Durante `Instalar / Atualizar`, o Gerenciador agora:

```text
recria o agendamento
→ para o servidor atual
→ aciona a própria tarefa agendada
→ confirma que http://127.0.0.1:8000 responde
→ só então informa sucesso
```

O status passou a distinguir:

```text
Inicialização automática: ATIVA (ao entrar no Windows)
Inicialização automática: PRECISA SER RECONFIGURADA
Inicialização automática: DESATIVADA
```

Se a inicialização automática falhar fora da interface gráfica, o erro é registrado em `logs/manager.log`.



## Etapa 10.5 — PDF AstroPay

O importador PDF passou a reconhecer também o modelo mensal da AstroPay
(`statement_BRL_YYYY_N.pdf`). O parser usa a estrutura real da tabela
`Histórico de transações` e preserva o mesmo modelo canônico usado pelos demais
importadores.

### Regras do extrato AstroPay

O PDF não fornece um ID bancário individual para cada linha. Por isso o sistema
cria um FITID sintético e determinístico com:

```text
conta técnica AstroPay
+ data
+ descrição
+ valor assinado
+ saldo posterior à operação
```

O saldo posterior faz parte da identidade para permitir duas movimentações
legítimas com a mesma data, descrição e valor (por exemplo, dois Cashbacks do
mesmo valor no mesmo dia).

A data de geração do PDF, a página e a posição visual NÃO fazem parte do FITID.
Assim, baixar novamente o mesmo extrato gera os mesmos identificadores e o
sistema reconhece as movimentações como já existentes.

### Saldo inicial/anterior/final

Linhas com:

```text
Saldo Inicial
Saldo Anterior
Saldo Final
```

são metadados do extrato e não são criadas como `Transaction`.

O `Saldo Final` do resumo continua sendo salvo em `ledger_balance`, mas não
entra como crédito ou débito. Isso evita duplicidade entre o fechamento de um
mês e a abertura do mês seguinte.

Meses sem movimentação real, contendo somente saldo inicial/final, são aceitos
como extratos válidos com zero itens — não são marcados como falha.

### Conta AstroPay

Como o PDF não traz número de conta, o parser cria um identificador técnico
estável usando titular + moeda. Na primeira importação o usuário pode cadastrar
e vincular a conta normalmente; os próximos PDFs do mesmo titular/moeda são
reconhecidos automaticamente.

### Pessoas / contrapartes

O resolver passou a reconhecer também o formato AstroPay:

```text
Ana Lucia Anastácio Da Silva Transferência Pix
```

como contraparte `Ana Lucia Anastácio Da Silva`. Prefixos bancários numéricos,
como `58.876.922`, continuam sendo preservados como identificador bancário da
contraparte, e não como parte do nome.



## Etapa 10.4 — Repositório mínimo e manifest de código-fonte

O fluxo de push passou de uma política de "adicionar tudo e bloquear o que
parece perigoso" para uma política mais restritiva:

```text
somente caminhos explicitamente autorizados
        ↓
git add -A -- <manifest>
        ↓
validar staging
        ↓
scanner de segredos
        ↓
commit
        ↓
push
```

O repositório contém o necessário para instalar o Financeiro OFX do zero,
incluindo código, migrations, templates, arquivos estáticos-fonte, testes,
dependências e scripts de instalação/execução.

Diretórios publicáveis:

```text
config/
core/
finance/
imports/
integrations/
services/
static/
templates/
windows/
```

Arquivos de raiz publicáveis:

```text
.env.example
.gitignore
Abrir-Financeiro-OFX.bat
Atualizar-GitHub.bat
Baixar-Atualizacao-GitHub.bat
GITHUB.md
Gerenciar-Financeiro-OFX.bat
MERCADO_PAGO_SETUP.md
README.md
SECURITY.md
github_sync.py
manage.py
requirements.txt
run.ps1
serve_waitress.py
setup.ps1
windows_manager.py
```

Os testes permanecem no repositório porque o processo de instalação os executa
antes de migrations. As migrations também são obrigatórias para criar um banco
novo corretamente.

Não são publicados:

```text
.env
db.sqlite3
.venv/
media/
staticfiles/
logs/
run/
backups/
samples/
VALIDACAO_ETAPA*.txt
*.ofx
*.qfx
*.pdf
*.csv
*.xls
*.xlsx
*.ods
*.zip
```

`media/.gitkeep` foi removido da política. O diretório `media/` não precisa
existir no clone: o Django/storage cria os diretórios necessários quando houver
arquivos importados.



## Etapa 10.3 — Atualização segura pelo GitHub e revisão dos BATs

Repositório oficial configurado nesta etapa:

```text
https://github.com/Th14g0R/financeiro-ofx
```

### Gerenciador

`Gerenciar-Financeiro-OFX.bat` continua abrindo a interface gráfica, que agora
possui:

```text
Verificar / baixar GitHub
```

`Instalar / Atualizar` também pergunta se o GitHub deve ser consultado antes
da atualização local.

O fluxo de download usa:

```text
git fetch
git pull --ff-only
```

O sistema não cria merge nem rebase automaticamente. Se o histórico local e o
GitHub divergirem, o download é cancelado.

Se houver arquivos locais alterados, o sistema também cancela o download para
não sobrescrever o trabalho local.

Antes de substituir arquivos por uma atualização remota, o servidor é parado.
Ele só volta a ser iniciado pelo fluxo de `Instalar / Atualizar`, depois de
dependências, checks, testes, backup e migrations.

### Pasta antiga que ainda não era um repositório Git

Ao verificar o GitHub pela primeira vez, a pasta pode ser conectada ao
repositório sem apagar os arquivos existentes:

```text
git init
git remote add origin ...
git fetch ...
git reset --mixed origin/<branch>
```

`reset --mixed` conecta o histórico e o índice ao GitHub, mas preserva o
conteúdo da pasta. Se o código local for diferente, essas diferenças aparecem
como alterações locais e precisam ser revisadas.

### Enviar alterações ao GitHub

Novo BAT:

```text
Atualizar-GitHub.bat
```

Ele chama `github_sync.py push`.

O processo:

1. valida a instalação do Git;
2. conecta a pasta ao repositório correto, se necessário;
3. executa `fetch`;
4. recusa push se houver commits remotos ainda não integrados;
5. verifica arquivos locais/sensíveis;
6. procura padrões conhecidos de segredo;
7. mostra o estado local;
8. solicita mensagem do commit;
9. cria o commit;
10. executa `git push`.

Se `user.name` ou `user.email` ainda não estiverem configurados, o próprio
fluxo solicita esses dois dados e os grava somente na configuração local deste
repositório.

Na primeira conexão com um repositório que já tenha histórico, se os arquivos
locais forem diferentes, o BAT exige a confirmação adicional:

```text
PUBLICAR LOCAL
```

Isso reduz o risco de publicar uma pasta antiga por engano.

### Proteção contra envio de dados locais

O push é bloqueado se detectar arquivos como:

```text
.env
.env.local / outras variantes .env.*
*.sqlite3
.venv/
media/
backups/
logs/
run/
staticfiles/
*.pem
*.key
*.p12
*.pfx
```

`.env.example` permanece permitido.

Também há uma verificação textual de alguns padrões de alto risco, incluindo
tokens Mercado Pago, tokens GitHub e chaves privadas.

Essa verificação é uma camada adicional; ela não substitui a revisão do
`git status` nem ferramentas especializadas de secret scanning.

### BAT de abertura

`Abrir-Financeiro-OFX.bat` foi corrigido para não abrir o navegador antes de o
servidor realmente responder.

O BAT agora executa:

```text
python windows_manager.py --start
```

de forma síncrona e só abre `http://127.0.0.1:8000/` se o comando concluir com
sucesso.

Se a `.venv` ou `windows_manager.py` não existirem, mostra erro em vez de abrir
uma página sem servidor.

### BAT do Gerenciador

`Gerenciar-Financeiro-OFX.bat` agora valida:

- `requirements.txt`;
- `windows_manager.py`;
- Python 3.14;
- criação da `.venv`;
- atualização inicial do pip;
- instalação das dependências;
- existência do `pythonw.exe`.

### Download direto por BAT

Também foi incluído:

```text
Baixar-Atualizacao-GitHub.bat
```

Ele executa a mesma política de download `fast-forward only` fora da interface
gráfica.

Depois de baixar uma alteração por esse BAT, execute
`Gerenciar-Financeiro-OFX.bat → Instalar / Atualizar`.

### Autenticação GitHub

Nenhum token GitHub é gravado nos BATs ou no código.

Em HTTPS, use Git Credential Manager ou um Personal Access Token quando o Git
solicitar autenticação. Senha comum da conta GitHub não deve ser colocada no
BAT nem em arquivos do projeto.



## Etapa 10.2 — Unificação manual de nomes similares

A associação automática continua conservadora: ela só unifica registros quando
há evidência suficiente. Para nomes similares ou duvidosos que permanecerem
separados, a tela `Pessoas / contrapartes` agora permite decisão manual.

Fluxo:

```text
Pesquisar nomes semelhantes
        ↓
marcar 2 ou mais registros
        ↓
Unificar selecionados
        ↓
revisar movimentos, aliases e identificadores
        ↓
escolher o registro principal
        ↓
informar/corrigir o nome final
        ↓
Confirmar unificação
```

Exemplo real:

```text
THOMPSON RESENDE DA SILVA
THOMPSON RESENDE DA SILVA OLIVEIRA
```

O sistema não precisa assumir automaticamente que são a mesma pessoa. O
usuário pode pesquisar `THOMPSON`, selecionar os dois e decidir.

### O que é preservado

A unificação manual não altera:

- FITID;
- data/hora;
- banco/conta;
- valor;
- descrição original;
- origem OFX/PDF/API.

As movimentações dos registros secundários passam a apontar para o registro
principal. Todos os nomes anteriores são copiados como aliases, e os registros
secundários são apenas desativados — não são apagados.

Isso também faz com que uma futura `Reanalisar associações` continue
reconhecendo as variantes antigas no registro consolidado.

### Escolha do registro principal

Na tela de confirmação o usuário escolhe qual ID permanecerá ativo. O sistema
sugere como principal o registro com mais movimentações; em empate, prefere o
nome mais completo.

O `Nome final` também pode ser corrigido manualmente antes de salvar.

### Segurança contra unificações equivocadas

Antes da gravação, o preview mostra:

- tipo Pessoa/Empresa;
- quantidade de movimentações;
- aliases de nome;
- PIX;
- CPF/CNPJ;
- identificadores bancários.

Diferenças de PIX ou identificadores bancários geram aviso, pois uma pessoa
pode legitimamente possuir mais de uma conta/chave.

Conflitos mais fortes exigem uma confirmação extra:

- CPFs/CNPJs completos diferentes;
- seleção que mistura Pessoa e Empresa.

A operação usa `transaction.atomic()` para que transferência de movimentações,
cópia de aliases, atualização do registro principal e desativação dos
secundários sejam concluídas como uma única operação lógica.

Não há migration nova nesta etapa.


## Etapa 10.1 — Associação bancária de pessoas e empresas

A associação de contrapartes foi ampliada para interpretar os formatos vistos
nos extratos reais, em especial descrições do Banco do Brasil e cadastros
legados que continham data, horário, identificador numérico ou parcela dentro
do nome.

Exemplos agora tratados:

```text
Pix - Enviado - 29/08 08:37 Livia Alves Mendes
    -> Livia Alves Mendes

15/01 FRANCISCA DEIJANE CARVAL 001/011
15/02 FRANCISCA DEIJANE CARVAL 002/011
15/03 FRANCISCA DEIJANE CARVAL 003/011
    -> FRANCISCA DEIJANE CARVAL

46.685.824 ROSENILSON EDUARDO DE SOUSA
46685824 ROSENILSON EDUAR
    -> mesmo identificador bancário 46685824
    -> ROSENILSON EDUARDO DE SOUSA

02/04 17:09 ANA LUCIA ANASTACIO DA S
    -> ANA LUCIA ANASTACIO DA S
```

O texto bancário bruto continua preservado como evidência. Ele não é mais
usado como se fosse o nome da pessoa.

### Regras de associação

A resolução usa, nesta ordem:

1. identificador PIX mascarado exato;
2. identificador bancário normalizado exato;
3. nome/alias normalizado exato;
4. nome truncado, somente quando há prefixo token a token e um único candidato.

A regra de truncamento não usa apenas percentual de similaridade. Por exemplo,
`JOAO SILVA` não é mesclado automaticamente com `JOAO SILVA JUNIOR`; já
`ROSENILSON EDUAR` pode ser associado a `ROSENILSON EDUARDO DE SOUSA`, pois o
último token está claramente truncado.

Se houver mais de um candidato compatível, o sistema não escolhe
silenciosamente.

### Saneamento do histórico existente

`rebuild_counterparties` agora reanalisa todas as movimentações automáticas
(OFX/PDF/API/importação), preservando movimentações manuais que já tenham uma
contraparte escolhida pelo usuário.

Antes da reanálise ele:

- remove data/hora incorporada ao display_name;
- remove sufixos de parcela, como `001/011`;
- separa identificadores numéricos do nome;
- cria alias `Identificador bancário`;
- mescla duplicidades por identificador ou nome exato;
- faz uma segunda passagem conservadora para nomes truncados;
- desativa cadastros automáticos órfãos, sem apagar o histórico.

O instalador já executa `rebuild_counterparties` após as migrations, portanto
essas correções também são aplicadas ao banco existente quando a atualização
for concluída.

A tela **Pessoas / contrapartes** também recebeu o botão
`Reanalisar associações`, permitindo executar o mesmo saneamento sem PowerShell.
A operação não altera `raw_description`, FITID, valor ou data do extrato.


## Etapa 10 — Transferências entre contas próprias

O Dashboard deixou de tratar automaticamente todo crédito bancário como
receita e todo débito bancário como despesa.

A partir desta etapa há duas camadas independentes:

```text
Movimentação bancária
    ├── Externa
    ├── Possível transferência interna
    └── Transferência interna confirmada
```

O extrato original não é modificado. A classificação interna fica em um
modelo separado (`InternalTransfer`) que relaciona a perna de saída com a
perna de entrada.

### Contas próprias

`Account` recebeu:

```text
is_own_account = True/False
```

Todas as contas já existentes recebem `True` pela migration, preservando o
comportamento esperado para contas que já eram do titular.

A tela de Contas permite filtrar e alterar:

```text
Minha conta
Outra
```

Quando uma conta deixa de ser marcada como própria, vínculos internos ativos
que dependiam dela são rejeitados e as movimentações voltam à classificação
externa.

### Matching automático

Valor igual é obrigatório, mas nunca suficiente sozinho.

O motor considera:

- conta de saída e conta de entrada marcadas como próprias;
- contas diferentes;
- débito de um lado e crédito do outro;
- valor exatamente igual;
- PIX/TED/DOC/Transferência no tipo ou histórico;
- mesma data ou diferença bancária controlada;
- horário, quando ambos os bancos o fornecem;
- contraparte;
- documento/referência;
- menção ao banco da outra conta no histórico.

Pontuação:

```text
>= 90 + par mutuamente único + evidência forte
    → Transferência interna confirmada automaticamente

>= 70 + par mutuamente único
    → Possível transferência interna para revisão

ambíguo
    → não cria vínculo
```

Para auto confirmação, a pontuação alta ainda precisa de ao menos uma evidência
forte: contraparte/nome correspondente, documento/referência correspondente,
menção ao banco da outra conta no histórico ou horários bancários com
diferença de até 1 minuto.

Se dois candidatos tiverem pontuação próxima, o sistema não escolhe um deles
silenciosamente.

### Revisão

Nova tela:

```text
Transferências internas
```

Permite:

- executar a análise;
- ver sugestões pendentes;
- confirmar uma sugestão;
- informar que não é transferência interna;
- consultar confirmadas;
- desfazer um vínculo confirmado.

Um par rejeitado não é recriado automaticamente com as mesmas duas
movimentações.

### Dashboard

Os três indicadores principais agora são:

```text
Entradas externas
Saídas externas
Resultado externo
```

Transferências internas confirmadas deixam de compor esses três totais.

Existe um quarto indicador:

```text
Entre minhas contas
```

Na visão consolidada ele mostra o volume movimentado contando cada
transferência uma única vez.

Quando um banco específico é selecionado, mostra:

```text
Recebido de minhas contas
Enviado para minhas contas
Movimento interno líquido
```

O Dashboard ainda disponibiliza os valores bancários brutos para auditoria:

```text
Crédito bancário bruto
Débito bancário bruto
```

Assim é possível comparar a visão financeira externa com o que efetivamente
entrou/saiu dos extratos.

Sugestões `POSSIBLE` permanecem contabilizadas como externas até confirmação,
evitando que uma heurística reduza receita/despesa silenciosamente.

### Movimentações

A tela de Movimentações recebeu filtro e coluna:

```text
Externa
Transferência interna
Possível transferência interna
```

### Importações

Após uma importação ser gravada com sucesso, a análise de transferências
internas é registrada com `transaction.on_commit()`. Portanto ela só executa
depois do commit do lote.

O instalador também executa:

```text
python manage.py analyze_internal_transfers
```

após as migrations para analisar o histórico já existente.

### Integridade

`InternalTransfer` usa constraints condicionais para impedir que uma mesma
movimentação participe de mais de um vínculo ativo (`POSSIBLE` ou
`CONFIRMED`) ao mesmo tempo.

As duas movimentações continuam independentes e mantêm:

- conta;
- FITID;
- data/hora;
- valor;
- origem OFX/PDF/API;
- descrição bruta.

Excluir uma movimentação importada remove apenas o vínculo de classificação
associado, por `CASCADE`; não altera a movimentação correspondente da outra
conta.


## Revisão 9.2.2 — último teste do Dashboard + acesso LAN reversível

A suíte real do Windows chegou a 109 testes e restou uma única falha:
`test_dashboard_contains_chart_payloads` esperava o elemento `expenseChart`
mesmo quando o período não possuía saídas. Nessa condição, o comportamento
correto da interface é exibir a mensagem "Não há saídas no período
selecionado" e manter somente `data-expense-chart` com payload vazio.

Correção:

- Dashboard sem saídas testa `data-expense-chart`;
- Dashboard que possui débito confirma que `expenseChart` é renderizado.

### Rede local

O Gerenciador Windows agora possui:

```text
Abrir para rede local
Fechar acesso de rede
```

Ao abrir:

1. identifica um IPv4 privado da máquina;
2. mantém `DJANGO_DEBUG=False`;
3. define `FINANCEIRO_HOST=0.0.0.0`;
4. ativa `FINANCEIRO_LAN_MODE=True`;
5. mantém `DJANGO_ALLOWED_HOSTS` explícito, sem `*`;
6. solicita elevação UAC;
7. cria uma regra do Windows Firewall:
   - TCP;
   - porta configurada do Financeiro OFX;
   - perfil `Private`;
   - origem `LocalSubnet`;
   - Edge Traversal bloqueado;
8. reinicia o servidor;
9. mostra o endereço `http://IP-LOCAL:8000/`.

Ao fechar:

1. o servidor é parado;
2. tenta remover a regra do Firewall;
3. independentemente do resultado do Firewall, volta para
   `FINANCEIRO_HOST=127.0.0.1`;
4. desativa `FINANCEIRO_ALLOW_NETWORK` e `FINANCEIRO_LAN_MODE`;
5. reinicia o sistema somente em localhost.

Por segurança, criação e alteração de credenciais bancárias continuam
bloqueadas quando o acesso é feito remotamente por HTTP na LAN. Essas
operações precisam ser realizadas em `127.0.0.1` ou através de HTTPS.

O modo LAN é destinado apenas a uma rede privada/confiável. Não equivale a
publicação segura na Internet.


## Revisão 9.2.1 — correção da instalação/testes

A execução real no Windows encontrou dois problemas de infraestrutura de teste,
não problemas do banco nem da regra financeira:

1. Com `DJANGO_DEBUG=False`, o projeto usa
   `CompressedManifestStaticFilesStorage`. A suíte roda antes de
   `collectstatic`, portanto o manifesto ainda não conhecia o novo
   `static/js/dashboard.js`, causando:
   `Missing staticfiles manifest entry for 'js/dashboard.js'`.

   Correção: somente durante `manage.py test`, o backend de arquivos estáticos
   passa a ser `django.contrib.staticfiles.storage.StaticFilesStorage`.
   Na execução normal, WhiteNoise + Manifest continua ativo.

2. O login bloqueado pelo rate limiter criava um formulário para exibir a
   mensagem de bloqueio e chamava `add_error()` antes de inicializar
   `cleaned_data`.

   Correção: o formulário bloqueado agora inicializa `cleaned_data = {}` antes
   de `add_error()`, sem executar nova autenticação.

Não há migration nova nesta revisão.

O instalador continua executando todos os testes antes de backup/migrate. Se a
suíte falhar, o banco principal não é alterado.
A Etapa 9 corrige a heurística de duplicidade sem FITID e amplia o sistema
para extratos PDF, integração Mercado Pago via API, ordenação de tabelas e
Dashboard por mês/ano/período.



## Revisão 9.2 — Dashboard por banco, Mercado Pago e hardening

### Dashboard

Foi acrescentado filtro por banco ao Dashboard. O recorte selecionado passa a
ser aplicado integralmente a:

- entradas;
- saídas;
- movimento líquido;
- quantidade de movimentações;
- gráfico Entradas x Saídas;
- gráfico lateral;
- drill-down mês/ano;
- atalho para a lista de movimentações.

Com `Todos os bancos`, o gráfico lateral compara saídas por banco. Com um
banco específico, ele mostra as saídas separadas pelas contas desse banco.

### Mercado Pago

Para a própria conta Mercado Pago, o modo recomendado no sistema é
`Client ID + Client Secret`. O backend gera e renova o Access Token pelo fluxo
Client Credentials. A Public Key não é usada para o relatório bancário.

O cadastro/alteração de credenciais exige confirmação da senha atual do
Financeiro OFX.

### Segurança

A revisão adiciona defesa em profundidade:

- rate limit persistente de login por usuário e IP;
- trilha de eventos de segurança;
- CSP e headers complementares;
- SRI nos recursos CDN;
- cookies/sessões endurecidos;
- modo HTTPS explícito;
- bloqueio de exposição acidental do Waitress;
- validações de deployment;
- credenciais bancárias criptografadas e reautenticação;
- chamadas Mercado Pago com redirects recusados, timeout, erros sanitizados e
  limite de download;
- validação do arquivo do relatório contra a lista retornada pela API.

Consulte `SECURITY.md` antes de expor a aplicação em rede ou Internet.

Não há garantia técnica de risco zero em um sistema conectado à Internet.
Para instalação pública, MFA é a próxima camada de autenticação recomendada.
## Revisão 9.1 — correções após a suíte real do Windows

A suíte Django executada no ambiente Windows identificou dois problemas
introduzidos na montagem da Etapa 9:

1. `templates/finance/transaction_list.html` conservou parte do bloco antigo
   de paginação depois da inclusão da nova paginação com `querystring`. Isso
   deixou um `{% endif %}` excedente e causava `TemplateSyntaxError`.
2. O teste da tela de upload ainda esperava o texto antigo `Importar OFX`,
   embora a interface tenha sido ampliada para OFX/QFX/PDF/CSV e agora use
   `Importar extrato`.

A revisão 9.1 remove o bloco obsoleto e atualiza o teste para a nomenclatura
atual.

Não há migration nova nesta revisão.

## 1. Correção dos dois testes da Etapa 8

Os testes:

```text
test_missing_fitid_uses_fingerprint_only_as_possible_duplicate
test_possible_duplicate_can_be_forced_and_fingerprint_is_not_unique
```

falhavam porque o fingerprint usava diretamente `posted_at.isoformat()`.

Com `USE_TZ=True`, o mesmo instante pode existir no staging no fuso local e,
depois de persistido, ser retornado pelo Django em UTC. O instante é igual,
mas a string usada no SHA-256 era diferente.

### Fingerprint v2

Agora o fingerprint:

1. transforma a data/hora em UTC;
2. remove microssegundos;
3. normaliza tipo, descrição, documento e referência;
4. calcula o SHA-256 do valor canônico.

Novas movimentações recebem:

```text
fingerprint_version = 2
```

Para registros antigos sem FITID há também um fallback estrutural
conservador, usando:

```text
conta
data/hora
valor
natureza
tipo
descrição
documento
referência
```

Assim:

```text
FITID presente
    → identidade forte: conta + FITID

FITID ausente + fingerprint/estrutura igual
    → POSSÍVEL DUPLICADO
    → decisão do usuário
```

O fingerprint continua sendo heurística; não possui restrição UNIQUE.

---

## 2. Extrato PDF

O upload principal agora aceita:

```text
.ofx
.qfx
.pdf
.csv
```

### Mercado Pago PDF

Foi criado um parser específico para o modelo de **Extrato de Conta do
Mercado Pago**.

Ele extrai:

```text
banco
agência
conta
período
saldo final
data
descrição
ID da operação
valor
saldo
```

O campo:

```text
ID da operação
```

é convertido para o identificador local da transação (`fitid`), porque é o
identificador fornecido pelo próprio provedor para aquela movimentação.

O PDF não informa horário de cada linha nesse modelo; por isso a interface
mantém:

```text
horário não informado
```

em vez de inventar `00:00`.

O parser desta versão foi validado contra o PDF Mercado Pago fornecido para
desenvolvimento: as 18 movimentações das duas páginas foram extraídas,
incluindo IDs e sinais de entrada/saída.

### Outros bancos em PDF

A arquitetura está separada em:

```text
services/statements/
```

Portanto novos bancos podem ganhar parsers próprios sem alterar o motor
financeiro.

Nesta versão o PDF implementado e validado é o **Mercado Pago**. Um PDF de
outro banco recebe uma mensagem clara de formato ainda não suportado, em vez
de tentar importar dados incorretos.

Não é utilizado OCR quando o PDF já contém texto pesquisável.

---

## 3. Origem do arquivo

`ImportFile` agora registra:

```text
source_format
provider
source_reference
```

Formatos:

```text
OFX
PDF
API_CSV
CSV
```

Provedores atuais:

```text
GENERIC
MERCADO_PAGO
```

A tela da importação mostra o formato/provedor junto do SHA-256.

---

## 4. Integrações bancárias via API

Novo menu:

```text
Integrações
```

Novo app Django:

```text
integrations
```

A arquitetura permite adicionar novos provedores.

### Mercado Pago

A primeira implementação usa o relatório:

```text
Dinheiro em conta / Account Money Report
```

Fluxo:

```text
Integração Mercado Pago
        ↓
Autenticação
        ↓
Configurar relatório
        ↓
Solicitar período
        ↓
Mercado Pago gera o relatório assincronamente
        ↓
Listar relatórios prontos
        ↓
Baixar CSV
        ↓
ImportBatch / staging
        ↓
revisão
        ↓
gravação
```

Endpoints implementados:

```text
POST /oauth/token

GET/POST /v1/account/settlement_report/config

POST /v1/account/settlement_report

GET /v1/account/settlement_report/list

GET /v1/account/settlement_report/:file_name
```

O relatório CSV usa `SOURCE_ID` como identificador da operação no staging.

### Autenticação

Modos disponíveis:

```text
Client ID + Client Secret
Access Token
```

O fluxo Client Credentials é destinado à leitura dos próprios recursos da
conta associada à aplicação.

As credenciais secretas não são armazenadas em texto puro.

Campos sensíveis usam Fernet com:

```text
FINANCEIRO_CREDENTIAL_KEY
```

O Gerenciador do Windows cria a chave automaticamente.

Para contas de terceiros, a próxima evolução deve usar o fluxo OAuth
Authorization Code e consentimento do titular, em vez de compartilhar
credenciais.

---

## 5. Dashboard

O Dashboard foi reorganizado.

### Mês

```text
Visualizar mês
[ 08/2026 ] [ Ver mês ]
```

O gráfico fica detalhado por dia.

### Ano

```text
Visualizar ano
[ 2026 ] [ Ver ano ]
```

O gráfico apresenta os meses do ano.

É possível escolher qualquer ano que possua movimentações, além do ano atual.

### Clique no mês

Quando o gráfico estiver agrupado por mês:

```text
Jan/26  Fev/26  Mar/26 ...
```

clique em uma barra de determinado mês.

O sistema navega para:

```text
?month=YYYY-MM
```

e monta o gráfico diário daquele mês.

Também existem botões Jan–Dez quando a visão anual está ativa.

### Período personalizado

Continua disponível:

```text
Data inicial
Data final
Aplicar
```

Até 62 dias:

```text
agrupamento diário
```

Acima de 62 dias:

```text
agrupamento mensal + drill-down por clique
```

### Alinhamento

Mês, Ano e Período personalizado foram separados em blocos responsivos e
alinhados pela base dos controles.

---

## 6. Valores em BRL

Foi criado:

```text
finance/templatetags/finance_extras.py
```

Exemplos:

```text
8261.44     → R$ 8.261,44
8389.08     → R$ 8.389,08
-127.64     → -R$ 127,64
```

Também há formato assinado para linhas:

```text
+ R$ 35,00
- R$ 8,98
```

O Dashboard, Movimentações, Pessoas/Contrapartes e staging passaram a usar
esses filtros.

O Chart.js continua usando `Intl.NumberFormat("pt-BR", currency="BRL")`.

---

## 7. Ordenação por cabeçalhos

Clique nos títulos das tabelas para alternar:

```text
↑ crescente
↓ decrescente
```

Aplicado em:

```text
Pessoas / contrapartes
Movimentações
Bancos
Contas
Histórico de importações
Integrações
Extrato consolidado da contraparte
```

A ordenação ocorre no banco de dados, antes da paginação.

Filtros, busca e ordenação permanecem na URL.

A paginação usa o `querystring` do Django para preservar os parâmetros atuais.

---

## 8. Pessoas / contrapartes

Além dos aliases existentes, o rebuild passou a melhorar o campo `Tipo`.

Nomes com marcadores jurídicos inequívocos, como:

```text
LTDA
EIRELI
SOCIEDADE ANÔNIMA
INSTITUIÇÃO DE PAGAMENTO
```

são classificados como:

```text
Empresa
```

em vez de `Pessoa`.

O comando:

```text
rebuild_counterparties
```

também revisa contrapartes já cadastradas.

---

## 9. Instalação mais segura

O Gerenciador do Windows continua sendo o modo recomendado:

```text
Gerenciar-Financeiro-OFX.bat
```

A sequência de atualização mudou para:

```text
instalar dependências
↓
manage.py check
↓
makemigrations --check --dry-run
↓
EXECUTAR TESTES
↓
somente se os testes passarem:
    migrate
    rebuild_counterparties
    collectstatic
↓
reiniciar servidor
```

Isso corrige o problema de uma instalação com testes falhando alterar o banco
local antes de informar o erro.

O `setup.ps1` segue a mesma política para quem quiser usá-lo manualmente.

---

## 10. Dependências adicionadas

```text
PyMuPDF>=1.27,<2
requests>=2.32,<3
cryptography>=48,<51
```

Além das dependências anteriores.

PyMuPDF é usado para extrair texto/posição dos PDFs pesquisáveis.
Requests é usado para APIs.
Cryptography protege as credenciais das integrações.

---

## Atualização

Extraia o ZIP por cima da pasta atual:

```text
C:\TEMP\site\financeiro-ofx
```

Preserve:

```text
.env
db.sqlite3
.venv
media/
```

Depois dê duplo clique em:

```text
Gerenciar-Financeiro-OFX.bat
```

e clique:

```text
Instalar / Atualizar
```

O Gerenciador fará os testes antes de migrar seu banco local.

### Teste recomendado após a atualização

1. Confirme que a instalação termina com todos os testes `OK`.
2. Abra o Dashboard e verifique:
   - `R$ 8.261,44`;
   - seleção de mês;
   - seleção de ano;
   - clique em mês do gráfico anual.
3. Abra Pessoas e clique em `Nome` / `Movimentações` para ordenar.
4. Importe o PDF Mercado Pago pela tela `Importar extrato`.
5. Confira Agência, Conta e IDs da operação antes de gravar.
6. Cadastre uma integração Mercado Pago em `Integrações`.
7. Teste a conexão.
8. Solicite um relatório de um período.
9. Quando aparecer na lista, clique `Importar para staging`.
10. Revise antes de gravar, exatamente como em OFX/PDF.

## Próximas evoluções

- parsers PDF para outros bancos;
- OAuth Authorization Code para contas de terceiros;
- sincronização agendada das integrações;
- mesclagem de contrapartes duplicadas;
- exportação consolidada para o sistema de empréstimos;
- previsão de pagamentos/cartões e conciliação entre contas.
