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


## Bancos reais retornados pelo Meu Pluggy

O conector `Meu Pluggy (200)` é um proxy e **não deve ser cadastrado como banco** no
Financeiro OFX. A partir da Etapa 10.9.5, a cópia identifica a instituição de cada conta
retornada e relaciona a conta local diretamente ao banco real. Se o banco ainda não existir,
é cadastrado automaticamente. Um COMPE `000` é tratado como placeholder e ignorado.

Contas criadas por versões anteriores sob o banco `MeuPluggy` são migradas na próxima
execução de **Copiar dados**: a mesma conta local é reclassificada para o banco real, logo
as movimentações existentes continuam com os mesmos IDs e não são recriadas.

## Exclusão / rollback local de dados copiados

A partir da Etapa 10.9.5, a tela **Open Finance / Meu Pluggy** permite excluir os dados
copiados de um Item inteiro ou de uma única conta Pluggy, incluindo opcionalmente contas
e bancos locais que tenham sido cadastrados automaticamente pela integração. A exclusão
atua somente no Financeiro OFX e nunca apaga o Item ou o consentimento no Pluggy Dashboard/Meu Pluggy.

O sistema só apaga uma movimentação financeira quando a origem é comprovadamente Pluggy
(`source_type=API`, `raw_data.provider=PLUGGY` e FITID gerado pelo importador Pluggy).
Se um lançamento OFX/PDF/manual existente tiver sido apenas associado a um vínculo Pluggy,
o lançamento é preservado. Contas e bancos locais só são removidos mediante opção explícita
e quando a proveniência Pluggy está comprovada, ficaram vazios e não possuem importações,
outras integrações ou vínculos que precisem ser preservados.

Toda exclusão exige a senha atual e a confirmação textual `EXCLUIR`.


## Etapa 10.9.6 — deduplicação, contas similares e identidade

A cópia do Pluggy agora participa do mesmo processo de revisão financeira das importações OFX/PDF.

- O sistema não usa FITID como única evidência entre fontes diferentes. Ele compara conta, banco, natureza, valor, data, descrição e contraparte para gerar uma revisão de duplicidade.
- Duplicidades muito prováveis criadas por uma nova importação podem ficar fora dos totais até decisão do usuário, sem exclusão física do lançamento.
- `paymentData.receiver` é priorizado em saídas e `paymentData.payer` em entradas para vincular Pessoas/Contrapartes. CPF/CNPJ completo, quando presente, tem prioridade sobre variações de nome.
- `Account.owner` e `Account.taxNumber` alimentam Titular/CPF-CNPJ da conta local. O produto `Identity`, quando disponível, é mantido como snapshot no Item.
- Para contas bancárias, `bankData.transferNumber` é usado quando disponível; se estiver ausente, o sistema usa `Account.number` como fallback.
- Números com zeros à esquerda são normalizados para procurar contas semelhantes. Quando a similaridade é forte, a importação para aquela conta aguarda decisão entre **Usar conta existente** e **Manter/criar conta separada**.
- Depois da atualização, use **Movimentações → Analisar duplicidades** para fazer o pente fino do histórico já existente.

## Diagnóstico de Item remoto (10.9.6.2)

Quando a Pluggy devolver HTTP 404, o Financeiro OFX passa a informar em qual etapa a falha ocorreu: consulta do Item, listagem de contas ou listagem de transações. Os dados já copiados localmente não são apagados por uma falha remota.

Na revisão de contas semelhantes, a interface preserva explicitamente qual botão disparou o formulário antes de ativar o estado de carregamento. Isso evita perder a decisão `use_existing`/`keep_separate` ao desabilitar os botões durante o envio.

## Detalhes de transferências e Cofrinho (10.9.9)

A partir da 10.9.9, `paymentData` é normalizado no lançamento local para preservar,
quando a instituição fornecer: pagador, recebedor, COMPE/ISPB, agência, conta,
documento, meio de pagamento, referência e código de autenticação. Uma chave PIX
só é exibida quando vier explicitamente em algum campo do payload; ela não é
inferida a partir de CPF, telefone ou conta.

Movimentos identificados com segurança como transferência entre o saldo disponível
e Cofrinho/reserva da mesma conta ficam no extrato e na auditoria, mas são tratados
como movimentação interna e não compõem entrada/saída externa no Dashboard.
Rendimentos/juros/CDI permanecem contabilizados como receita real.

Para reaproveitar os metadados em lançamentos Pluggy já existentes, a migration da
10.9.9 faz um backfill conservador a partir do `raw_data` já armazenado. Executar
**Copiar dados e organizar bancos** novamente também atualiza esses campos com o
payload mais recente e reexecuta a classificação de Cofrinho/reserva.


## Categorias de transações (10.9.10)

Quando a API retornar `category` e `categoryId`, o Financeiro OFX preserva esses
valores como metadados da origem e cria/reutiliza uma categoria local com o mesmo
nome. Se `category` não vier, `merchant.category` pode ser usado como fallback.
A disponibilidade da categorização depende dos recursos habilitados na conta Pluggy.

A primeira categoria recebida pode ser aplicada automaticamente ao lançamento. Depois
que o usuário altera a categoria no Financeiro OFX, essa decisão passa a ser manual e
não é sobrescrita por sincronizações posteriores. A alteração local também não envia
um PATCH de categorização para a Pluggy; ela vale somente no Financeiro OFX.

Use **Movimentações** para filtrar por categoria ou alterar a categoria de um lançamento
sem liberar a edição dos demais campos financeiros. A tela de **Revisão de duplicidades**
também aceita filtro por categoria.

## Categorias em português-BR e Dashboard (10.9.11)

O Financeiro OFX mantém `source_category_name` e `source_category_id` exatamente como
foram recebidos da Pluggy, mas utiliza uma categoria local traduzida para português-BR.
Exemplos: `Transfers` → `Transferências`, `Shopping` → `Compras` e
`Proceeds interests and dividends` → `Rendimentos, juros e dividendos`.

A tradução local não envia alteração para a Pluggy e não sobrescreve uma categoria que
tenha sido escolhida manualmente pelo usuário. Se a Pluggy introduzir uma categoria que
ainda não exista no catálogo local, o nome original é preservado como fallback.

O Dashboard usa a categoria local para montar gráficos separados de entradas e saídas
externas por categoria. Os gráficos respeitam o período e o banco selecionados e permitem
abrir o Extrato filtrado clicando na barra correspondente. Transferências confirmadas entre
contas próprias e movimentações de Cofrinho/reserva continuam fora desses gráficos externos.

