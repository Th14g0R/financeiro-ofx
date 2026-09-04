# Mercado Pago — configuração no Financeiro OFX

## Antes de começar

A integração para consultar relatórios da própria conta não exige que o
Financeiro OFX fique exposto na Internet. O sistema pode continuar em:

```text
http://127.0.0.1:8000/
```

As chamadas para `https://api.mercadopago.com` são feitas do servidor local
para fora.

Antes de armazenar credenciais reais, confirme no `.env`:

```text
DJANGO_DEBUG=False
FINANCEIRO_HOST=127.0.0.1
FINANCEIRO_ALLOW_NETWORK=False
```

## 1. Criar ou escolher uma aplicação Mercado Pago

1. Entre em Mercado Pago Developers.
2. Abra `Suas integrações`.
3. Se já existir uma aplicação adequada à sua conta, você pode usá-la.
4. Caso contrário, escolha `Criar aplicação`.
5. Conclua a identificação/reautenticação solicitada pelo Mercado Pago.
6. Preencha os dados reais da aplicação.

A interface do Mercado Pago pode mudar; use as opções que correspondam ao uso
real da sua conta.

## 2. Credenciais de produção

Dentro da aplicação:

```text
Produção
→ Credenciais de produção
```

A tela de produção pode exigir ativação com:

- indústria/ramo;
- website real do negócio;
- aceite de termos e privacidade;
- reCAPTCHA.

Não informe um website fictício.

As credenciais de produção incluem pares como:

```text
Public Key + Access Token
Client ID + Client Secret
```

## 3. Opção recomendada no Financeiro OFX

Use:

```text
Autenticação:
Client ID + Client Secret
```

Isso permite que o backend obtenha um Access Token temporário pelo fluxo:

```text
POST https://api.mercadopago.com/oauth/token

{
    "client_id": "...",
    "client_secret": "...",
    "grant_type": "client_credentials"
}
```

Esse fluxo é adequado para acessar os próprios recursos da aplicação/conta.
O token recebido tem duração limitada e o Financeiro OFX o renova
automaticamente.

A `Public Key` não é utilizada neste fluxo de relatório financeiro.

## 4. Cadastrar no Financeiro OFX

Primeiro confira:

```text
Bancos
→ Mercado Pago
```

Depois:

```text
Contas
→ sua conta Mercado Pago
```

Em seguida:

```text
Integrações
→ Nova integração
```

Preencha:

```text
Nome:
Mercado Pago Principal

Provedor:
Mercado Pago

Conta local:
selecione a conta Mercado Pago cadastrada

Autenticação:
Client ID + Client Secret

Client ID:
cole o Client ID de produção

Client Secret:
cole o Client Secret de produção

Access Token:
deixe vazio neste modo

Senha atual do Financeiro OFX:
confirme sua senha atual

Ativa:
marcado
```

Salve e clique:

```text
Testar
```

Se o teste for aceito, a situação deverá ficar:

```text
Conectada
```

## 5. Opção alternativa: Access Token direto

O Mercado Pago também mostra um `Access Token` nas credenciais de produção.

Se você optar por esse modelo:

```text
Autenticação:
Access Token
```

cole o token no campo correspondente.

Nesse modo, o Financeiro OFX não precisa de Client Secret para realizar as
requisições. A opção Client ID + Client Secret é preferida para a própria
conta porque o sistema pode obter/renovar o token temporário do fluxo Client
Credentials automaticamente.

## 6. Gerar extrato pela API

Depois da conexão:

```text
Integrações
→ Relatórios
```

Informe:

```text
Data inicial
Data final
```

O relatório Dinheiro em conta permite dados de até 60 dias por relatório.

Clique:

```text
Solicitar ao Mercado Pago
```

A API responde de forma assíncrona. O arquivo pode não aparecer
imediatamente.

Depois:

```text
Atualizar lista
```

Quando o arquivo estiver disponível:

```text
Importar para staging
```

O relatório entra no mesmo fluxo seguro de revisão das demais importações.

## 7. Nunca faça

Não coloque Client Secret ou Access Token em:

- Git/GitHub;
- JavaScript do navegador;
- arquivos públicos;
- prints;
- mensagens;
- logs;
- parâmetros de URL.

Não envie suas credenciais para suporte ou para um chat.

## 8. Se renovar as credenciais

Se você renovar Client ID/Client Secret no Mercado Pago:

1. abra a integração no Financeiro OFX;
2. clique em editar;
3. informe o novo par;
4. confirme a senha atual do Financeiro OFX;
5. salve;
6. clique em `Testar`.

O token temporário armazenado anteriormente é descartado e um novo será
solicitado.

## 9. Conta de outra pessoa

Para acessar uma conta Mercado Pago que não seja a sua, não peça as
credenciais privadas do titular.

A arquitetura correta para uma evolução multiusuário é OAuth Authorization
Code, com consentimento explícito do titular e acesso limitado.
