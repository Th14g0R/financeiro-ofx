# Financeiro OFX — GitHub

Repositório:

```text
https://github.com/Th14g0R/financeiro-ofx
```

## 1. Verificar se existe atualização

Opção principal:

```text
Gerenciar-Financeiro-OFX.bat
→ Verificar / baixar GitHub
```

O sistema faz `git fetch`, compara o commit local com o branch principal remoto
e informa:

- commits locais não enviados;
- commits disponíveis no GitHub;
- existência de arquivos locais alterados.

O download automático só ocorre quando a árvore local está limpa e o histórico
pode avançar por fast-forward.

## 2. Atualizar o sistema usando o GitHub

Use:

```text
Gerenciar-Financeiro-OFX.bat
→ Instalar / Atualizar
```

Responda `Sim` à pergunta sobre verificar o GitHub.

Se existir atualização e for seguro baixá-la:

```text
GitHub
→ download fast-forward
→ dependências
→ Django check
→ migrations --check
→ testes
→ backup SQLite
→ migrate
→ rebuild_counterparties
→ analyze_internal_transfers
→ collectstatic
→ reinicia servidor
```

O banco principal só é migrado depois que a suíte de testes passa.

## 3. Subir alterações locais

Execute:

```text
Atualizar-GitHub.bat
```

O BAT mostra as alterações e solicita a mensagem do commit.

Na primeira execução ele também pode solicitar:

```text
Nome para os commits
E-mail para os commits
```

Esses valores são gravados apenas no `.git/config` do Financeiro OFX.

Depois confirme:

```text
SIM
```

Se for a primeira conexão de uma pasta local diferente de um repositório que
já possui histórico, haverá ainda uma confirmação:

```text
PUBLICAR LOCAL
```

## 4. Segurança antes do push

O processo bloqueia arquivos e pastas sensíveis, incluindo:

```text
.env
.env.*
*.sqlite3
.venv
media
backups
logs
run
staticfiles
*.pem
*.key
*.p12
*.pfx
```

A exceção é:

```text
.env.example
```

Também bloqueia padrões conhecidos de Access Token do Mercado Pago, tokens do
GitHub e chaves privadas.

Mesmo assim, revise sempre a lista apresentada pelo Git antes de confirmar o
push.

## 5. Se o GitHub tiver alterações novas

O push é interrompido.

Não é executado `push --force`.

Primeiro verifique/baixe as alterações remotas. Se existir divergência real
entre históricos, resolva-a conscientemente com Git antes de continuar.

## 6. Se houver alterações locais durante o download

O download é cancelado.

O sistema não executa automaticamente:

```text
git reset --hard
git clean
git stash
git merge
git rebase
git push --force
```

Esses comandos poderiam apagar ou reescrever trabalho local.

## 7. Autenticação

A URL configurada é HTTPS.

O projeto não guarda usuário, senha, PAT ou token GitHub.

Use preferencialmente o Git Credential Manager instalado com Git for Windows.
Se o GitHub solicitar credencial via HTTPS, use um método atualmente aceito
pelo GitHub, como Personal Access Token; não grave esse token no projeto.

## 8. Rollback de código após download

Antes de um pull que realmente baixa commits, o Financeiro OFX registra o
commit anterior dentro do próprio diretório `.git`:

```text
.git/financeiro-ofx-before-update.txt
```

Esse arquivo não é enviado ao GitHub.

Ele serve como referência para recuperação manual caso seja necessário
identificar qual commit estava instalado antes da atualização.


## Manifest de arquivos enviados

`Atualizar-GitHub.bat` não executa mais um `git add -A` irrestrito no projeto.

A ferramenta mantém um manifest explícito em `github_sync.py`. Somente código,
migrations, testes, templates, static-fonte, scripts de instalação/execução e
documentação operacional entram no staging.

Isso é intencional: o GitHub recomenda evitar comandos catch-all ao lidar com
risco de dados sensíveis e revisar exatamente o que será colocado no commit.

Arquivos financeiros ou locais ficam fora mesmo que sejam criados na raiz da
pasta:

```text
*.ofx
*.qfx
*.pdf
*.csv
*.xls
*.xlsx
*.ods
.env*
*.sqlite3*
media/
backups/
logs/
```

A única exceção de ambiente que pode ser publicada é `.env.example`, que deve
conter somente nomes/configurações de exemplo, nunca credenciais reais.

`VALIDACAO_ETAPA*.txt` e `samples/` também são locais e não são necessários para
instalar o sistema do zero.

Se no futuro um novo arquivo de código precisar ser publicado fora dos
diretórios já autorizados, ele deve ser adicionado conscientemente ao manifest
`ESSENTIAL_TOP_LEVEL_FILES` ou `ESSENTIAL_TOP_LEVEL_DIRS`.
