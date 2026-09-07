# Financeiro OFX — Auditoria de segurança da Etapa 10.8

## Objetivo

Esta etapa adiciona controles automatizados para reduzir risco de acesso
indevido, injeção de dados, XSS, CSRF, clickjacking, vazamento de sessão,
exposição de segredos e alterações sem autoria conhecida.

O processo de instalação agora executa, antes de alterar o banco principal:

```text
manage.py test
manage.py security_audit --fail-on-high
```

Se a auditoria automatizada encontrar um achado classificado como `HIGH`, a
instalação é interrompida antes do backup/migrations.

## Controles verificados automaticamente

- `DEBUG=False`;
- `ALLOWED_HOSTS` sem `*`;
- `SECRET_KEY` longa e não baseada em `django-insecure-`;
- Django >= 5.2.17;
- `SecurityMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware` e
  `XFrameOptionsMiddleware` presentes;
- `X_FRAME_OPTIONS=DENY`;
- `SESSION_COOKIE_HTTPONLY=True`;
- CSP e headers complementares;
- formulários POST internos com `{% csrf_token %}`;
- busca por `eval()`, `exec()`, `mark_safe()`, SQL por f-string e
  `subprocess(..., shell=True)`;
- busca por tokens GitHub, Mercado Pago e private keys no código versionável;
- scripts JavaScript externos sem SRI;
- `check --deploy` do Django como parte da análise.

## Testes de regressão adicionados

A suíte Django inclui testes para:

- login sem CSRF → HTTP 403;
- host não autorizado → HTTP 400;
- payload XSS no login não ser refletido como HTML executável;
- payload com aparência de SQL não causar bypass/erro na busca;
- páginas financeiras exigirem autenticação;
- headers `X-Frame-Options`, `X-Content-Type-Options` e CSP;
- operador não acessar gerenciamento de usuários/auditoria;
- criação de segundo usuário com perfil próprio;
- desativação de usuário invalidar sessões existentes;
- todas as operações autenticadas POST/PUT/PATCH/DELETE gerarem `AuditEvent`;
- decisões de acesso negadas (HTTP 401/403) de usuários autenticados serem auditadas;
- falhas de login gerarem evento de segurança sem registrar a senha;
- senha informada em formulários não ser gravada no `AuditEvent`;
- título das abas iniciar por `Financeiro | ...`.

## Trilha de auditoria

`AuditEvent` registra somente metadados necessários:

```text
usuário
operação/rota
método HTTP
caminho
status HTTP
sucesso/falha
request-id
hash protegido do IP
nomes de campos não sensíveis
```

Não são gravados valores de senha, token, segredo, client secret, access token,
CSRF ou conteúdo de arquivos importados.

## Limitações e risco residual

Esta auditoria é uma combinação de revisão estática local + testes de regressão
Django. Ela não substitui um pentest externo autorizado, DAST contra uma
instância isolada, análise de infraestrutura/rede ou scanner de dependências
baseado em CVEs. Nesta geração do pacote, a análise estática estrutural foi
executada no ambiente de build; a suíte Django completa continua sendo
executada no Windows pelo fluxo `Instalar / Atualizar` antes das migrations.

Dois riscos permanecem conscientemente visíveis:

1. **Modo LAN sem HTTPS:** aceitável apenas em rede privada/confiável, com o
   Firewall limitado a `LocalSubnet`. Credenciais bancárias, recuperação de
   senha, gerenciamento administrativo de usuários, alteração do próprio perfil
   sensível e `/admin/` continuam restritos a localhost ou HTTPS.
2. **Recursos CDN:** Bootstrap e Chart.js permanecem via jsDelivr, mas ambos
   usam `integrity` (SRI) e `crossorigin="anonymous"`. A CSP permite somente
   o domínio necessário. Para ambientes completamente isolados da Internet,
   esses recursos podem ser versionados localmente em uma etapa futura.

## Dependências

A Etapa 10.8 eleva o mínimo do Django para:

```text
Django>=5.2.17,<5.3
```

para exigir a linha 5.2 já contendo os patches de segurança publicados até
agosto de 2026.

## Validação estrutural desta geração

No ambiente de build da Etapa 10.8 foi executada uma análise estática adicional,
sem carregar o Django, cobrindo **121 arquivos Python** e **36 templates**. O
resultado foi:

```text
Erros estruturais encontrados: 0
Templates derivados de base.html sem título: 0
Formulários POST internos sem csrf_token: 0
Uso de |safe / autoescape off: 0
Scripts JavaScript externos sem SRI: 0
Padrões eval/exec/mark_safe/shell=True/SQL por f-string: 0
Padrões concretos de token/chave privada: 0
```

Essa verificação não substitui `manage.py test`, `manage.py check --deploy` nem o
comando `security_audit`. Esses controles dependem do Django instalado e serão
executados no Windows pelo fluxo **Instalar / Atualizar**, antes das migrations.


## Chave secreta legada

O instalador corrige automaticamente `DJANGO_SECRET_KEY` quando ela estiver
ausente, tiver menos de 50 caracteres ou começar com `django-insecure-`.

A correção é feita sem mostrar nem registrar o valor da chave. A troca não
altera hashes de senha nem a chave usada para criptografar credenciais
bancárias. Sessões e links de recuperação gerados com a chave antiga deixam de
ser válidos.

`financeiro_security.W003` indica somente que o modo LAN privado está ativo
sem HTTPS. Esse aviso continua visível e não é convertido em achado HIGH.
