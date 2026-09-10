# Financeiro OFX — instalação em um Windows novo

Este guia cobre dois cenários diferentes. Escolha apenas um deles.

## 1. Instalação realmente nova, sem levar os dados atuais

Leve apenas o ZIP completo da versão mais recente do Financeiro OFX.
Não copie `.venv`, `db.sqlite3`, `.env`, `staticfiles`, `logs`, `run`,
`__pycache__`, backups antigos ou patches.

No computador novo:

1. Instale o **Python Install Manager** oficial e o runtime **Python 3.14**.
2. Abra PowerShell e confirme:

   ```powershell
   py -3.14 --version
   ```

3. Descompacte o ZIP do Financeiro OFX em uma pasta local.
4. Execute `Gerenciar-Financeiro-OFX.bat`.
5. Use a opção de instalação/atualização. O projeto criará `.venv`, instalará
   `requirements.txt`, criará `.env`, executará testes, migrations e
   `collectstatic`. É necessário acesso à internet para instalar dependências.
6. Inicie o Financeiro OFX e abra **no próprio computador**:

   ```text
   http://127.0.0.1:8000/
   ```

   Se ainda não existir administrador, o site abrirá automaticamente a tela
   **Primeiro acesso**. Informe nome, usuário, e-mail de recuperação e senha.
   O próprio sistema criará o administrador e fará o primeiro login. Não é
   necessário executar `manage.py createsuperuser`.
7. Configure Pluggy e demais integrações pela interface do sistema.
8. Se quiser acesso pela rede local ou inicialização automática, configure-os
   novamente no Gerenciador. Essas configurações do Windows não são copiadas
   junto com a pasta do projeto.

## 2. Novo computador levando a instalação e os dados atuais

Além do ZIP completo da versão mais recente, copie de forma segura:

- `db.sqlite3` — usuários, bancos, contas, movimentações, auditoria, itens Pluggy etc.;
- `media\` — arquivos OFX/PDF e demais arquivos enviados ao sistema;
- `.env` — **obrigatório para manter as chaves da instalação**. Em especial,
  `FINANCEIRO_CREDENTIAL_KEY` é usada para descriptografar os segredos de
  integração armazenados no banco.

### Procedimento recomendado

1. Pare o Financeiro OFX no computador antigo.
2. Faça um backup pelo Gerenciador ou copie `db.sqlite3` com o servidor parado.
3. Copie `db.sqlite3`, a pasta `media` e `.env` para mídia segura.
4. No computador novo, descompacte primeiro o ZIP completo da versão atual.
5. Antes da instalação, coloque `db.sqlite3`, `media\` e `.env` na raiz do projeto.
6. Execute `Gerenciar-Financeiro-OFX.bat` e instale/atualize. O instalador
   preserva `.env`, cria a `.venv`, instala dependências, executa testes e
   migrations e cria backup do banco antes de aplicar migrations.
7. Valide login, Dashboard, arquivos históricos e Open Finance.
8. Reconfigure inicialização automática, Firewall/LAN e atalhos no novo Windows.

> **Não envie `.env` por e-mail, GitHub ou repositório público.** Ele contém
> material criptográfico e possivelmente configurações SMTP. Use pendrive
> protegido, pasta criptografada ou outro canal sob seu controle.

## O que não precisa copiar

- `.venv\` — deve ser recriada no novo computador;
- `staticfiles\` — é regenerada por `collectstatic`;
- `logs\` e `run\` — são artefatos de execução;
- `__pycache__\` / `*.pyc`;
- patches antigos;
- ZIPs de versões antigas;
- `.git\`, a menos que queira manter o clone/histórico Git nesse computador;
- `backups\`, a menos que queira guardar também o histórico de backups locais.

## Git é opcional

Para instalar e usar o Financeiro OFX a partir do ZIP, Git não é necessário.
Se for utilizar os recursos de sincronização com GitHub do próprio projeto,
instale Git for Windows e configure a autenticação/repositório nesse computador.

## Checklist final

```text
Python 3.14 disponível via py -3.14
ZIP mais recente descompactado
Gerenciar-Financeiro-OFX.bat executado
Testes OK
Migrations OK
Superusuário criado/restaurado
Pluggy validado
Backup validado
Firewall/LAN configurados apenas se necessário
```
