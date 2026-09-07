# Financeiro OFX — Segurança e Integrações Bancárias

## Princípio geral

O Financeiro OFX trata credenciais bancárias, relatórios financeiros e
movimentações como dados sensíveis. A segurança é implementada em camadas.
Nenhuma aplicação conectada à Internet pode prometer risco zero; a meta é
reduzir a superfície de ataque, falhar de forma segura, limitar impacto e
manter rastreabilidade.

## Padrão recomendado: uso local

A configuração padrão continua sendo:

```text
FINANCEIRO_HOST=127.0.0.1
FINANCEIRO_ALLOW_NETWORK=False
DJANGO_SECURE_MODE=False
DJANGO_DEBUG=False
```

Nesse modo, o Waitress aceita conexões somente do próprio computador.

Não altere `FINANCEIRO_HOST` para `0.0.0.0` apenas para acessar o sistema de
fora. Para acesso remoto, use HTTPS corretamente configurado.

## Acesso pela rede / Internet

Antes de expor o sistema:

1. Use um domínio próprio.
2. Coloque um reverse proxy HTTPS na frente do Waitress.
3. Mantenha o Waitress em `127.0.0.1` sempre que o proxy estiver na mesma
   máquina.
4. Configure no `.env`:

```text
DJANGO_DEBUG=False
DJANGO_SECURE_MODE=True
DJANGO_ALLOWED_HOSTS=financeiro.seudominio.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://financeiro.seudominio.com
FINANCEIRO_ALLOW_NETWORK=False
```

Se o reverse proxy estiver em outra máquina e for realmente necessário expor
o Waitress na rede interna, configure `FINANCEIRO_ALLOW_NETWORK=True` somente
após restringir firewall/origem da conexão.

`DJANGO_TRUST_PROXY_SSL_HEADER=True` só deve ser usado quando o proxy confiável
remove o header recebido do cliente e define `X-Forwarded-Proto` corretamente.

Depois:

```text
python manage.py check --deploy
```

## Credenciais bancárias

Nunca coloque no Git, JavaScript, HTML, prints, logs ou mensagens:

- Client Secret;
- Access Token;
- senha do Mercado Pago;
- `FINANCEIRO_CREDENTIAL_KEY`;
- `DJANGO_SECRET_KEY`.

No banco, Client Secret e Access Token são armazenados criptografados com
Fernet. No modo seguro, uma `FINANCEIRO_CREDENTIAL_KEY` dedicada é
obrigatória.

A operação de criar/alterar uma integração exige novamente a senha atual do
Financeiro OFX.

## Mercado Pago — própria conta

O modo recomendado é:

```text
Autenticação = Client ID + Client Secret
```

O servidor chama:

```text
POST https://api.mercadopago.com/oauth/token
```

com `grant_type=client_credentials`, recebe um Access Token temporário,
armazena-o criptografado e o renova antes da expiração.

A Public Key não é necessária para o relatório Dinheiro em conta porque não
há chamada frontend ao Mercado Pago.

## Mercado Pago — conta de terceiro

Não peça senha, Client Secret ou Access Token do titular por mensagem.

Para integrações de terceiros, a evolução correta é OAuth Authorization Code,
com consentimento do titular e escopo limitado. O modo Client Credentials
implementado nesta etapa deve ser usado para recursos da própria conta.

## Proteções implementadas

- autenticação Django;
- senha mínima de 12 caracteres;
- limitação persistente de tentativas por usuário e por IP;
- mensagens genéricas no bloqueio de login;
- expiração de sessão por inatividade;
- `HttpOnly` e `SameSite` para sessão;
- `Secure` para cookies no modo HTTPS;
- CSRF do Django;
- `X-Frame-Options: DENY`;
- Content Security Policy;
- Subresource Integrity nos scripts/estilos CDN;
- `Cache-Control: no-store` em páginas autenticadas;
- HSTS no modo seguro;
- lista explícita de hosts;
- limite de tamanho de uploads;
- credenciais criptografadas;
- reautenticação antes de alterar credenciais bancárias;
- trilha de auditoria para ações de integração;
- API Mercado Pago com hostname fixo e HTTPS;
- redirects externos recusados;
- timeouts de conexão/leitura;
- mensagens de erro da API sanitizadas;
- relatório API limitado a 20 MB no download;
- `file_name` validado contra a lista devolvida pela própria API;
- backup do SQLite antes de migrations;
- testes executados antes de alterar o banco durante atualização;
- Waitress recusa exposição de rede não autorizada;
- `manage.py check --deploy` no modo seguro.

## MFA

MFA ainda não foi implementado nesta etapa. Para qualquer instalação exposta
publicamente na Internet, MFA é a próxima camada prioritária de autenticação,
especialmente para usuários administradores.

## Rotação de credenciais

Se Client ID/Client Secret forem renovados no Mercado Pago:

1. abra `Integrações`;
2. edite a integração;
3. informe Client ID e Client Secret novos;
4. confirme sua senha do Financeiro OFX;
5. salve;
6. clique em `Testar`.

O token temporário anterior é invalidado no cadastro local e um novo será
obtido na próxima chamada.

## Incidente ou suspeita de vazamento

1. Remova temporariamente o acesso externo ao Financeiro OFX.
2. Renove Client ID/Client Secret ou Access Token no Mercado Pago.
3. Atualize a integração no Financeiro OFX.
4. Troque senhas dos usuários administrativos.
5. Revise `Admin > Eventos de segurança`.
6. Preserve os backups e logs para análise.
7. Se `FINANCEIRO_CREDENTIAL_KEY` tiver vazado, considere todas as credenciais
   criptografadas com ela comprometidas e faça rotação das credenciais
   bancárias antes de trocar a chave local.


## Acesso temporário pela rede local

O Gerenciador possui duas ações:

```text
Abrir para rede local
Fechar acesso de rede
```

`Abrir para rede local` não publica o sistema na Internet. Ele configura o
Waitress para escutar na máquina e cria uma regra do Windows Firewall
restrita ao perfil de rede `Private` e à origem `LocalSubnet`.

Mesmo assim, esse acesso utiliza HTTP. Portanto:

- use somente em Wi-Fi/LAN privada e confiável;
- não use em Wi-Fi público;
- não encaminhe a porta 8000 no roteador;
- não use essa opção como substituto de HTTPS;
- credenciais bancárias não podem ser criadas/alteradas remotamente por HTTP.

Para voltar ao modo mais restrito, use `Fechar acesso de rede`. O servidor
volta para `127.0.0.1` mesmo se a remoção da regra do Firewall falhar.


## Recuperação de senha

- senhas continuam armazenadas pelos hashers do Django; a senha atual não pode
  ser exibida nem recuperada em texto claro;
- o Gerenciador local pode apenas verificar um candidato com `check_password()`
  ou gravar uma nova senha com `set_password()`;
- a redefinição local exige acesso ao computador e ao banco SQLite da aplicação;
- alteração do e-mail de recuperação dentro do site exige a senha atual;
- recuperação por e-mail mantém resposta genérica para não revelar se um
  endereço está ou não cadastrado;
- links de recuperação usam tokens de uso único e expiram em 1 hora nesta
  configuração;
- o fluxo de recuperação por link é bloqueado em HTTP remoto/LAN e permitido
  apenas em localhost ou HTTPS;
- credenciais SMTP ficam somente no `.env` local e não devem ser publicadas no
  GitHub.

## Multiusuário e autoria

Cada pessoa deve utilizar sua própria conta. Compartilhar usuário/senha elimina
a capacidade de atribuir uma operação corretamente.

A Etapa 10.8 registra alterações autenticadas em `AuditEvent`. A trilha é
somente leitura na interface administrativa e não armazena valores de senha,
token ou segredo. Falhas de login e bloqueios ficam em `SecurityEvent`, e
decisões de acesso negadas para usuários autenticados também são auditadas.

Desativar um usuário invalida suas sessões ativas. Redefinição administrativa
de senha também encerra sessões antigas do usuário afetado.

Gerenciamento de usuários (criar, alterar perfil/estado e redefinir senha) exige
`localhost` ou HTTPS, além da reautenticação pela senha do administrador. O modo LAN
por HTTP permanece adequado apenas para operações não sensíveis de consulta/operação.
A área `/admin/`, alteração da própria senha e alteração do e-mail de recuperação
também são bloqueadas em HTTP remoto/LAN; use o computador local ou HTTPS para essas
superfícies sensíveis.

## Auditoria automatizada

Antes de migrations, o instalador executa:

```text
python manage.py security_audit --fail-on-high
```

O comando agrega os checks de deploy do Django e verificações locais de
configuração, CSRF, escaping, padrões de injeção, segredos e recursos externos.
Consulte `SECURITY_AUDIT.md`.



## Controle do processo no Windows

O endpoint `/__health__/` não exige autenticação porque é utilizado pelo
Gerenciador antes do login. Ele não retorna dados financeiros, usuário,
configurações ou segredos. O PID é retornado somente em loopback e é usado para
impedir que o botão de parada encerre um processo não relacionado.

A elevação UAC utilizada para registrar a tarefa automática ou encerrar um
servidor legado é transitória. O processo Waitress normal continua executando
com privilégios limitados do usuário atual.
