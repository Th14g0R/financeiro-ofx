# Financeiro OFX — Pluggy / Meu Pluggy

## Objetivo

Para uso pessoal, o Financeiro OFX usa o **Meu Pluggy** como origem das
conexões bancárias reais e a API Pluggy como canal de leitura dos dados.

Fluxo recomendado:

```text
Banco real
  ↓ consentimento Open Finance
Meu Pluggy
  ↓ proxy Meu Pluggy / Connector 200
Pluggy Dashboard / Development / Demo
  ↓ Item ID do Meu Pluggy
Financeiro OFX
  ↓ GET /items/<itemId>
  ↓ GET /accounts?itemId=<itemId>
  ↓ GET /v2/transactions?accountId=<accountId>
Banco de dados local
```

O Item **Sandbox Open Finance** serve apenas para dados sintéticos. Ele não é a
ponte para as conexões reais já existentes em `meu.pluggy.ai`.

## 1. Preparação no Meu Pluggy

1. Acesse `https://meu.pluggy.ai/connections`.
2. Mantenha os bancos reais conectados ali.
3. Confirme que os consentimentos estão ativos.

O Meu Pluggy funciona como Data Passport. Segundo o guia oficial, suas conexões
existentes podem ser reutilizadas pela aplicação Demo do Dashboard através do
conector Meu Pluggy, sem criar novo consentimento bancário.

## 2. Credenciais da API

1. Acesse `https://dashboard.pluggy.ai`.
2. Selecione o ambiente **Development**.
3. Use o Client ID e Client Secret da Development Application do Financeiro.
4. No Financeiro, abra `Open Finance > Credenciais da API Pluggy`.
5. Salve as credenciais e execute **Testar API**.

Client Secret e API Key permanecem exclusivamente no backend.

## 3. Criar o Item proxy para dados reais

1. No Dashboard, abra a aplicação de Development e entre em **Demo**.
2. Clique em **Conectar Conta**.
3. Procure e selecione **Meu Pluggy** — não selecione `Sandbox Open Finance`.
4. Entre com a mesma conta usada em `meu.pluggy.ai`.
5. Conclua o vínculo com as conexões existentes do Meu Pluggy.
6. No menu do Item criado, clique em **Copiar Item ID**.
7. No Financeiro, cole o UUID em **Registrar Item ID do Meu Pluggy**.
8. O backend valida o Item com `GET /items/<itemId>` antes de persistir.
9. Clique em **Copiar dados**.

Para dados reais do fluxo pessoal, o Item esperado é do **Meu Pluggy / Connector
200**.

## 4. Entendendo o status

O Financeiro mostra separadamente:

- `status` do Item na Pluggy;
- `executionStatus` da execução;
- data da última atualização na Pluggy;
- data da última cópia para o banco local;
- `statusDetail`/`executionReport` quando a Pluggy os retornar.

Principais combinações:

```text
UPDATING                      = sincronização ainda em andamento
UPDATED / SUCCESS             = sincronização concluída
UPDATED / PARTIAL_SUCCESS     = concluída, mas algum produto falhou
OUTDATED                      = execução terminou com erro recuperável
LOGIN_ERROR                   = falha de autenticação/credenciais
```

`PARTIAL_SUCCESS` é estado final. Os produtos concluídos já podem estar
 disponíveis para leitura; consulte os detalhes para identificar o que falhou.

## 5. Cópia para o Financeiro OFX

O Financeiro realiza somente leitura da API:

```text
GET /items/<itemId>
GET /accounts?itemId=<itemId>&type=BANK
GET /v2/transactions?accountId=<accountId>
```

A listagem de transações usa paginação por cursor do endpoint V2.

Nesta revisão o fluxo normal da interface **não dispara PATCH /items/<id>**.
A atualização dos consentimentos/conexões é feita no Meu Pluggy ou no Dashboard;
depois use:

```text
Atualizar situação
Copiar dados
```

Isso evita disparos manuais repetidos e a limitação de frequência de atualização
da Development Application.

## 6. Pluggy Connect embutido (opcional)

O widget embutido continua desativado por padrão:

```env
PLUGGY_EMBEDDED_CONNECT_ENABLED=False
```

Caso seja habilitado explicitamente:

```env
PLUGGY_EMBEDDED_CONNECT_ENABLED=True
```

o frontend usa as opções documentadas:

```javascript
{
  connectorIds: [200],
  selectedConnectorId: 200,
  includeSandbox: false
}
```

## 7. Segurança

- Client Secret e API Key nunca são enviados ao navegador.
- Item ID é validado novamente no backend antes de ser gravado.
- Operações POST permanecem protegidas por CSRF.
- Operações sensíveis continuam restritas a localhost ou HTTPS.
- Dados financeiros existentes não são sobrescritos silenciosamente quando a
  origem remota divergir.
- O menu principal não expõe mais a antiga área de integração bancária direta;
  o caminho principal passa a ser **Open Finance**.
- O código legado de integração direta é mantido temporariamente apenas para
  compatibilidade/migração, sem ser apresentado no fluxo normal da interface.

## Problemas comuns

### Só aparece Sandbox Open Finance

O Sandbox é um Item separado, com dados fictícios. Volte à Demo, clique em
**Conectar Conta** e procure especificamente por **Meu Pluggy**.

Se o conector Meu Pluggy não aparecer mesmo com a conta correta e a aplicação de
Development selecionada, confirme a disponibilidade do conector no Dashboard e,
se necessário, abra chamado com o suporte Pluggy.

### Recebi erro dizendo para aguardar 1 hora

Development Applications podem ter frequência mínima para atualizações manuais
de Item. Não repita o PATCH. Para o fluxo Meu Pluggy, atualize/gerencie a conexão
no Meu Pluggy/Dashboard e use no Financeiro apenas **Atualizar situação** e
**Copiar dados**.

### O Item está em PARTIAL_SUCCESS

A execução terminou; não está mais processando. Abra **Detalhes retornados pela
Pluggy** para identificar quais produtos foram atualizados e quais falharam.


## Exclusão / rollback local de dados copiados

A partir da Etapa 10.9.4, a tela **Open Finance / Meu Pluggy** permite excluir os dados
copiados de um Item inteiro ou de uma única conta Pluggy. A exclusão atua somente no
Financeiro OFX e nunca apaga o Item ou o consentimento no Pluggy Dashboard/Meu Pluggy.

O sistema só apaga uma movimentação financeira quando a origem é comprovadamente Pluggy
(`source_type=API`, `raw_data.provider=PLUGGY` e FITID gerado pelo importador Pluggy).
Se um lançamento OFX/PDF/manual existente tiver sido apenas associado a um vínculo Pluggy,
o lançamento é preservado. Contas locais só são removidas mediante opção explícita, quando há evidência de que foram
criadas pela própria Pluggy e se ficarem vazias, sem importações, outras integrações ou outros vínculos Pluggy.

Toda exclusão exige a senha atual e a confirmação textual `EXCLUIR`.
