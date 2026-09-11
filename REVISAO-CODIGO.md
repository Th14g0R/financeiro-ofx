# Revisão do Financeiro OFX — 10/09/2026

A falha de agrupamento vinha de duas regras: resolução por BANK_ID (alimentado pelo ISPB da Pluggy) e mesclagem de todos os cadastros com esse identificador na reconstrução. Ambas foram removidas. ISPB é mantido apenas como referência bancária.

## Alterações

- CPF/CNPJ completo tem prioridade; documentos divergentes impedem associação por nome ou nome truncado. Documento mascarado isolado não associa nomes diferentes. Correspondências ambíguas permanecem separadas.
- A reconstrução usa pagador/recebedor e documento de `payment_details`, respeitando a direção do movimento, com a descrição original como alternativa.
- `rebuild_counterparties --repair-bank-groups` isola agrupamentos bancários contaminados, preserva seus cadastros/aliases históricos e reatribui movimentos pelos dados originais. Movimentos manuais já vinculados são preservados.
- Listagem de pessoas e detalhe não apresentam ISPB como identidade pessoal. Links de cadastros desativados redirecionam para a lista atual com mensagem.
- Detalhe de pessoa agora tem páginas de 50 movimentos, com totais de todo o filtro, substituindo o corte silencioso em 500 registros.
- Resolução reaproveita aliases pré-carregados, restringe busca de nomes truncados pelo primeiro nome e unifica a busca por nome/alias. Atualização de lotes consulta os arquivos pendentes uma vez, em vez de fazer uma consulta por arquivo.
- Removidos imports sem uso e regras redundantes. Ajustados contraste de texto secundário, foco, alturas de controles, quebra de FITID/textos longos, navegação e espaçamento móvel.

## Validação

- Análise sintática/estática de 144 módulos Python das aplicações e serviços; revisão direcionada de identificação, importação, consultas, templates e JavaScript. Dependências, arquivos gerados, banco e backups não foram tratados como código removível.
- Suíte completa: 268 testes aprovados. Após acrescentar o redirecionamento dos cadastros antigos, 67 testes direcionados aprovados, incluindo o novo caso (269 testes distintos ao todo).
- Django check, verificação de migrações pendentes, sintaxe de todos os JavaScripts próprios e git diff --check sem erros.
- Edge: detalhe renderizado em 1440×1080 e 390×844; controles do filtro com 38 px, alinhamento inferior igual no desktop e ausência de transbordamento horizontal da página. No celular a tabela conserva rolagem horizontal própria.
- Capturas locais em `run/person-desktop.png` e `run/person-mobile.png` (ignoradas pelo Git).

## Reparo da base local

Backup SQLite consistente criado em `backups/before-person-repair-20260910-212546.sqlite3` antes de alterar os vínculos. Foram isolados 10 grupos contaminados e reatribuídos 61 movimentos. Outros 30 movimentos ganharam vínculo reconhecível. Nenhum movimento anteriormente vinculado perdeu sua pessoa.

Os 1.510 registros mantiveram valores, direção, conta, FITID, descrição original e estado de desconsideração financeira. A segunda reconstrução foi verificada dentro de uma transação revertida: zero reatribuições e zero novos grupos isolados. Nenhum cadastro ativo ficou com múltiplos documentos completos.

## Limites

Sem CPF/CNPJ ou outra evidência pessoal suficiente, nomes iguais ainda podem ser homônimos; nome sozinho não comprova identidade. Nomes truncados continuam sujeitos à regra conservadora de prefixo e unicidade. O reparo não inventa documentos ausentes.

A conferência visual cobriu o detalhe de pessoa em desktop/celular, não cada tela e navegador. Não foram realizadas chamadas às instituições financeiras nem sincronizações externas. Bibliotecas e migrações históricas foram preservadas; não houve atualização de dependências.
