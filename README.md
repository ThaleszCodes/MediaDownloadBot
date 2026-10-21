# MediaDownloadBot — Termux

Envie um link público `https://www.erome.com/a/IDDOALBUM` no privado do bot.
Ele mostra **Baixar fotos**, **Baixar vídeos** e **Baixar Todos** e envia cada mídia no chat.
Qualquer pessoa pode usar. Não precisa de IA, banco de dados, webhook ou FFmpeg.
Use somente conteúdo não explícito e autorizado. Não há classificação visual automática:
o bot não garante bloquear conteúdo explícito. Não contorna login ou bloqueios.

## Instalar

No Termux, execute:

```bash
pkg update && pkg upgrade -y
pkg install python git nano -y
git clone https://github.com/ThaleszCodes/MediaDownloadBot.git
cd MediaDownloadBot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Crie um bot com `/newbot` no @BotFather. Cole seu token depois do `=` no `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=COLE_SEU_TOKEN_AQUI
```

No nano: Ctrl+O, Enter e Ctrl+X. Não compartilhe o token. `.env` é ignorado pelo Git.

```bash
termux-wake-lock
python bot.py
```

Abra o bot no Telegram, envie `/start` e depois um link real de um álbum não explícito
autorizado. `IDDOALBUM` é apenas um exemplo. Ctrl+C encerra; depois use `termux-wake-unlock`.

Para iniciar de novo:

```bash
cd ~/MediaDownloadBot
source .venv/bin/activate
python bot.py
```

Desative a otimização de bateria do Termux no Android. O wake lock não garante que o
Android mantenha o processo vivo. Celular desligado, processo parado ou sem internet = bot offline.
Apenas uma instância por token. Downloads e envios de todos os usuários usam sua conexão.

## Limites e comportamento

- Até 50 mídias por álbum e 49 MiB por arquivo. Sem compressão: arquivos grandes contam como falha.
- Dois downloads simultâneos, um pedido por pessoa e intervalo de 30 segundos.
- Dez minutos por pedido após sair da fila. Temporários apagados ao terminar ou falhar.
- Envia fotos/vídeos individualmente na ordem do álbum. Se Telegram recusar o formato,
  tenta documento. Não promete reproduzir todo codec de vídeo no aplicativo.
- Uma falha não impede os demais arquivos. Não repete automaticamente envios com timeout,
  pois podem ter chegado mesmo sem confirmação.
- Fila e botões em andamento não persistem após reiniciar. Atualizações antigas são descartadas.
- Só aceita HTTPS e mídia nos domínios do Erome. Mudança de CDN, HTML, redirecionamentos
  ou bloqueios pode exigir ajuste. Não há bypass de proteção.
- Não grava links em logs. Mensagens enviadas permanecem no Telegram.

## Validação

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Testes com HTML sintético e HTTP simulado, sem álbuns reais.
Não foi feito envio real no Telegram, pois o token deve ser configurado no seu celular.
Teste manualmente: /start, link inválido, três botões num álbum não explícito autorizado,
álbum inexistente e segundo pedido durante download. O parser depende do HTML público atual.
